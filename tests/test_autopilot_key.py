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
