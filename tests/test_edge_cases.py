"""Boundaries found by probing rather than by reading: damaged files, odd numbers, hostile input."""

import json

import pytest
from fastapi.testclient import TestClient

from jobwrapper import paths
from jobwrapper.config import Config
from jobwrapper.models import Job, Profile
from jobwrapper.models.resume import (
    MasterResume,
    ResumeBullet,
    ResumeExperience,
    TailoringPlan,
)
from jobwrapper.pipeline.normalize import iso_date, parse_salary
from jobwrapper.resume.tailor import Tailor, TailorOptions
from jobwrapper.server.app import create_app


# --------------------------------------------------------------------------- dates and money
@pytest.mark.parametrize("value,expected_prefix", [
    ("2025", "2025-01-01"),
    ("2019", "2019-01-01"),
    ("March 2025", "2025-03-01"),
    ("Mar 2025", "2025-03-01"),
    ("2025-03", "2025-03-01"),
])
def test_a_bare_year_is_a_year_not_an_epoch(value, expected_prefix):
    """Reading "2025" as epoch seconds dated postings to 1970 and made them all look stale."""
    assert iso_date(value).startswith(expected_prefix)


@pytest.mark.parametrize("value", ["12345", "not a date", "Present", ""])
def test_undatable_values_yield_nothing(value):
    assert iso_date(value) == ""


def test_real_epoch_timestamps_still_work():
    assert iso_date(1719878400).startswith("2024-07")


@pytest.mark.parametrize("text,low,high,currency", [
    ("12-18 LPA", 1_200_000, 1_800_000, "INR"),
    ("15 to 25 lakhs per annum", 1_500_000, 2_500_000, "INR"),
    ("1.2 - 1.8 crore", 12_000_000, 18_000_000, "INR"),
    ("₹12,00,000 - ₹18,00,000", 1_200_000, 1_800_000, "INR"),
    ("$150,000 - $180,000", 150_000, 180_000, "USD"),
    ("€80.000 - €95.000", 80_000, 95_000, "EUR"),
])
def test_salary_formats_including_indian_conventions(text, low, high, currency):
    """A lakh read as a plain number is wrong by a factor of a hundred."""
    salary = parse_salary(text)
    assert (salary.min, salary.max, salary.currency) == (low, high, currency)


def test_a_year_range_is_not_a_salary():
    assert parse_salary("Founded 1999 - 2001, offices worldwide").min is None


# --------------------------------------------------------------------------- damaged files
@pytest.mark.parametrize("content", ["{not json", '{"identity": "not an object"}', "", "null"])
def test_a_damaged_profile_does_not_stop_the_app(tmp_path, content):
    path = tmp_path / "profile.json"
    path.write_text(content)
    profile = Profile.load(path)
    assert isinstance(profile, Profile)
    assert list(tmp_path.glob("profile.json.corrupt-*")), "the damaged file is kept, not deleted"


@pytest.mark.parametrize("content", ["this: is: not: valid: [", "search: 42"])
def test_a_damaged_config_falls_back_to_defaults(tmp_path, content, monkeypatch):
    monkeypatch.setenv("JOBWRAPPER_HOME", str(tmp_path))
    paths.ensure_layout()
    (tmp_path / "config.yaml").write_text(content)
    config = Config.load(tmp_path / "config.yaml")
    assert isinstance(config, Config)
    assert config.apply.autonomy == "review"


def test_a_damaged_master_resume_falls_back(tmp_path):
    path = tmp_path / "master_resume.json"
    path.write_text("")
    assert MasterResume.load(path).experience == []


def test_saves_are_atomic(tmp_path):
    """A crash mid-write must not truncate the previous file."""
    path = tmp_path / "profile.json"
    Profile().save(path)
    assert json.loads(path.read_text())
    assert not list(tmp_path.glob("*.tmp")), "the temporary file is renamed, not left behind"


# --------------------------------------------------------------------------- hostile requests
@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_artifact_rejects_a_path_with_a_null_byte(client):
    assert client.get("/api/artifact", params={"path": "/tmp/x\x00.pdf"}).status_code == 400


def test_artifact_refuses_to_leave_the_data_directory(client):
    for path in ("../../etc/passwd", "/etc/hosts", "~/.ssh/id_rsa"):
        assert client.get("/api/artifact", params={"path": path}).status_code in {400, 403, 404}


@pytest.mark.parametrize("limit", [-5, 0, 99999])
def test_list_limits_are_clamped(client, limit):
    assert client.get("/api/jobs", params={"limit": limit}).status_code == 422


# --------------------------------------------------------------------------- misbehaving plans
def _master():
    return MasterResume(
        skill_groups={"Languages": ["Python"]},
        experience=[ResumeExperience(company="Acme", title="Eng",
                                     bullets=[ResumeBullet(text="Built a Go service.")])])


def test_a_skill_group_the_master_never_had_is_dropped():
    """The firewall checks skills; an invented *group heading* would otherwise survive empty."""
    tailor = Tailor(Config(), _master(), Profile())
    result = tailor._apply_plan(
        TailoringPlan(skill_groups={"Invented": ["Rust"], "Languages": ["Python"]}),
        [], TailorOptions())
    assert list(result.skill_groups) == ["Languages"]


@pytest.mark.parametrize("plan", [
    TailoringPlan(experience_order=[5, 9, -3]),
    TailoringPlan(dropped_bullets=[[-1, -1], [0]]),
    TailoringPlan(skill_groups={}),
])
def test_out_of_range_indices_from_a_model_do_not_crash(plan):
    tailor = Tailor(Config(), _master(), Profile())
    assert tailor._apply_plan(plan, [], TailorOptions()).experience


def test_trimming_more_bullets_than_exist_keeps_the_resume_usable():
    trimmed = Tailor.trim(_master(), drop=99)
    assert sum(len(e.bullets) for e in trimmed.experience) >= 1


# --------------------------------------------------------------------------- odd content
def test_unicode_survives_the_store(store):
    job = Job(source="lever", company="Größe & Co 🚀", title="Ingénieur")
    store.jobs.upsert(job)
    assert store.jobs.get(job.id).company == "Größe & Co 🚀"


def test_latex_rendering_escapes_what_would_break_a_compile():
    from jobwrapper.resume.render import render_latex

    resume = MasterResume(name="José Müller", summary="Cut cost 100% & saved $5k",
                          skill_groups={"Languages": ["C++", "C#", "R&D"]})
    tex = render_latex(resume, Profile())
    for fragment in ["100\\%", "\\$5k", "C\\#", "R\\&D"]:
        assert fragment in tex
