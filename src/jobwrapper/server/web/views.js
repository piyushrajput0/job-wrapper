/* Views. Each returns HTML and optionally wires itself up in `mount`. */
const Views = (() => {
  const esc = Form.esc;
  const scoreClass = (n) => (n >= 75 ? "hi" : n >= 55 ? "mid" : "lo");
  const statusPill = (s) => {
    const map = { submitted: "good", ready_for_review: "info", needs_input: "warn",
                  failed: "bad", skipped: "", duplicate: "", planned: "info", in_progress: "info" };
    return `<span class="pill ${map[s] ?? ""}">${esc(String(s).replace(/_/g, " "))}</span>`;
  };
  const when = (iso) => {
    if (!iso) return "";
    const d = new Date(iso);
    const days = Math.floor((Date.now() - d) / 86400000);
    return days <= 0 ? "today" : days === 1 ? "yesterday" : `${days}d ago`;
  };

  /* ------------------------------------------------------------ autopilot */
  async function autopilot(api) {
    const [status, current, secrets] = await Promise.all([
      api.get("/api/status"), api.get("/api/autopilot/current"), api.get("/api/secrets"),
    ]);
    const running = current.status === "running";
    const blocked = status.missing_required.length
      ? `Fill in <a href="#/profile">your profile</a> first — missing: ${esc(status.missing_required.join(", "))}`
      : !status.resume.master_loaded
        ? `Import your résumé on the <a href="#/resume">Résumé</a> page first.`
        : "";

    return `
    <div class="card">
      <h3>Run the whole thing</h3>
      <div class="blurb">Pulls your latest résumé from Overleaf, searches every source, then works
        through the best matches <b>one at a time</b> — reading each job description, rewriting your
        résumé around its keywords, compiling a PDF for that job, and filling the application with it.</div>
      ${blocked ? `<div class="banner">${blocked}</div>` : ""}
      ${!status.browser?.ready ? `<div class="banner">
        Job Wrapper fills applications by driving a real browser, and one is not installed yet.
        <button class="btn sm primary" id="ap-install-browser" style="margin-left:8px">Install it (~150 MB)</button>
        <span class="muted" id="ap-browser-state"></span></div>` : ""}
      ${!secrets.current?.usable ? `<div class="banner">No AI model configured — tailoring will use
        the deterministic ranker. Pick a provider in <a href="#/settings">Settings</a>
        (a local Ollama is free) to switch it on.</div>` : ""}
      <div class="form-grid">
        <div class="field" style="grid-column:span 3"><label>How many jobs</label>
          <input type="number" id="ap-limit" value="5" min="1" max="50"></div>
        <div class="field" style="grid-column:span 3"><label>Autonomy</label>
          <select id="ap-autonomy">${["review", "auto", "dryrun"].map((v) =>
            `<option value="${v}"${v === status.autonomy ? " selected" : ""}>${v}</option>`).join("")}</select>
          <div class="help">review fills but never submits</div></div>
        <div class="field" style="grid-column:span 3"><label>Search first</label>
          <label class="switch"><input type="checkbox" id="ap-search" checked><span class="track"></span></label></div>
        <div class="field" style="grid-column:span 3"><label>Pull from Overleaf</label>
          <label class="switch"><input type="checkbox" id="ap-overleaf" checked><span class="track"></span></label></div>
      </div>
      <div class="toolbar" style="margin:14px 0 0">
        <button class="btn primary" id="ap-start" ${running || blocked ? "disabled" : ""}>
          ${running ? "Running…" : "Start run"}</button>
        <button class="btn danger" id="ap-stop" ${running ? "" : "disabled"}>Stop after this job</button>
        <span class="muted" id="ap-state">${running ? esc(current.progress || "starting…") : "idle"}</span>
      </div>
    </div>

    <div class="card" id="ap-live" ${running || (current.events || []).length ? "" : "hidden"}>
      <h3>Progress</h3>
      <div class="ring" style="margin-bottom:10px">
        <span id="ap-count" class="muted">—</span>
        <span class="bar"><i id="ap-bar" style="width:0%"></i></span>
      </div>
      <div id="ap-log" class="mono" style="max-height:340px;overflow:auto;font-size:12.5px"></div>
    </div>

    <div class="card" id="ap-result" hidden><h3>Result</h3><div id="ap-result-body"></div></div>`;
  }

  /* ------------------------------------------------------------ dashboard */
  async function dashboard(api) {
    const [status, jobs, apps] = await Promise.all([
      api.get("/api/status"), api.get("/api/jobs?limit=8"), api.get("/api/applications?limit=6"),
    ]);
    const s = status.applications || {};
    const todo = [];
    if (status.missing_required.length)
      todo.push(`Fill in <a href="#/profile">${status.missing_required.length} required profile field(s)</a>: <span class="mono">${esc(status.missing_required.join(", "))}</span>`);
    if (!status.resume.master_loaded)
      todo.push(`Import your master resume on the <a href="#/resume">Resume</a> page`);
    if (!status.jobs.total)
      todo.push(`Run a search to populate the job list`);
    if (!status.llm.available)
      todo.push(`No Claude key detected - tailoring and answering fall back to the deterministic engine. Set <span class="mono">ANTHROPIC_API_KEY</span> to enable them.`);

    return `
    <div class="grid stats">
      <div class="stat"><div class="k">Jobs found</div><div class="v">${status.jobs.total}</div>
        <div class="d">${status.jobs.new} not yet actioned</div></div>
      <div class="stat"><div class="k">Submitted</div><div class="v">${s.submitted || 0}</div>
        <div class="d">${status.applied_today} today of ${status.daily_cap} cap</div></div>
      <div class="stat"><div class="k">Awaiting review</div><div class="v">${(s.ready_for_review || 0) + (s.needs_input || 0)}</div>
        <div class="d">${s.needs_input || 0} need an answer from you</div></div>
      <div class="stat"><div class="k">Profile</div><div class="v">${status.profile_complete.pct}%</div>
        <div class="d">${status.profile_complete.filled}/${status.profile_complete.total} fields</div></div>
    </div>
    ${todo.length ? `<div class="card" style="margin-top:14px"><h3>Next steps</h3>
      <ul style="margin:8px 0 0;padding-left:18px;line-height:1.9">${todo.map((t) => `<li>${t}</li>`).join("")}</ul></div>` : ""}
    <div class="split" style="margin-top:14px">
      <div class="card"><h3>Top matches</h3><div class="blurb">Highest scoring jobs not yet actioned.</div>
        ${jobs.length ? `<table><tbody>${jobs.map((j) => `<tr>
          <td style="width:52px"><span class="score ${scoreClass(j.match_score)}">${j.match_score}</span></td>
          <td><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
            <div class="muted">${esc(j.company)} · ${esc(j.location || "—")}</div></td></tr>`).join("")}</tbody></table>`
          : '<div class="empty"><h3>No jobs yet</h3><p>Run a search from the Jobs page.</p></div>'}</div>
      <div class="card"><h3>Recent applications</h3><div class="blurb">Everything the tool has touched.</div>
        ${apps.length ? `<table><tbody>${apps.map((a) => `<tr>
          <td>${esc(a.title)}<div class="muted">${esc(a.company)} · ${when(a.created_at)}</div></td>
          <td style="text-align:right">${statusPill(a.status)}</td></tr>`).join("")}</tbody></table>`
          : '<div class="empty"><h3>Nothing applied yet</h3><p>Pick jobs on the Jobs page.</p></div>'}</div>
    </div>
    <div class="card" style="margin-top:14px"><h3>Sources</h3>
      <div class="blurb">Where jobs are coming from. Add a company career page in Settings.</div>
      <table><thead><tr><th>Source</th><th>Kind</th><th>Last run</th><th>Found</th><th>Status</th></tr></thead><tbody>
      ${status.sources.map((src) => {
        const run = (status.source_runs || []).find((r) => r.source_id === src.id) || {};
        return `<tr><td>${esc(src.id)}</td><td class="muted">${esc(src.kind)}</td>
          <td class="muted">${when(run.last_run) || "never"}</td>
          <td>${run.last_count ?? "—"}</td>
          <td>${src.enabled ? (run.last_error ? `<span class="pill bad">error</span>` : `<span class="pill good">on</span>`) : '<span class="pill">off</span>'}</td></tr>`;
      }).join("")}</tbody></table></div>`;
  }

  /* ------------------------------------------------------------ jobs */
  async function jobs(api, params) {
    const query = new URLSearchParams({ limit: "300", min_score: params.min || "0" });
    if (params.q) query.set("q", params.q);
    if (params.status) query.set("status", params.status);
    const list = await api.get(`/api/jobs?${query}`);
    return `
    <div class="toolbar">
      <input type="search" id="job-q" placeholder="Search title or description" value="${esc(params.q || "")}">
      <select id="job-min" style="width:150px">
        ${[0, 50, 65, 75, 85].map((n) => `<option value="${n}"${String(n) === String(params.min || 0) ? " selected" : ""}>Score ≥ ${n}</option>`).join("")}
      </select>
      <select id="job-status" style="width:150px">
        ${["", "new", "submitted", "ready_for_review", "needs_input", "skipped"].map((s) =>
          `<option value="${s}"${s === (params.status || "") ? " selected" : ""}>${s ? esc(s.replace(/_/g, " ")) : "Any status"}</option>`).join("")}
      </select>
      <span class="spacer" style="flex:1"></span>
      <span class="muted">${list.length} job(s)</span>
      <button class="btn" id="btn-search">Run search</button>
      <button class="btn primary" id="btn-apply-selected" disabled>Apply to selected</button>
    </div>
    ${list.length ? `<div class="card" style="padding:6px 6px 2px">
    <table><thead><tr><th style="width:34px"></th><th style="width:56px">Score</th><th>Role</th>
      <th style="width:170px">Company</th><th style="width:150px">Location</th>
      <th style="width:96px">Source</th><th style="width:96px">Posted</th></tr></thead><tbody>
      ${list.map((j) => `
      <tr class="clickable" data-id="${esc(j.id)}">
        <td><input type="checkbox" class="pick" data-id="${esc(j.id)}"></td>
        <td><span class="score ${scoreClass(j.match_score)}">${j.match_score}</span></td>
        <td><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
          ${j.salary?.min ? `<span class="pill good" style="margin-left:6px">${esc(j.salary.min.toLocaleString())}+</span>` : ""}
          ${j.status && j.status !== "new" ? statusPill(j.status) : ""}</td>
        <td>${esc(j.company)}</td><td class="muted">${esc(j.location || "—")}</td>
        <td class="muted">${esc(j.source)}</td><td class="muted">${when(j.posted_at) || "—"}</td>
      </tr>
      <tr class="detail" data-detail="${esc(j.id)}" hidden><td colspan="7">
        <div class="split">
          <div><div class="reasons">
            ${(j.match_reasons || []).map((r) => `<div class="r">+ ${esc(r)}</div>`).join("")}
            ${(j.match_gaps || []).map((g) => `<div class="g">− ${esc(g)}</div>`).join("")}
          </div></div>
          <div><div class="muted" style="max-height:150px;overflow:auto;white-space:pre-wrap">${esc((j.description || "").slice(0, 900))}</div></div>
        </div>
        <div class="toolbar" style="margin:12px 0 4px">
          <button class="btn sm" data-tailor="${esc(j.id)}">Preview tailored resume</button>
          <button class="btn sm primary" data-apply="${esc(j.id)}">Apply now</button>
          <button class="btn sm ghost" data-hide="${esc(j.id)}">Not interested</button>
          <a class="btn sm ghost" href="${esc(j.apply_url || j.url)}" target="_blank" rel="noopener">Open posting</a>
        </div>
      </td></tr>`).join("")}
    </tbody></table></div>`
      : '<div class="empty"><h3>No jobs match</h3><p>Run a search, or relax the filters.</p></div>'}`;
  }

  /* ------------------------------------------------------------ applications */
  async function applications(api) {
    const list = await api.get("/api/applications?limit=100");
    if (!list.length) return '<div class="empty"><h3>No applications yet</h3><p>Pick some jobs and apply.</p></div>';
    return list.map((a) => `
      <div class="card">
        <div style="display:flex;gap:12px;align-items:flex-start">
          <div style="flex:1">
            <h3>${esc(a.title)} <span class="muted">at</span> ${esc(a.company)}</h3>
            <div class="blurb" style="margin:4px 0 10px">
              ${statusPill(a.status)} · ${esc(a.ats || "generic")} · ${when(a.created_at)}
              · ${a.fields_filled} field(s) filled${a.fields_flagged ? `, ${a.fields_flagged} flagged` : ""}
              ${a.match_score ? ` · score ${a.match_score}` : ""}
            </div>
            ${a.notes ? `<div class="banner">${esc(a.notes)}</div>` : ""}
            ${a.error ? `<div class="banner" style="border-left-color:var(--bad)">${esc(a.error)}</div>` : ""}
            <div class="toolbar" style="margin:0">
              ${(a.plan?.fields || []).length && ["ready_for_review", "needs_input"].includes(a.status)
                ? `<button class="btn sm primary" data-review="${esc(a.id)}">Open &amp; refill</button>` : ""}
              ${a.url ? `<a class="btn sm ghost" href="${esc(a.url)}" target="_blank" rel="noopener">Open posting</a>` : ""}
              ${a.resume_path ? `<a class="btn sm ghost" href="/api/artifact?path=${encodeURIComponent(a.resume_path)}" target="_blank">Resume PDF</a>` : ""}
              ${a.cover_letter_path ? `<a class="btn sm ghost" href="/api/artifact?path=${encodeURIComponent(a.cover_letter_path)}" target="_blank">Cover letter</a>` : ""}
            </div>
            ${(a.plan?.fields || []).length ? `<details style="margin-top:10px"><summary class="muted">What was filled (${a.plan.fields.length})</summary>
              <table style="margin-top:8px"><tbody>${a.plan.fields.map((f) => `<tr>
                <td style="width:46%">${esc(f.question)}</td><td>${esc(String(f.value).slice(0, 120))}</td>
                <td style="width:110px" class="muted">${esc(f.method)} ${f.needs_review ? '<span class="pill warn">check</span>' : ""}</td>
              </tr>`).join("")}</tbody></table></details>` : ""}
            ${(a.screenshots || []).length ? `<div class="shots">${a.screenshots.filter(Boolean).map((p) =>
              `<a href="/api/artifact?path=${encodeURIComponent(p)}" target="_blank"><img src="/api/artifact?path=${encodeURIComponent(p)}" alt="step"></a>`).join("")}</div>` : ""}
          </div>
        </div>
      </div>`).join("");
  }

  /* ------------------------------------------------------------ answers */
  async function answers(api) {
    const list = await api.get("/api/answers");
    return `<div class="card"><h3>Answer bank</h3>
      <div class="blurb">Every question the tool has been taught. It never asks twice - edit anything that looks wrong and the next application uses the new answer.</div>
      <div class="toolbar"><input type="search" id="ans-q" placeholder="Filter questions"></div>
      ${list.length ? `<table id="ans-table"><thead><tr><th>Question</th><th style="width:30%">Answer</th>
        <th style="width:110px">Source</th><th style="width:80px">Used</th><th style="width:60px"></th></tr></thead><tbody>
        ${list.map((a) => `<tr data-q="${esc(a.question)}">
          <td>${esc(a.question)}${a.company ? `<div class="muted">only for ${esc(a.company)}</div>` : ""}</td>
          <td><input type="text" value="${esc(a.answer)}" data-answer="${esc(a.question)}" data-company="${esc(a.company)}"></td>
          <td><span class="pill ${a.source === "human" ? "good" : "info"}">${esc(a.source)}</span></td>
          <td class="muted">${a.times_used}</td>
          <td><button class="btn sm danger" data-del="${esc(a.question)}" data-company="${esc(a.company)}">×</button></td>
        </tr>`).join("")}</tbody></table>`
        : '<div class="empty"><h3>Nothing learned yet</h3><p>Questions the tool cannot answer from your profile land here once answered.</p></div>'}
      </div>`;
  }

  /* ------------------------------------------------------------ resume */
  async function resume(api) {
    const [master, status] = await Promise.all([api.get("/api/resume/master"), api.get("/api/status")]);
    const roles = master.experience || [];
    return `
    <div class="card"><h3>Master resume</h3>
      <div class="blurb">The ceiling on what any tailored resume may claim. Import your Overleaf
        <span class="mono">.tex</span> (or a .json/.md/.txt) once; every application then gets its own
        tailored PDF generated from it.</div>
      <div class="toolbar">
        <input type="text" id="import-path" style="flex:1;min-width:280px"
          placeholder="/Users/you/resume.tex   (.tex, .pdf, .json, .md or .txt)">
        <label class="switch"><input type="checkbox" id="import-llm" checked><span class="track"></span>
          <span class="muted">use the model to parse</span></label>
        <label class="switch"><input type="checkbox" id="import-fill" checked><span class="track"></span>
          <span class="muted">fill my profile too</span></label>
        <button class="btn primary" id="btn-import">Import</button>
      </div>
      <div class="muted" style="font-size:12.5px">LaTeX engines detected: ${esc(status.resume.latex_engines.join(", "))}</div>
    </div>
    ${roles.length ? `<div class="card"><h3>Fill your profile from this résumé</h3>
      <div class="blurb">Your résumé already answers most of what an application asks. This copies
        it across — name, contact, address, work history, education, skills with the years each
        one is backed by — and leaves anything you have already answered alone.</div>
      <div class="toolbar">
        <button class="btn" id="btn-preview-fill">See what it would fill</button>
        <button class="btn primary" id="btn-apply-fill">Fill my profile</button>
        <label class="switch"><input type="checkbox" id="fill-overwrite"><span class="track"></span>
          <span class="muted">overwrite what I have already typed</span></label>
      </div>
      <div id="fill-preview"></div>
    </div>

    <div class="card"><h3>What was parsed</h3>
      <dl class="kv">
        <dt>Name</dt><dd>${esc(master.name || "—")}</dd>
        <dt>Contact</dt><dd>${esc(master.email || "—")} · ${esc(master.phone || "—")}</dd>
        <dt>Summary</dt><dd>${esc(master.summary || "—")}</dd>
        <dt>Skill groups</dt><dd>${Object.entries(master.skill_groups || {}).map(([g, v]) =>
          `<strong>${esc(g)}:</strong> ${esc(v.join(", "))}`).join("<br>") || "—"}</dd>
      </dl>
      <h4 style="margin:16px 0 8px">Experience</h4>
      ${roles.map((r) => `<div class="entry"><header><strong>${esc(r.title)}</strong>
        <span class="muted">${esc(r.company)}</span><span class="spacer"></span>
        <span class="muted">${esc(r.start_date)} – ${esc(r.end_date || "present")}</span></header>
        <div class="body"><ul style="margin:0;padding-left:18px">${(r.bullets || []).map((b) =>
          `<li>${esc(b.text)}</li>`).join("")}</ul></div></div>`).join("")}
      ${(master.education || []).length ? `<h4 style="margin:16px 0 8px">Education</h4>
        ${master.education.map((e) => `<div class="muted">${esc(e.institution)} — ${esc(e.degree)}${
          e.minor ? `, minor in ${esc(e.minor)}` : ""}${e.gpa ? ` · GPA ${esc(e.gpa)}` : ""}</div>`).join("")}` : ""}
      </div>` : `<div class="empty"><h3>No master resume loaded</h3>
        <p>Import one above to unlock per-application tailoring.</p></div>`}`;
  }

  /* ------------------------------------------------------------ settings */
  async function settings(api) {
    const [config, status, SECRETS, PROVIDERS] = await Promise.all([
      api.get("/api/config"), api.get("/api/status"), api.get("/api/secrets"),
      api.get("/api/providers")]);
    const s = config.search, a = config.apply, r = config.resume, l = config.llm;
    const list = (v) => (v || []).join(", ");
    return `
    <div class="card"><h3>What to look for</h3>
      <div class="blurb">These drive both the search and the match score.</div>
      <div class="form-grid">
        <div class="field" style="grid-column:span 6"><label>Job titles</label>
          <input type="text" id="s-titles" value="${esc(list(s.titles))}" placeholder="Software Engineer, Backend Engineer"></div>
        <div class="field" style="grid-column:span 6"><label>Excluded title words</label>
          <input type="text" id="s-extitles" value="${esc(list(s.exclude_titles))}"></div>
        <div class="field" style="grid-column:span 6"><label>Keywords</label>
          <input type="text" id="s-keywords" value="${esc(list(s.keywords))}"></div>
        <div class="field" style="grid-column:span 6"><label>Excluded keywords</label>
          <input type="text" id="s-exkeywords" value="${esc(list(s.exclude_keywords))}"></div>
        <div class="field" style="grid-column:span 6"><label>Locations</label>
          <input type="text" id="s-locations" value="${esc(list(s.locations))}"></div>
        <div class="field" style="grid-column:span 3"><label>Posted within (days)</label>
          <input type="number" id="s-days" value="${s.posted_within_days}"></div>
        <div class="field" style="grid-column:span 3"><label>Minimum salary</label>
          <input type="number" id="s-salary" value="${s.min_salary ?? ""}"></div>
        <div class="field" style="grid-column:span 4"><label>Remote only</label>
          <label class="switch"><input type="checkbox" id="s-remote"${s.remote_only ? " checked" : ""}><span class="track"></span></label></div>
        <div class="field" style="grid-column:span 8"><label>Only consider sponsorship-friendly postings</label>
          <label class="switch"><input type="checkbox" id="s-sponsor"${s.require_sponsorship_friendly ? " checked" : ""}><span class="track"></span></label></div>
      </div>
    </div>

    <div class="card"><h3>How to apply</h3>
      <div class="blurb"><strong>Review</strong> fills everything and stops before submit — the default, and
        the one to keep until you trust it. <strong>Auto</strong> submits by itself, within the caps below.</div>
      <div class="form-grid">
        <div class="field" style="grid-column:span 4"><label>Autonomy</label>
          <select id="a-autonomy">${["dryrun", "review", "auto"].map((v) =>
            `<option value="${v}"${v === a.autonomy ? " selected" : ""}>${v}</option>`).join("")}</select></div>
        <div class="field" style="grid-column:span 4"><label>Daily cap</label>
          <input type="number" id="a-daily" value="${a.daily_cap}"></div>
        <div class="field" style="grid-column:span 4"><label>Per-company cap</label>
          <input type="number" id="a-company" value="${a.per_company_cap}"></div>
        <div class="field" style="grid-column:span 4"><label>Minimum score to apply</label>
          <input type="number" id="m-apply" value="${config.match.min_score_to_apply}"></div>
        <div class="field" style="grid-column:span 4"><label>Seconds between applications</label>
          <input type="number" id="a-gap" value="${a.min_seconds_between_applications}"></div>
        <div class="field" style="grid-column:span 4"><label>Run the browser headless</label>
          <label class="switch"><input type="checkbox" id="a-headless"${a.headless ? " checked" : ""}><span class="track"></span></label></div>
        <div class="field" style="grid-column:span 6"><label>Create accounts automatically when a site demands one</label>
          <label class="switch"><input type="checkbox" id="a-signup"${a.auto_signup ? " checked" : ""}><span class="track"></span>
          <span class="muted">off = the form is pre-filled and you press submit</span></label></div>
        <div class="field" style="grid-column:span 6"><label>Generate a cover letter per application</label>
          <label class="switch"><input type="checkbox" id="a-cover"${a.generate_cover_letter ? " checked" : ""}><span class="track"></span></label></div>
      </div>
    </div>

    <div class="card"><h3>Resume &amp; model</h3>
      <div class="form-grid">
        <div class="field" style="grid-column:span 4"><label>Truthfulness firewall</label>
          <select id="r-truth">${["strict", "review", "off"].map((v) =>
            `<option value="${v}"${v === r.truthfulness ? " selected" : ""}>${v}</option>`).join("")}</select>
          <div class="help">Strict reverts any claim the master resume cannot support.</div></div>
        <div class="field" style="grid-column:span 4"><label>Max pages</label>
          <input type="number" id="r-pages" value="${r.max_pages}"></div>
        <div class="field" style="grid-column:span 4"><label>PDF engine</label>
          <select id="r-engine">${["auto", "tectonic", "pdflatex", "xelatex", "latexmk", "html"].map((v) =>
            `<option value="${v}"${v === r.engine ? " selected" : ""}>${v}</option>`).join("")}</select></div>
        <div class="field" style="grid-column:span 8"><label>Overleaf git URL</label>
          <input type="text" id="r-overleaf" value="${esc(r.overleaf_git_url || "")}" placeholder="https://git.overleaf.com/&lt;project-id&gt;"></div>
        <div class="field" style="grid-column:span 4"><label>Use an AI model at all</label>
          <label class="switch"><input type="checkbox" id="l-enabled"${l.enabled ? " checked" : ""}><span class="track"></span>
            <span class="muted">${status.llm.available ? "configured" : "not configured"}</span></label>
          <div class="help">Off = deterministic ranker and template letter</div></div>
        <div class="field" style="grid-column:span 4"><label>Effort</label>
          <select id="l-effort">${["low", "medium", "high", "xhigh", "max"].map((v) =>
            `<option value="${v}"${v === l.effort ? " selected" : ""}>${v}</option>`).join("")}</select></div>
        <div class="field" style="grid-column:span 4"><label>Spend so far</label>
          <input type="text" value="$${(status.llm.usage?.total?.cost_usd ?? 0).toFixed(2)} over ${status.llm.usage?.total?.calls ?? 0} calls" disabled></div>
      </div>
    </div>

    <div class="card"><h3>AI model</h3>
      <div class="blurb">Job Wrapper reads job descriptions, rewrites your résumé around them and
        answers awkward application questions. Pick whichever provider you already pay for — or run
        one locally for free. Keys are encrypted at rest in
        <span class="mono">~/.jobwrapper/vault.enc</span> and never leave this machine except in
        calls to the provider you chose.</div>
      <div class="form-grid">
        <div class="field" style="grid-column:span 5"><label for="ai-provider">Provider</label>
          <select id="ai-provider">${PROVIDERS.providers.map((p) =>
            `<option value="${esc(p.id)}"${p.id === PROVIDERS.current.provider ? " selected" : ""}>
               ${esc(p.label)}${p.has_key ? " ✓" : ""}</option>`).join("")}</select>
          <div class="help" id="ai-provider-note"></div></div>
        <div class="field" style="grid-column:span 7"><label for="ai-model">Model</label>
          <div class="row" style="display:flex;gap:8px">
            <select id="ai-model" style="flex:1"><option>loading…</option></select>
            <button class="btn" id="ai-refresh" title="Ask the provider what it can run">↻</button>
          </div>
          <div class="help">Not listed? Type an exact model id below.</div></div>
        <div class="field" style="grid-column:span 7" id="ai-key-field">
          <label for="ai-key">API key</label>
          <input type="password" id="ai-key" placeholder="paste a key to replace the saved one">
          <div class="help" id="ai-key-help"></div></div>
        <div class="field" style="grid-column:span 5"><label for="ai-model-custom">Custom model id</label>
          <input type="text" id="ai-model-custom" placeholder="optional override"></div>
      </div>
      <div class="toolbar" style="margin-top:12px">
        <button class="btn primary" id="ai-save">Save</button>
        <button class="btn" id="ai-test">Test it</button>
        <button class="btn danger" id="ai-clear">Remove key</button>
        <span class="muted" id="ai-status">${SECRETS.current.usable
          ? `<span class="pill good">ready</span> ${esc(SECRETS.current.label)} · ${esc(SECRETS.current.model)}`
          : `<span class="pill warn">not configured</span> running on the deterministic fallbacks`}</span>
      </div>
    </div>

    <div class="card"><h3>Sources</h3>
      <div class="blurb">Paste a company careers URL and the tool works out which ATS it uses.</div>
      <div class="toolbar">
        <input type="text" id="src-url" style="flex:1;min-width:260px" placeholder="https://example.com/careers">
        <button class="btn" id="btn-detect">Detect &amp; add</button>
      </div>
      <table><thead><tr><th>ID</th><th>Kind</th><th style="width:90px">Enabled</th></tr></thead><tbody>
        ${config.sources.map((src, i) => `<tr><td class="mono">${esc(src.id)}</td><td class="muted">${esc(src.kind)}</td>
          <td><label class="switch"><input type="checkbox" data-src="${i}"${src.enabled ? " checked" : ""}><span class="track"></span></label></td></tr>`).join("")}
      </tbody></table>
    </div>

    <div class="card"><h3>Browser extension</h3>
      <div class="blurb">Load <span class="mono">extension/</span> as an unpacked extension, then paste this token into its options page.</div>
      <div class="toolbar"><input type="text" class="mono" readonly value="${esc(status.extension_token)}" style="flex:1">
        <button class="btn" id="btn-copy-token">Copy</button></div>
    </div>

    <div class="toolbar"><button class="btn primary" id="btn-save-config">Save settings</button></div>`;
  }

  return { autopilot, dashboard, jobs, applications, answers, resume, settings, statusPill, scoreClass, when };
})();
