"""The API key the user pastes in, and the one-button run that uses it."""

import pytest
from fastapi.testclient import TestClient

from jobwrapper.config import Config
from jobwrapper.llm import LLMClient
from jobwrapper.models import Application, Job
from jobwrapper.models.resume import MasterResume
from jobwrapper.pipeline import Autopilot
from jobwrapper.server.app import create_app
from jobwrapper.vault import Vault


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_api_key_is_stored_encrypted_and_read_back(home):
    vault = Vault(home / "key-test.enc", interactive=False)
    vault.set_api_key("anthropic", "sk-ant-secret-value")
    assert Vault(home / "key-test.enc", interactive=False).get_api_key("anthropic") \
        == "sk-ant-secret-value"
    assert b"sk-ant-secret-value" not in (home / "key-test.enc").read_bytes()


def test_vault_never_prompts_in_non_interactive_mode(home, monkeypatch):
    """The server must not block on getpass - it provisions its own passphrase."""
    monkeypatch.delenv("JOBWRAPPER_VAULT_PASSPHRASE", raising=False)

    def explode(*args, **kwargs):
        raise AssertionError("getpass was called in non-interactive mode")

    monkeypatch.setattr("getpass.getpass", explode)
    vault = Vault(home / "auto-key.enc", interactive=False)
    vault.set_api_key("anthropic", "sk-ant-auto")
    assert vault.get_api_key("anthropic") == "sk-ant-auto"


def test_llm_client_prefers_the_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    assert LLMClient().api_key() == "sk-ant-from-env"


def test_secrets_endpoint_never_returns_the_key(client):
    client.put("/api/secrets", json={"anthropic_api_key": "sk-ant-abcdefgh1234"})
    payload = client.get("/api/secrets").json()["anthropic"]
    assert payload["set"] is True
    assert payload["hint"] == "…1234"
    assert "sk-ant-abcdefgh1234" not in str(payload)


def test_secrets_endpoint_rejects_a_non_key(client):
    assert client.put("/api/secrets", json={"anthropic_api_key": "hunter2"}).status_code == 422


def test_secrets_can_be_cleared(client):
    client.put("/api/secrets", json={"anthropic_api_key": ""})
    assert client.get("/api/secrets").json()["anthropic"]["source"] in {"none", "environment"}


def test_autopilot_shortlist_skips_what_was_already_applied_to(store, profile):
    config = Config()
    config.match.min_score_to_apply = 50
    fresh = Job(source="lever", company="Fresh Co", title="Backend Engineer", match_score=80)
    done = Job(source="lever", company="Done Co", title="Backend Engineer", match_score=90)
    store.jobs.upsert(fresh)
    store.jobs.upsert(done)
    store.jobs.set_score(fresh)
    store.jobs.set_score(done)
    store.applications.save(Application(job_id=done.id, company="Done Co", title="Backend Engineer",
                                        status="submitted"))

    pilot = Autopilot(config, store, profile, MasterResume())
    picked = pilot.shortlist(limit=10)
    companies = {j.company for j in picked}
    assert "Fresh Co" in companies
    assert "Done Co" not in companies


def test_autopilot_reports_when_there_is_nothing_to_do(store, profile):
    config = Config()
    config.match.min_score_to_apply = 99
    pilot = Autopilot(config, store, profile, MasterResume())
    report = pilot.run(limit=3, do_search=False, do_overleaf=False)
    assert report.shortlisted == 0
    assert report.events[-1]["stage"] == "done"


def test_autopilot_emits_progress_to_a_callback(store, profile):
    seen = []
    config = Config()
    config.match.min_score_to_apply = 99
    Autopilot(config, store, profile, MasterResume(),
              on_progress=seen.append).run(limit=1, do_search=False, do_overleaf=False)
    assert [e.stage for e in seen][-1] == "done"
    assert all(hasattr(e, "as_dict") for e in seen)


def test_daily_cap_counts_attempts_not_just_submissions(store, profile):
    """At autonomy `review` nothing is ever submitted, so a submission-only cap capped nothing."""
    from jobwrapper.apply import ApplicationRunner
    from jobwrapper.models import Job

    config = Config()
    config.apply.daily_cap = 2
    config.match.min_score_to_apply = 10
    for i in range(2):
        store.applications.save(Application(job_id=f"cap{i}", company=f"Co{i}", title="Eng",
                                            status="ready_for_review"))
    runner = ApplicationRunner(config, store, profile, MasterResume())
    job = Job(source="lever", company="Next Co", title="Engineer",
              url="https://example.com/apply", match_score=90)
    assert "daily cap" in (runner.guardrail_block(job) or "")


