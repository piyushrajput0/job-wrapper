import os
import tempfile
from pathlib import Path

import pytest

# every test runs against a throwaway data root
_TMP = tempfile.mkdtemp(prefix="jobwrapper-tests-")
os.environ["JOBWRAPPER_HOME"] = _TMP
os.environ["JOBWRAPPER_NO_LLM"] = "1"
os.environ["JOBWRAPPER_VAULT_PASSPHRASE"] = "test-passphrase"

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def home() -> Path:
    return Path(_TMP)


@pytest.fixture
def profile():
    from jobwrapper.models import Profile
    from jobwrapper.models.profile import Education, Experience, Language, Skill

    p = Profile()
    p.identity.legal_first_name, p.identity.legal_last_name = "Alex", "Rivera"
    p.contact.email, p.contact.phone = "alex.rivera@example.com", "4155550142"
    p.address.line1, p.address.city = "12 Elm Street", "San Francisco"
    p.address.state, p.address.state_code = "California", "CA"
    p.address.postal_code, p.address.country = "94110", "United States"
    p.links.linkedin = "https://linkedin.com/in/alexrivera"
    p.links.github = "https://github.com/alexrivera"
    p.education.append(Education(
        institution="University of California, Berkeley", degree_level="Bachelor's",
        degree_name="Bachelor of Science", field_of_study="Computer Science",
        minor="Applied Mathematics", gpa="3.7", start_date="2015-08", end_date="2019-05"))
    p.experience.append(Experience(
        company="Northwind Data", title="Senior Software Engineer", start_date="2022-01",
        currently_employed=True, supervisor_name="Dana Cole",
        technologies=["Go", "Kubernetes", "Python", "Kafka"],
        bullets=["Built a multi-region ingestion service in Go handling 40k events per second."]))
    p.skills = [Skill(name="Python", years=6, level="expert"), Skill(name="Go", years=4)]
    p.languages = [Language(name="English", proficiency="Native")]
    p.preferences.compensation.desired_base_min = 180000
    p.preferences.compensation.desired_base_max = 215000
    p.years_of_experience = 6
    return p


@pytest.fixture
def master():
    from jobwrapper.resume.importer import import_master_resume

    return import_master_resume(FIXTURES / "sample_master.tex", use_llm=False)


@pytest.fixture
def job():
    from jobwrapper.models import Job

    return Job(
        source="greenhouse", company="Vector Labs", title="Senior Backend Engineer",
        location="Remote (US)", ats="greenhouse",
        url="https://boards.greenhouse.io/vectorlabs/jobs/1",
        description=("We need a Senior Backend Engineer. You will design distributed systems in "
                     "Go and Python, own Kubernetes infrastructure, and scale Kafka pipelines. "
                     "Requirements: 5+ years backend, strong Go, Kubernetes, Terraform, "
                     "PostgreSQL. Nice to have: Rust. You will mentor engineers."))


@pytest.fixture
def store():
    from jobwrapper.store import Store

    s = Store(Path(_TMP) / "test.db")
    yield s
    s.close()
