"""jobwrapper - command line interface.

Everything the web UI can do, plus the things a terminal is better at (cron, piping, scripting).
"""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import paths
from .config import Config, SourceConfig
from .llm import LLMClient
from .logging_setup import setup
from .models import Profile
from .models.resume import MasterResume
from .store import Store

app = typer.Typer(add_completion=False, no_args_is_help=True,
                  help="Find jobs, tailor a resume per job, and fill the applications.")
resume_app = typer.Typer(help="Master resume: import, tailor, sync with Overleaf.")
sources_app = typer.Typer(help="Job sources.")
answers_app = typer.Typer(help="The answer bank.")
vault_app = typer.Typer(help="Encrypted credential vault.")
app.add_typer(resume_app, name="resume")
app.add_typer(sources_app, name="sources")
app.add_typer(answers_app, name="answers")
app.add_typer(vault_app, name="vault")

console = Console()


def ctx() -> tuple[Config, Store, Profile, MasterResume]:
    layout = paths.ensure_layout()
    config = Config.load()
    return (config, Store(), Profile.load(layout["profile"]),
            MasterResume.load(layout["master_resume"]))


def score_style(score: int) -> str:
    return "bold green" if score >= 75 else "yellow" if score >= 55 else "dim"


# --------------------------------------------------------------------------- setup
@app.command()
def init(open_ui: bool = typer.Option(True, "--open/--no-open", help="Open the web UI after setup")):
    """Create the data directory, write a default config, and open the profile UI."""
    setup()
    layout = paths.ensure_layout()
    config = Config.load()
    profile_path = layout["profile"]
    if not profile_path.exists():
        Profile().save(profile_path)
    console.print(Panel.fit(
        f"[bold]Job Wrapper is set up[/bold]\n\n"
        f"data       {layout['root']}\n"
        f"config     {layout['config']}\n"
        f"profile    {profile_path}\n"
        f"sources    {len([s for s in config.sources if s.enabled])} enabled\n\n"
        f"Next: fill in your profile, then import your resume.\n"
        f"  [cyan]jobwrapper ui[/cyan]                    open the web UI\n"
        f"  [cyan]jobwrapper resume import <file>[/cyan]  load your Overleaf .tex\n"
        f"  [cyan]jobwrapper search[/cyan]                find jobs\n"
        f"  [cyan]jobwrapper apply --limit 3[/cyan]       fill applications (review mode)",
        title="ready"))
    if open_ui:
        ui(port=None, host=None, no_browser=False)


@app.command()
def ui(port: int | None = typer.Option(None), host: str | None = typer.Option(None),
       no_browser: bool = typer.Option(False, "--no-browser")):
    """Start the local web UI (profile intake, jobs, applications, settings)."""
    from .server import serve
    from .server.app import get_state

    setup()
    state = get_state()
    url = f"http://{host or state.config.server.host}:{port or state.config.server.port}"
    console.print(f"[bold]Job Wrapper UI[/bold]  {url}")
    console.print(f"[dim]extension token: {state.config.server.token}[/dim]")
    if not no_browser:
        webbrowser.open(url)
    serve(host=host, port=port)


@app.command("app")
def desktop_app(port: int | None = typer.Option(None, help="Pin the local port")):
    """Open Job Wrapper as a desktop window (no terminal, no browser tab)."""
    setup()
    from .desktop import run as run_desktop

    raise typer.Exit(run_desktop(port=port))