def test_closed_postings_are_recognised():
    """A filled posting is a skip, not a failure - and the job should stop coming back."""
    from jobwrapper.apply.ats import adapter_for

    adapter = adapter_for(name="generic")
    markers = adapter.catalog.ats("generic")["closed_text"]
    assert "no longer accepting applications" in markers

    class FakeSession:
        def page_text(self, limit=6000):
            return "Thanks for your interest. This job is no longer available."

    assert adapter.is_closed(FakeSession()) == "this job is no longer available"


def test_open_posting_is_not_flagged_as_closed():
    from jobwrapper.apply.ats import adapter_for

    class FakeSession:
        def page_text(self, limit=6000):
            return "Senior Backend Engineer. Apply now. We are hiring across the team."

    assert adapter_for(name="generic").is_closed(FakeSession()) is None


def test_review_replays_the_stored_plan_without_the_model(store, profile, monkeypatch):
    """Re-filling a reviewed application must be deterministic: same values, no model call."""
    from jobwrapper.apply import ApplicationRunner
    from jobwrapper.models.application import FilledField, FillPlan

    plan = FillPlan(url="https://example.com/apply", fields=[
        FilledField(selector="#fn", field_key="first_name", value="Alex", question="First Name"),
        FilledField(selector="#em", field_key="email", value="a@example.com", question="Email"),
    ])
    application = Application(job_id="j1", company="Acme", title="Engineer",
                              url="https://example.com/apply", status="ready_for_review",
                              plan=plan)
    store.applications.save(application)

    calls: list[str] = []

    class FakeSession:
        page = None

        def goto(self, url, wait="domcontentloaded"):
            calls.append(f"goto:{url}")
            return True

        def dismiss_cookie_banner(self):
            return False

        def apply_field(self, item, frame=""):
            calls.append(f"fill:{item.field_key}={item.value}")
            return True, ""

        def extract_fields(self):
            return []

    class FakeAdapter:
        name = "generic"

        def open_application(self, session, url):
            return True

        def before_fill(self, session):
            pass

        def after_fill(self, session):
            pass

    runner = ApplicationRunner(Config(), store, profile, MasterResume())
    monkeypatch.setattr("jobwrapper.apply.runner.adapter_for", lambda **kw: FakeAdapter())
    filled, failed = runner.replay(application, FakeSession())

    assert (filled, failed) == (2, 0)
    assert calls == ["goto:https://example.com/apply",
                     "fill:first_name=Alex", "fill:email=a@example.com"]


def test_review_of_an_application_with_no_plan_is_a_no_op(store, profile):
    from jobwrapper.apply import ApplicationRunner

    runner = ApplicationRunner(Config(), store, profile, MasterResume())
    empty = Application(job_id="j2", company="Acme", title="Engineer", status="planned")
    assert runner.replay(empty, object()) == (0, 0)


def test_artifact_filenames_lead_with_the_candidate(profile):
    """Recruiters see the filename; "Alex-Rivera-..." beats "VectorLabs-...".""" 
    from jobwrapper.apply.runner import artifact_basename
    from jobwrapper.models import Job

    base = artifact_basename(profile, Job(company="Vector Labs, Inc.",
                                          title="Senior Backend Engineer (Platform)"), "20260101")
    assert base.startswith("Alex-Rivera-")
    assert "Senior-Backend-Engineer" in base and "Vector-Labs" in base
    assert " " not in base and "," not in base


def test_cover_letter_renders_as_a_document(profile):
    """ATS upload fields reject .txt, so the letter has to be a real document."""
    from jobwrapper.apply.runner import _cover_letter_html
    from jobwrapper.models import Job

    html = _cover_letter_html("First paragraph.\n\nSecond paragraph.", profile,
                              Job(company="Vector Labs", title="Senior Backend Engineer"))
    assert "<p>First paragraph.</p>" in html and "<p>Second paragraph.</p>" in html
    assert "Alex Rivera" in html and "Vector Labs" in html
    assert "alex.rivera@example.com" in html


def test_status_reports_whether_a_browser_is_available(client):
    """A packaged app ships without a browser; the UI has to know so it can offer to fetch one."""
    payload = client.get("/api/status").json()
    assert "browser" in payload and isinstance(payload["browser"]["ready"], bool)


def test_desktop_picks_a_free_port_and_a_landing_route():
    from jobwrapper.desktop import free_port, landing_route

    first, second = free_port(), free_port()
    assert 1024 < first < 65536 and 1024 < second < 65536
    assert landing_route() in {"#/profile", "#/autopilot"}
