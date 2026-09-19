"""The search summary has to add up, and tailoring has to surface what the résumé earns."""
from __future__ import annotations

from jobwrapper.config import Config
from jobwrapper.models import Job, Profile
from jobwrapper.models.resume import MasterResume, ResumeBullet, ResumeExperience, ResumeProject
from jobwrapper.resume.tailor import Tailor


def _master() -> MasterResume:
    return MasterResume(
        name="Test Person", email="t@example.com",
        skill_groups={"Languages": ["Python", "Go"], "Tools": ["Docker"]},
        experience=[ResumeExperience(
            title="Backend Engineer", company="Acme", start_date="2021-01",
            bullets=[ResumeBullet(text="Built ingestion on Kafka, writing the SQL that fed it."),
                     ResumeBullet(text="Ran deploys on Kubernetes with Terraform.")])],
        projects=[ResumeProject(name="Ledger", description="A FastAPI service backed by PostgreSQL.")])


def _job() -> Job:
    return Job(id="j1", source="t", title="Backend Engineer", company="Beta",
               url="https://example.com/j1",
               description="Kafka, SQL, Kubernetes, Terraform, FastAPI, PostgreSQL, Python.")


def _tailored():
    config = Config()
    config.llm.enabled = False
    return Tailor(config, _master(), Profile(), llm=None).tailor(_job())


def test_a_skill_the_resume_demonstrates_can_reach_the_skills_list():
    """Kafka is described in a bullet but never listed - the ATS cannot see it there."""
    result = _tailored()
    listed = {s.lower() for group in result.resume.skill_groups.values() for s in group}
    assert "kafka" in listed
    assert "Kafka" in result.plan.skills_surfaced


def test_a_skill_the_resume_cannot_support_is_never_added():
    config = Config()
    config.llm.enabled = False
    job = _job()
    job.description += " Also requires COBOL, Fortran and Haskell."
    result = Tailor(config, _master(), Profile(), llm=None).tailor(job)
    listed = {s.lower() for group in result.resume.skill_groups.values() for s in group}
    assert not ({"cobol", "fortran", "haskell"} & listed)
    assert not result.violations


def test_tailoring_stays_small():
    """"A little bit of change" - the master's own skills all survive, nothing is rewritten away."""
    result = _tailored()
    before = {s.lower() for group in _master().skill_groups.values() for s in group}
    after = {s.lower() for group in result.resume.skill_groups.values() for s in group}
    assert before <= after
    assert len(after - before) <= Config().resume.max_new_keywords


def test_project_technologies_come_from_that_projects_own_text():
    project = _tailored().resume.projects[0]
    listed = {t.lower() for t in project.technologies}
    assert "fastapi" in listed and "postgresql" in listed
    assert "kafka" not in listed          # Kafka is in a role, not in this project


def test_search_report_numbers_reconcile():
    """806 deduped minus what was rejected has to equal what was stored, or the count lies."""
    from jobwrapper.pipeline.search import SearchReport

    report = SearchReport(fetched=846, after_dedupe=806, new=33, updated=0,
                          disqualified=14, off_target=759)
    assert report.new + report.updated + report.disqualified + report.off_target == report.after_dedupe
    assert "off_target" in report.as_dict()