@app.command()
def doctor():
    """Check the environment: browsers, LaTeX, model access, profile completeness."""
    from .resume.compile import available_engines
    from .server.schema import completeness

    setup()
    config, store, profile, master = ctx()
    table = Table(show_header=False, box=None)

    def row(name: str, ok: bool, detail: str) -> None:
        table.add_row(f"[{'green' if ok else 'red'}]{'✓' if ok else '✗'}[/]", name, detail)

    try:
        # look for an installed browser without starting the driver - starting it here just to
        # ask a question leaves a noisy async teardown behind
        from pathlib import Path as _Path

        import playwright  # noqa: F401
        from playwright._impl._driver import compute_driver_executable  # type: ignore

        roots = [_Path.home() / "Library" / "Caches" / "ms-playwright",
                 _Path.home() / ".cache" / "ms-playwright",
                 _Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/nonexistent"))]
        installed = [p for root in roots if root.exists()
                     for p in root.glob("chromium*") if p.is_dir()]
        compute_driver_executable()
        row("browser", bool(installed),
            "chromium ready" if installed else "run `playwright install chromium`")
    except Exception as exc:
        row("browser", False, f"run `playwright install chromium` ({str(exc)[:60]})")

    engines = available_engines()
    row("pdf", True, ", ".join(engines) if engines else
        "no LaTeX found - falling back to the HTML/Chromium renderer")
    llm = LLMClient(config.llm)
    row("claude", llm.available(),
        f"{config.llm.model}" if llm.available() else "no key - deterministic fallbacks in use")
    pct = completeness(profile.model_dump(mode="json"))["_overall"]["pct"]
    missing = profile.missing_required()
    row("profile", not missing, f"{pct}% complete" + (f", missing: {', '.join(missing)}" if missing else ""))
    row("resume", bool(master.experience),
        f"{len(master.experience)} roles" if master.experience else "not imported yet")
    row("sources", any(s.enabled for s in config.sources),
        f"{len([s for s in config.sources if s.enabled])} enabled")
    row("jobs", True, f"{store.jobs.count()} stored, {store.jobs.count('new')} new")
    console.print(Panel(table, title="doctor"))
    store.close()


# --------------------------------------------------------------------------- profile
@app.command()
def profile(edit: bool = typer.Option(False, "--edit", help="Open the profile UI"),
            show: bool = typer.Option(False, "--show", help="Print the profile as JSON")):
    """Inspect or edit your profile."""
    setup()
    layout = paths.ensure_layout()
    data = Profile.load(layout["profile"])
    if edit:
        return ui(port=None, host=None, no_browser=False)
    if show:
        console.print_json(json.dumps(data.model_dump(mode="json")))
        return
    from .server.schema import completeness

    stats = completeness(data.model_dump(mode="json"))
    table = Table("section", "complete")
    for key, value in stats.items():
        if key.startswith("_"):
            continue
        table.add_row(key, f"{value['pct']}%")
    console.print(table)
    console.print(f"overall [bold]{stats['_overall']['pct']}%[/bold]  ·  "
                  f"missing required: {', '.join(data.missing_required()) or 'none'}")


# --------------------------------------------------------------------------- resume
@resume_app.command("import")
def resume_import(path: Path = typer.Argument(..., exists=True),
                  use_llm: bool = typer.Option(True, "--llm/--no-llm"),
                  fill_profile: bool = typer.Option(True, "--fill-profile/--no-fill-profile",
                                                    help="Also fill your profile from it"),
                  overwrite: bool = typer.Option(False, "--overwrite",
                                                 help="Replace answers you already gave")):
    """Import a master resume (.tex from Overleaf, or .pdf/.json/.md/.txt)."""
    setup()
    from .resume.importer import import_master_resume
    from .resume.to_profile import profile_from_resume

    config, store, profile_data, _ = ctx()
    master = import_master_resume(path, LLMClient(config.llm), use_llm=use_llm)
    master.save(paths.ensure_layout()["master_resume"])
    console.print(f"[green]imported[/green] {len(master.experience)} roles, "
                  f"{len(master.projects)} projects, {len(master.education)} education entries, "
                  f"{len(master.skill_groups)} skill groups")

    if fill_profile:
        result = profile_from_resume(master, profile_data, overwrite=overwrite)
        result.profile.save(paths.ensure_layout()["profile"])
        table = Table("field", "from your resume", box=None, pad_edge=False)
        for change in result.changes:
            table.add_row(change.label, str(change.as_dict()["proposed"]))
        console.print(table)
        console.print(f"[green]filled {len(result.changes)} profile field(s)[/green]"
                      + (f", left {len(result.skipped)} you had already answered"
                         if result.skipped else ""))
        missing = result.profile.missing_required()
        console.print(f"still missing: {', '.join(missing)}" if missing
                      else "[green]profile is complete[/green]")
    store.close()


@resume_app.command("tailor")
def resume_tailor(job_id: str, out: Path | None = typer.Option(None)):
    """Tailor the master resume to one job and compile a PDF."""
    setup()
    from .apply.runner import ApplicationRunner

    config, store, profile_data, master = ctx()
    job = store.jobs.get(job_id)
    if not job:
        console.print(f"[red]no job {job_id}[/red]")
        raise typer.Exit(1)
    runner = ApplicationRunner(config, store, profile_data, master)
    tailored, cover, _text = runner.prepare_documents(job)
    console.print(f"[green]{tailored.pdf_path}[/green]")
    console.print(f"ATS {tailored.ats_score}/100 · coverage {tailored.keyword_coverage:.0%} · "
                  f"{len(tailored.violations)} truthfulness flag(s) · engine {tailored.engine_used}")
    for violation in tailored.violations:
        console.print(f"  [yellow]![/yellow] {violation.kind}: {violation.detail}")
    if out and tailored.pdf_path:
        Path(out).write_bytes(Path(tailored.pdf_path).read_bytes())
    store.close()


@resume_app.command("overleaf-auth")
def overleaf_auth(token: str = typer.Option(..., prompt=True, hide_input=True)):
    """Store an Overleaf git-bridge token in the encrypted vault."""
    from .resume.overleaf import save_token
    from .vault import Vault

    save_token(token, Vault())
    console.print("[green]token stored[/green]")


@resume_app.command("overleaf-pull")
def overleaf_pull(url: str | None = typer.Option(None, help="https://git.overleaf.com/<id>"),
                  import_after: bool = typer.Option(True, "--import/--no-import")):
    """Clone or pull your Overleaf project and import the resume from it."""
    setup()
    from .resume.overleaf import sync
    from .vault import Vault

    config = Config.load()
    git_url = url or config.resume.overleaf_git_url
    if not git_url:
        console.print("[red]no Overleaf URL - pass --url or set resume.overleaf_git_url[/red]")
        raise typer.Exit(1)
    result = sync(git_url, paths.ensure_layout()["overleaf"], Vault())
    console.print(("[green]" if result.ok else "[red]") + result.message + "[/]")
    if result.ok and result.main_tex:
        config.resume.overleaf_git_url = git_url
        config.save()
        if import_after:
            resume_import(result.main_tex, use_llm=True)


# --------------------------------------------------------------------------- search
@app.command()
def search(source: list[str] = typer.Option(None, "--source", "-s", help="Only these source ids"),
           show: int = typer.Option(10, help="How many results to print")):
    """Run every enabled source, de-duplicate, score, and store."""
    setup()
    from .pipeline import SearchEngine

    config, store, profile_data, _ = ctx()
    engine = SearchEngine(config, store, profile_data)
    try:
        report = engine.run(only=list(source) if source else None)
    finally:
        engine.close()
    console.print(f"[bold]{report.fetched}[/bold] fetched · "
                  f"[bold]{report.after_dedupe}[/bold] after dedupe · "
                  f"[green]{report.new}[/green] new · {report.updated} updated · "
                  f"{report.disqualified} filtered out · "
                  f"{report.off_target} off target")
    if report.off_target and report.off_target > 4 * (report.new + report.updated):
        console.print("  [yellow]most postings never matched your titles or keywords - "
                      "widen them in Settings if you expected more[/yellow]")
    for source_id, error in report.errors.items():
        console.print(f"  [red]{source_id}[/red]: {error[:90]}")
    if show:
        jobs(limit=show, min_score=0, status="new", search_text=None, json_out=False)
    store.close()


@app.command("list")
def jobs(limit: int = typer.Option(20), min_score: int = typer.Option(0),
         status: str | None = typer.Option(None),
         search_text: str | None = typer.Option(None, "--search"),
         json_out: bool = typer.Option(False, "--json")):
    """List stored jobs, best match first."""
    setup()
    config, store, _profile, _master = ctx()
    found = store.jobs.list(status=status, min_score=min_score, limit=limit, search=search_text)
    if json_out:
        console.print_json(json.dumps([j.model_dump(mode="json") for j in found]))
        store.close()
        return
    table = Table(box=None, pad_edge=False)
    table.add_column("score", width=5, justify="right")
    table.add_column("id", width=10, no_wrap=True)
    table.add_column("title", overflow="ellipsis", no_wrap=True, max_width=44)
    table.add_column("company", overflow="ellipsis", no_wrap=True, max_width=18)
    table.add_column("location", overflow="ellipsis", no_wrap=True, max_width=20)
    table.add_column("salary", no_wrap=True)
    for job in found:
        table.add_row(f"[{score_style(job.match_score)}]{job.match_score}[/]", job.id,
                      job.title, job.company, job.location or "—", job.salary.as_text() or "—")
    console.print(table)
    store.close()


@app.command()
def show(job_id: str):
    """Show one job with its match reasoning."""
    setup()
    config, store, _profile, _master = ctx()
    job = store.jobs.get(job_id)
    if not job:
        console.print(f"[red]no job {job_id}[/red]")
        raise typer.Exit(1)
    console.print(Panel(f"[bold]{job.title}[/bold] at {job.company}\n"
                        f"{job.location} · {job.source} · score {job.match_score}\n{job.url}"))
    for reason in job.match_reasons:
        console.print(f"  [green]+[/green] {reason}")
    for gap in job.match_gaps:
        console.print(f"  [yellow]-[/yellow] {gap}")
    console.print(f"\n{job.description[:2500]}")
    store.close()


# --------------------------------------------------------------------------- apply
@app.command()
def apply(job_id: list[str] = typer.Option(None, "--job", "-j"),
          limit: int = typer.Option(5),
          autonomy: str | None = typer.Option(None, help="dryrun | review | auto"),
          headless: bool | None = typer.Option(None),
          yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation")):
    """Tailor a resume and fill the application for each job."""
    setup()
    from .apply import ApplicationRunner

    config, store, profile_data, master = ctx()
    if autonomy:
        config.apply.autonomy = autonomy  # type: ignore[assignment]
    if headless is not None:
        config.apply.headless = headless

    missing = profile_data.missing_required()
    if missing:
        console.print(f"[red]profile incomplete:[/red] {', '.join(missing)}")
        console.print("run [cyan]jobwrapper ui[/cyan] to fill it in")
        raise typer.Exit(1)

    if job_id:
        selected = [store.jobs.get(i) for i in job_id]
        selected = [j for j in selected if j]
    else:
        selected = store.jobs.list(status="new", min_score=config.match.min_score_to_apply,
                                   limit=limit)
    if not selected:
        console.print("[yellow]nothing to apply to[/yellow]")
        raise typer.Exit(0)

    console.print(f"[bold]{len(selected)}[/bold] job(s) at autonomy "
                  f"[bold]{config.apply.autonomy}[/bold]:")
    for job in selected[:limit]:
        console.print(f"  {job.match_score:>3}  {job.short()}")
    if config.apply.autonomy == "auto" and not yes:
        typer.confirm("This will SUBMIT applications automatically. Continue?", abort=True)
    elif not yes:
        typer.confirm("Open a browser and fill these in?", abort=True)

    runner = ApplicationRunner(config, store, profile_data, master)
    report = runner.run(selected, limit=limit)
    console.print(f"\n[green]{report.submitted}[/green] submitted · "
                  f"[cyan]{report.ready_for_review}[/cyan] ready for review · "
                  f"[yellow]{report.needs_input}[/yellow] need input · "
                  f"{report.skipped} skipped · [red]{report.failed}[/red] failed")
    for application in report.applications:
        if application.status in {"needs_input", "failed"}:
            console.print(f"  [yellow]{application.company}[/yellow]: "
                          f"{application.notes or application.error}")
    store.close()


@app.command()
def run(limit: int = typer.Option(5, help="How many jobs to work through"),
        autonomy: str | None = typer.Option(None, help="dryrun | review | auto"),
        search: bool = typer.Option(True, "--search/--no-search", help="Search before applying"),
        overleaf: bool = typer.Option(True, "--overleaf/--no-overleaf",
                                      help="Pull the latest resume from Overleaf first"),
        headless: bool | None = typer.Option(None),
        yes: bool = typer.Option(False, "--yes", "-y")):
    """The whole loop: pull the resume, search, then tailor and apply one job at a time."""
    setup()
    from .pipeline import Autopilot

    config, store, profile_data, master = ctx()
    if autonomy:
        config.apply.autonomy = autonomy  # type: ignore[assignment]
    if headless is not None:
        config.apply.headless = headless

    missing = profile_data.missing_required()
    if missing:
        console.print(f"[red]profile incomplete:[/red] {', '.join(missing)}")
        console.print("run [cyan]jobwrapper ui[/cyan] to fill it in")
        raise typer.Exit(1)

    llm = LLMClient(config.llm)
    console.print(Panel.fit(
        f"[bold]Autopilot[/bold]\n"
        f"jobs        up to {limit}\n"
        f"autonomy    {config.apply.autonomy}"
        f"{'  [red](submits by itself)[/red]' if config.apply.autonomy == 'auto' else ''}\n"
        f"search      {'yes' if search else 'no'}\n"
        f"overleaf    {'yes' if overleaf and config.resume.overleaf_git_url else 'no'}\n"
        f"tailoring   {'Claude ' + config.llm.model if llm.available() else 'deterministic ranker (no API key)'}",
        title="about to run"))
    if not yes:
        typer.confirm("Start?", abort=True)

    def show(event) -> None:
        prefix = f"[dim]{event.index}/{event.total}[/dim] " if event.total else ""
        who = f"[bold]{event.company}[/bold] — " if event.company else ""
        colour = {"submitted": "green", "needs_input": "yellow", "failed": "red"}.get(event.status, "")
        text = f"[{colour}]{event.message}[/{colour}]" if colour else event.message
        console.print(f"  {prefix}[cyan]{event.stage}[/cyan] {who}{text}")

    pilot = Autopilot(config, store, profile_data, master, llm, on_progress=show)
    try:
        report = pilot.run(limit=limit, do_search=search, do_overleaf=overleaf)
    except KeyboardInterrupt:
        pilot.stop()
        console.print("[yellow]stopping after the job in flight...[/yellow]")
        raise
    console.print(f"\n[green]{report.submitted}[/green] submitted · "
                  f"[cyan]{report.ready_for_review}[/cyan] ready for review · "
                  f"[yellow]{report.needs_input}[/yellow] need you · "
                  f"[red]{report.failed}[/red] failed · {report.resumes_built} resume(s) built")
    if llm.available():
        console.print(f"[dim]model spend this run: ${llm.cost_so_far():.3f}[/dim]")
    store.close()


@app.command("model")
def set_model(
    provider: str | None = typer.Option(None, help="anthropic | openai | google | groq | "
                                                   "mistral | deepseek | xai | openrouter | "
                                                   "together | ollama"),
    model: str | None = typer.Option(None, help="Model id; omit for the provider default"),
    key: str | None = typer.Option(None, help="API key (prompted if the provider needs one)"),
    show: bool = typer.Option(False, "--show", help="List providers and what is configured"),
    clear: bool = typer.Option(False, "--clear", help="Forget this provider's key"),
):
    """Choose which model to use, and store its key (encrypted)."""
    setup()
    from .llm.providers import PROVIDERS, get_provider, list_models, looks_like_key
    from .vault import Vault

    config = Config.load()
    vault = Vault(interactive=False)

    if show or not provider:
        table = Table("provider", "key", "models", "in use")
        for pid, entry in PROVIDERS.items():
            stored = bool(vault.get_api_key(pid))
            table.add_row(
                f"{entry.label} [dim]({pid})[/dim]",
                "saved" if stored else ("not needed" if not entry.needs_key else "-"),
                str(len(entry.models)) + "+",
                "[green]yes[/green]" if pid == config.llm.provider else "")
        console.print(table)
        console.print(f"currently: [bold]{get_provider(config.llm.provider).label}[/bold] · "
                      f"{config.llm.model}")
        if not provider:
            return

    entry = get_provider(provider)
    if clear:
        vault.clear_api_key(provider)
        console.print(f"[green]removed the {entry.label} key[/green]")
        return

    if entry.needs_key and not vault.get_api_key(provider) and key is None:
        console.print(f"[dim]get a key at {entry.key_url}[/dim]")
        key = typer.prompt(f"{entry.label} API key", hide_input=True)
    if key:
        if not looks_like_key(provider, key):
            console.print(f"[red]that does not look like a {entry.label} key[/red]")
            raise typer.Exit(1)
        vault.set_api_key(provider, key)

    if not model:
        available = list_models(provider, vault.get_api_key(provider))
        model = entry.default_model
        console.print(f"[dim]{len(available)} model(s) available; using {model}. "
                      f"Pass --model to choose another.[/dim]")

    config.llm.provider, config.llm.model = provider, model
    config.save()
    client = LLMClient(config.llm)
    console.print(f"[green]using {entry.label} · {model}[/green]"
                  f"{'' if client.available() else ' [yellow](no key detected yet)[/yellow]'}")


@app.command()
def status(limit: int = typer.Option(15)):
    """Application pipeline at a glance."""
    setup()
    config, store, _profile, _master = ctx()
    stats = store.applications.stats()
    console.print(" · ".join(f"[bold]{v}[/bold] {k.replace('_', ' ')}" for k, v in stats.items())
                  or "no applications yet")
    table = Table("when", "status", "company", "title", "filled", "notes")
    for application in store.applications.list(limit=limit):
        table.add_row(application.created_at[:16].replace("T", " "), application.status,
                      application.company[:20], application.title[:34],
                      str(application.fields_filled),
                      (application.notes or application.error)[:40])
    console.print(table)
    usage = LLMClient(config.llm).tracker.summary()
    console.print(f"[dim]model spend: ${usage['total']['cost_usd']:.2f} over "
                  f"{usage['total']['calls']} call(s)[/dim]")
    store.close()


@app.command()
def export(out: Path = typer.Option(Path("applications.csv")),
           what: str = typer.Option("applications", help="applications | jobs")):
    """Export to CSV."""
    import csv

    setup()
    config, store, _profile, _master = ctx()
    with out.open("w", newline="") as handle:
        if what == "jobs":
            writer = csv.writer(handle)
            writer.writerow(["id", "score", "title", "company", "location", "source", "url",
                             "salary_min", "salary_max", "posted_at"])
            for job in store.jobs.list(limit=5000):
                writer.writerow([job.id, job.match_score, job.title, job.company, job.location,
                                 job.source, job.url, job.salary.min, job.salary.max,
                                 job.posted_at])
        else:
            writer = csv.writer(handle)
            writer.writerow(["id", "status", "company", "title", "url", "ats", "score",
                             "fields_filled", "created_at", "submitted_at", "resume"])
            for application in store.applications.list(limit=5000):
                writer.writerow([application.id, application.status, application.company,
                                 application.title, application.url, application.ats,
                                 application.match_score, application.fields_filled,
                                 application.created_at, application.submitted_at,
                                 application.resume_path])
    console.print(f"[green]wrote {out}[/green]")
    store.close()


# --------------------------------------------------------------------------- sources
@sources_app.command("list")
def sources_list():
    """Show configured sources and what each returned last run."""
    setup()
    config, store, _profile, _master = ctx()
    runs = {r["source_id"]: r for r in store.sources.all()}
    table = Table("id", "kind", "enabled", "last run", "found", "error")
    for source in config.sources:
        run = runs.get(source.id, {})
        table.add_row(source.id, source.kind, "yes" if source.enabled else "no",
                      (run.get("last_run") or "")[:16], str(run.get("last_count", "")),
                      (run.get("last_error") or "")[:40])
    console.print(table)
    store.close()


@sources_app.command("add")
def sources_add(url: str, company: str = typer.Option(""),
                save: bool = typer.Option(True, "--save/--dry-run")):
    """Point at a company careers page; the ATS and board token are detected for you."""
    setup()
    from .sources import HttpClient, detect_from_url

    config = Config.load()
    http = HttpClient(user_agent=config.user_agent)
    try:
        found = detect_from_url(url, http, company=company)
    finally:
        http.close()
    if not found:
        console.print(f"[red]no known ATS found at {url}[/red]")
        console.print("[dim]that site can still be used with the browser extension (V2)[/dim]")
        raise typer.Exit(1)
    source_id = f"{found.ats}:{found.token or found.tenant}"
    console.print(f"[green]{found.ats}[/green] board '{found.token or found.tenant}' "
                  f"for {found.company}")
    if save:
        config.sources.append(SourceConfig(id=source_id, kind=found.ats,
                                           params=found.as_source_params()))
        config.save()
        console.print(f"added source [bold]{source_id}[/bold]")


@sources_app.command("kinds")
def sources_kinds():
    """List every available source adapter."""
    from .sources import available_kinds

    table = Table("kind", "label", "needs key")
    for entry in available_kinds():
        table.add_row(str(entry["kind"]), str(entry["label"]), "yes" if entry["needs_key"] else "")
    console.print(table)


# --------------------------------------------------------------------------- answers
@answers_app.command("list")
def answers_list(limit: int = typer.Option(50)):
    """Everything the tool has learned."""
    setup()
    config, store, _profile, _master = ctx()
    table = Table("question", "answer", "source", "used", "company")
    for record in store.answers.list(limit):
        table.add_row(record.question[:60], record.answer[:34], record.source,
                      str(record.times_used), record.company or "-")
    console.print(table)
    store.close()


@answers_app.command("set")
def answers_set(question: str, answer: str, company: str = typer.Option("")):
    """Teach the tool an answer."""
    setup()
    config, store, _profile, _master = ctx()
    store.answers.remember(question, answer, company=company, source="human")
    console.print("[green]saved[/green]")
    store.close()


@answers_app.command("forget")
def answers_forget(question: str, company: str = typer.Option("")):
    """Remove a learned answer."""
    setup()
    config, store, _profile, _master = ctx()
    console.print("[green]removed[/green]" if store.answers.forget(question, company)
                  else "[yellow]not found[/yellow]")
    store.close()


# --------------------------------------------------------------------------- vault
@vault_app.command("list")
def vault_list():
    """Domains with stored credentials (never prints secrets)."""
    from .vault import Vault

    setup()
    for domain in Vault().domains():
        console.print(f"  {domain}")


@vault_app.command("set")
def vault_set(domain: str, username: str,
              password: str = typer.Option(..., prompt=True, hide_input=True)):
    """Store credentials for a career site you already have an account on."""
    from .vault import Credential, Vault

    setup()
    Vault().put(Credential(domain=domain, username=username, password=password))
    console.print(f"[green]stored credentials for {domain}[/green]")


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted[/dim]")
        sys.exit(130)


if __name__ == "__main__":
    main()
