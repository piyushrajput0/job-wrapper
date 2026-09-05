from jobwrapper.models import Application, Job
from jobwrapper.vault import Vault, generate_password


def test_job_upsert_is_idempotent(store):
    job = Job(source="lever", company="Acme", title="Backend Engineer", location="Remote")
    assert store.jobs.upsert(job) is True
    assert store.jobs.upsert(job) is False
    assert store.jobs.count() >= 1


def test_job_upsert_keeps_the_longer_description(store):
    thin = Job(source="remoteok", company="Beta", title="SRE", description="short")
    rich = Job(source="greenhouse", company="Beta", title="SRE", description="a much longer body")
    store.jobs.upsert(thin)
    store.jobs.upsert(rich)
    assert store.jobs.get(thin.id).description == "a much longer body"


def test_answer_bank_normalises_questions(store):
    store.answers.remember("How many years of Python experience? *", "6")
    found = store.answers.recall("how many years of python experience")
    assert found and found.answer == "6"


def test_company_scoped_answer_beats_global(store):
    store.answers.remember("How did you hear about us?", "Job board")
    store.answers.remember("How did you hear about us?", "Referral", company="Acme")
    assert store.answers.recall("How did you hear about us?", "Acme").answer == "Referral"
    assert store.answers.recall("How did you hear about us?").answer == "Job board"


def test_application_caps(store):
    for i in range(3):
        store.applications.save(Application(job_id=f"j{i}", company="Acme", title="Eng",
                                            status="submitted"))
    assert store.applications.count_for_company("acme") == 3


def test_events_are_appended(store):
    store.events.log("test", "hello", ref="x", extra=1)
    assert store.events.recent(kind="test")[0]["message"] == "hello"


def test_vault_roundtrip_and_encryption(home):
    vault = Vault(home / "vault-test.enc")
    cred, created = vault.get_or_create("acme.com", "me@example.com")
    assert created and len(cred.password) == 20
    assert Vault(home / "vault-test.enc").get("careers.acme.com").password == cred.password
    assert cred.password.encode() not in (home / "vault-test.enc").read_bytes()


def test_vault_does_not_match_lookalike_domains(home):
    vault = Vault(home / "vault-lookalike.enc")
    vault.get_or_create("acme.com", "me@example.com")
    assert vault.get("evil-acme.com") is None


def test_generated_passwords_are_strong():
    passwords = {generate_password() for _ in range(20)}
    assert len(passwords) == 20
    for password in passwords:
        assert any(c.isupper() for c in password) and any(c.isdigit() for c in password)
