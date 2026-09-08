"""Filling the profile from a résumé - the step that removes most of the intake typing."""

import pytest

from jobwrapper.models import Profile
from jobwrapper.models.resume import (
    MasterResume,
    ResumeBullet,
    ResumeEducation,
    ResumeExperience,
)
from jobwrapper.resume.to_profile import (
    degree_level,
    parse_location,
    profile_from_resume,
    split_name,
    split_phone,
)


@pytest.fixture
def master():
    return MasterResume(
        name="Alex J. Rivera",
        email="alex@example.com",
        phone="+1 415 555 0142",
        location="San Francisco, CA",
        summary="Backend engineer.",
        links={"linkedin": "https://linkedin.com/in/alex"},
        skill_groups={"Languages": ["Python", "Go"]},
        experience=[ResumeExperience(
            company="Northwind", title="Senior Engineer", location="San Francisco, CA",
            start_date="2022-01", technologies=["Go"],
            bullets=[ResumeBullet(text="Built a Go service handling 40k events per second.")])],
        education=[ResumeEducation(
            institution="UC Berkeley", degree="Bachelor of Science in Computer Science",
            field_of_study="Computer Science", minor="Applied Mathematics", gpa="3.7",
            start_date="2015-08", end_date="2019-05")],
    )


@pytest.mark.parametrize("full,expected", [
    ("Alex Rivera", ("Alex", "", "Rivera", "")),
    ("Alex J. Rivera", ("Alex", "J.", "Rivera", "")),
    ("Alex Rivera Jr.", ("Alex", "", "Rivera", "Jr.")),
    ("Priya Sharma", ("Priya", "", "Sharma", "")),
    ("Cher", ("Cher", "", "", "")),
    ("", ("", "", "", "")),
])
def test_split_name(full, expected):
    assert split_name(full) == expected


@pytest.mark.parametrize("raw,expected", [
    ("+44 7700 900123", ("+44", "7700900123")),
    ("+91 98765 43210", ("+91", "9876543210")),
    ("(415) 555-0142", ("+1", "4155550142")),
    ("+1 415 555 0142", ("+1", "4155550142")),
    ("14155550142", ("+1", "4155550142")),
])
def test_split_phone(raw, expected):
    assert split_phone(raw) == expected


@pytest.mark.parametrize("raw,city,country", [
    ("San Francisco, CA", "San Francisco", "United States"),
    ("London, United Kingdom", "London", "United Kingdom"),
    ("Bengaluru, India", "Bengaluru", "India"),
    ("Berlin", "Berlin", ""),
    ("", "", ""),
])
def test_parse_location(raw, city, country):
    parsed = parse_location(raw)
    assert parsed["city"] == city
    assert parsed["country"] == country


@pytest.mark.parametrize("degree,level", [
    ("Bachelor of Science in Computer Science", "Bachelor's"),
    ("B.Tech in Computer Science", "Bachelor's"),
    ("MEng Computing", "Master's"),
    ("M.Tech", "Master's"),
    ("PhD in Physics", "PhD"),
    ("MBA", "MBA"),
    ("Some Certificate", "Certificate"),
    ("", ""),
])
def test_degree_level(degree, level):
    assert degree_level(degree) == level


def test_a_resume_fills_an_empty_profile(master):
    result = profile_from_resume(master, Profile())
    profile = result.profile

    assert profile.identity.legal_first_name == "Alex"
    assert profile.identity.legal_middle_name == "J."
    assert profile.identity.legal_last_name == "Rivera"
    assert profile.contact.email == "alex@example.com"
    assert (profile.contact.phone_country_code, profile.contact.phone) == ("+1", "4155550142")
    assert profile.address.city == "San Francisco"
    assert profile.address.state_code == "CA"
    assert profile.links.linkedin.endswith("/alex")
    assert [e.company for e in profile.experience] == ["Northwind"]
    assert profile.experience[0].currently_employed is True      # no end date means current
    assert profile.education[0].degree_level == "Bachelor's"
    assert profile.education[0].minor == "Applied Mathematics"
    assert profile.current_company == "Northwind"
    assert not profile.missing_required()


def test_it_does_not_overwrite_what_you_typed(master):
    existing = Profile()
    existing.identity.legal_first_name = "Alexandra"
    existing.contact.email = "me@personal.example"

    result = profile_from_resume(master, existing)

    assert result.profile.identity.legal_first_name == "Alexandra"
    assert result.profile.contact.email == "me@personal.example"
    assert {c.label for c in result.skipped} >= {"First name", "Email"}


def test_overwrite_is_available_when_asked_for(master):
    existing = Profile()
    existing.identity.legal_first_name = "Alexandra"
    result = profile_from_resume(master, existing, overwrite=True)
    assert result.profile.identity.legal_first_name == "Alex"


def test_a_default_is_not_treated_as_your_answer():
    """The profile ships with country "United States"; a UK résumé must still win."""
    master = MasterResume(name="Priya Sharma", email="p@example.com",
                          phone="+44 7700 900123", location="London, United Kingdom")
    result = profile_from_resume(master, Profile())
    assert result.profile.address.country == "United Kingdom"
    assert result.profile.address.country_code == "GB"
    assert result.profile.contact.phone_country_code == "+44"
    assert not result.skipped


def test_skill_years_come_from_the_history(master):
    result = profile_from_resume(master, Profile())
    by_name = {s.name: s for s in result.profile.skills}
    assert by_name["Go"].years > 0, "Go appears in a dated role, so it has years behind it"
    assert by_name["Python"].years == 0, "Python is listed but never dated"
    assert by_name["Python"].level == "intermediate", "an undated skill is unknown, not junior"


def test_preview_does_not_mutate_the_stored_profile(master):
    existing = Profile()
    result = profile_from_resume(master, existing)
    assert result.profile is not existing
    assert existing.identity.legal_first_name == ""      # the original is untouched
    assert result.profile.identity.legal_first_name == "Alex"


def test_endpoint_previews_then_applies():

    from fastapi.testclient import TestClient

    from jobwrapper.server.app import create_app, get_state

    state = get_state()
    state.master.name = "Alex Rivera"
    state.master.email = "alex@example.com"
    state.master.save(state.layout["master_resume"])
    client = TestClient(create_app())
    preview = client.post("/api/profile/from-resume", json={}).json()
    assert "changes" in preview and preview["applied"] is False
    applied = client.post("/api/profile/from-resume", json={"apply": True}).json()
    assert applied["applied"] is True
