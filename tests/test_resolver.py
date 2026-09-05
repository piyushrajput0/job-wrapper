"""The resolution cascade - the component whose mistakes reach a recruiter."""

import pytest

from jobwrapper.autofill import Catalog, FieldResolver, ResolveContext, ValueProvider
from jobwrapper.autofill.catalog import match_option
from jobwrapper.models.application import FieldDescriptor as FD


@pytest.fixture
def resolver(profile, job):
    context = ResolveContext(job=job, company="Vector Labs", ats="greenhouse",
                             resume_path="/tmp/resume.pdf")
    return FieldResolver(profile, context)


def resolve(resolver, **kwargs):
    return resolver.resolve_field(FD(**kwargs))


def test_ats_map_beats_everything(resolver):
    result = resolve(resolver, name="job_application[first_name]", label="Legal first name")
    assert result.value == "Alex" and result.method == "ats_map"


def test_label_only_resolution(resolver):
    assert resolve(resolver, name="q1", label="Email Address", input_type="email").value \
        == "alex.rivera@example.com"


def test_minor_is_not_the_major(resolver):
    assert resolve(resolver, name="q", label="What was your minor field of study?").value \
        == "Applied Mathematics"
    assert resolve(resolver, name="q", label="Major / Field of study").value == "Computer Science"


def test_managers_name_is_not_the_company(resolver):
    assert resolve(resolver, name="q", label="Manager's name at your current company").value \
        == "Dana Cole"


def test_sponsorship_pair_is_consistent(resolver):
    authorized = resolve(resolver, name="q", label="Are you legally authorized to work in the United States?",
                         input_type="radio", options=["Yes", "No"])
    sponsorship = resolve(resolver, name="q", label="Will you now or in the future require sponsorship?",
                          input_type="radio", options=["Yes", "No"])
    assert authorized.value == "Yes" and sponsorship.value == "No"


def test_degree_maps_onto_offered_options(resolver):
    result = resolve(resolver, name="q", label="Highest level of education completed",
                     input_type="select", options=["High School", "Bachelor's Degree", "Master's Degree"])
    assert result.value == "Bachelor's Degree"


def test_years_of_experience_with_a_named_skill(resolver):
    result = resolve(resolver, name="q", label="How many years of experience do you have with Python?",
                     options=["0-1", "2-3", "4-6", "7+"])
    assert result.value == "4-6"      # six years lands in the 4-6 bucket


def test_years_question_for_an_unknown_skill_is_not_guessed(resolver):
    result = resolve(resolver, name="q", label="How many years of experience do you have with COBOL?")
    assert not result.value


def test_eeo_defaults_to_declining(resolver):
    result = resolve(resolver, name="q", label="Gender", input_type="select",
                     options=["Male", "Female", "Decline To Self Identify"])
    assert result.value == "Decline To Self Identify"


def test_eeo_is_shared_when_the_user_opts_in(profile, job):
    profile.eeo.share_eeo = True
    profile.eeo.gender = "Female"
    resolver = FieldResolver(profile, ResolveContext(job=job, ats="generic"))
    result = resolver.resolve_field(FD(name="q", label="Gender", input_type="select",
                                       options=["Male", "Female", "Decline To Self Identify"]))
    assert result.value == "Female"


@pytest.mark.parametrize("label", [
    "Have you ever been convicted of a felony?",
    "Please enter your Social Security Number",
    "Complete the reCAPTCHA to continue",
    "Enter the verification code we sent you",
])
def test_dangerous_questions_are_escalated(resolver, label):
    result = resolve(resolver, name="q", label=label, required=True)
    assert result.blocked and not result.value


def test_salary_history_is_declined_by_default(resolver):
    assert resolve(resolver, name="q", label="Current salary").value == "Prefer not to disclose"


def test_marketing_opt_in_defaults_to_no(resolver):
    assert resolve(resolver, name="q", label="Send me marketing emails", input_type="checkbox").value == "No"


def test_resume_upload_is_an_upload_action(resolver):
    result = resolve(resolver, name="resume", label="Resume/CV", input_type="file")
    assert result.action == "upload" and result.value == "/tmp/resume.pdf"


def test_whole_form_plan_shape(resolver):
    fields = [
        FD(name="job_application[first_name]", label="First Name", required=True),
        FD(name="email", label="Email", input_type="email", required=True),
        FD(name="q", label="Have you ever been convicted of a crime?", required=True),
        FD(name="q2", label="What is your favourite bug?", input_type="textarea", required=True),
    ]
    plan = resolver.resolve_form(fields, url="https://example.com")
    assert plan.resolved_count == 2
    assert plan.blocking and not plan.is_submittable()
    assert any(d.label.startswith("What is your favourite") for d in plan.unresolved)


def test_match_option_declines_gracefully():
    assert match_option("Decline To Self Identify",
                        ["Male", "Female", "I do not wish to disclose"]) == "I do not wish to disclose"


def test_value_provider_covers_every_catalog_key(profile):
    """Every key in the catalog must be computable without raising."""
    catalog = Catalog()
    provider = ValueProvider(profile, ResolveContext(company="Acme"))
    for key in catalog.by_key:
        provider.value_for(key)  # must not raise


def test_placeholder_options_never_win(resolver):
    """A blank <option> is a substring of every value - it must not swallow the match."""
    from jobwrapper.autofill.catalog import match_option

    assert match_option("Bachelor of Science", ["", "Bachelor's Degree", "Master's Degree"]) \
        == "Bachelor's Degree"
    assert match_option("Yes", ["Select...", "Yes", "No"]) == "Yes"
    result = resolver.resolve_field(FD(
        name="q", label="Highest level of education completed", input_type="select",
        options=["", "Bachelor's Degree", "Master's Degree"]))
    assert result.value == "Bachelor's Degree"
