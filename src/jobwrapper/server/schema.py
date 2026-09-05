"""UI schema for the profile editor.

The web form is generated from this, so adding a question to the intake is a one-line change
here rather than a new hand-written input. Field `path` values address into the Profile model.
"""

from __future__ import annotations

from typing import Any

YES_NO = ["yes", "no", "prefer_not_to_say"]

GENDER = ["Male", "Female", "Non-binary", "Decline To Self Identify"]
RACE = [
    "Hispanic or Latino", "White (Not Hispanic or Latino)",
    "Black or African American (Not Hispanic or Latino)",
    "Native Hawaiian or Other Pacific Islander (Not Hispanic or Latino)",
    "Asian (Not Hispanic or Latino)",
    "American Indian or Alaska Native (Not Hispanic or Latino)",
    "Two or More Races (Not Hispanic or Latino)", "Decline To Self Identify",
]
VETERAN = [
    "I identify as one or more of the classifications of a protected veteran",
    "I am not a protected veteran", "I don't wish to answer",
]
DISABILITY = [
    "Yes, I have a disability, or have had one in the past",
    "No, I do not have a disability and have not had one in the past",
    "I do not want to answer",
]
WORK_AUTH_STATUS = [
    "U.S. Citizen", "U.S. Permanent Resident (Green Card)", "Green Card EAD", "H-1B",
    "H-4 EAD", "L-1", "L-2 EAD", "TN", "O-1", "E-3", "F-1 OPT", "F-1 STEM OPT", "F-1 CPT",
    "J-1", "Refugee / Asylee", "Requires sponsorship", "Other",
]
DEGREE_LEVELS = ["High School", "Associate", "Bachelor's", "Master's", "MBA", "PhD",
                 "Bootcamp", "Certificate", "Other"]
CLEARANCE = ["None", "Public Trust", "Confidential", "Secret", "Top Secret", "TS/SCI",
             "TS/SCI with Polygraph"]
WORK_MODELS = ["remote", "hybrid", "onsite", "no_preference"]
PROFICIENCY = ["beginner", "intermediate", "advanced", "expert"]
LANGUAGE_LEVELS = ["Native", "Fluent", "Professional", "Conversational", "Basic"]
SOURCES = ["Company website", "LinkedIn", "Indeed", "Glassdoor", "Referral", "Recruiter",
           "Job fair", "University career centre", "Hacker News", "Job board", "Other"]


def f(path: str, label: str, kind: str = "text", **extra: Any) -> dict[str, Any]:
    return {"path": path, "label": label, "kind": kind, **extra}


SECTIONS: list[dict[str, Any]] = [
    {
        "id": "identity",
        "title": "Identity",
        "icon": "user",
        "blurb": "Your legal name is what goes on the application; the preferred name is what "
                 "recruiters call you.",
        "fields": [
            f("identity.legal_first_name", "Legal first name", required=True, col=4),
            f("identity.legal_middle_name", "Middle name", col=4),
            f("identity.legal_last_name", "Legal last name", required=True, col=4),
            f("identity.preferred_name", "Preferred name", col=4,
              help="What you go by, if it differs"),
            f("identity.previous_name", "Previous / maiden name", col=4),
            f("identity.suffix", "Suffix", col=4, help="Jr., Sr., PhD"),
            f("identity.pronouns", "Pronouns", col=6),
            f("identity.date_of_birth", "Date of birth", "date", col=6,
              help="Never auto-filled. Used only to answer 'are you over 18?'"),
        ],
    },
    {
        "id": "contact",
        "title": "Contact",
        "icon": "mail",
        "fields": [
            f("contact.email", "Email", "email", required=True, col=6),
            f("contact.alternate_email", "Alternate email", "email", col=6),
            f("contact.phone_country_code", "Country code", col=3, placeholder="+1"),
            f("contact.phone", "Phone", "tel", required=True, col=5),
            f("contact.phone_device_type", "Phone type", "select", col=4,
              options=["mobile", "home", "work"]),
            f("contact.preferred_contact_method", "Preferred contact", "select", col=6,
              options=["email", "phone", "either"]),
        ],
    },
    {
        "id": "address",
        "title": "Address",
        "icon": "map",
        "blurb": "The single most common cause of a stalled autofill is a missing address line.",
        "fields": [
            f("address.line1", "Street address", required=True, col=8),
            f("address.line2", "Apt / Suite", col=4),
            f("address.city", "City", required=True, col=4),
            f("address.state", "State / Province", col=4),
            f("address.state_code", "State code", col=4, placeholder="CA"),
            f("address.postal_code", "ZIP / Postal code", col=4),
            f("address.country", "Country", col=4),
            f("address.country_code", "Country code", col=2, placeholder="US"),
            f("address.county", "County", col=3),
            f("address.timezone", "Time zone", col=3, placeholder="America/Los_Angeles"),
        ],
    },
    {
        "id": "links",
        "title": "Links",
        "icon": "link",
        "fields": [
            f("links.linkedin", "LinkedIn", "url", col=6),
            f("links.github", "GitHub", "url", col=6),
            f("links.portfolio", "Portfolio", "url", col=6),
            f("links.website", "Personal website", "url", col=6),
            f("links.twitter", "Twitter / X", "url", col=6),
            f("links.stackoverflow", "Stack Overflow", "url", col=6),
            f("links.google_scholar", "Google Scholar", "url", col=6),
            f("links.orcid", "ORCID", "url", col=6),
            f("links.kaggle", "Kaggle", "url", col=6),
            f("links.blog", "Blog", "url", col=6),
            f("links.dribbble", "Dribbble", "url", col=6),
            f("links.behance", "Behance", "url", col=6),
            f("links.other", "Other", "url", col=6),
        ],
    },
    {
        "id": "authorization",
        "title": "Work authorisation",
        "icon": "globe",
        "blurb": "Stored per country - the same person answers a US and a UK posting differently.",
        "repeat": {
            "path": "work_authorization.by_country",
            "kind": "map",
            "key_label": "Country code",
            "key_placeholder": "US",
            "fields": [
                f("authorized_to_work", "Authorised to work here?", "select", options=YES_NO, col=6),
                f("status", "Status", "select", options=WORK_AUTH_STATUS, col=6, free=True),
                f("requires_sponsorship_now", "Requires sponsorship now?", "select",
                  options=YES_NO, col=6),
                f("requires_sponsorship_future", "Will require sponsorship in future?", "select",
                  options=YES_NO, col=6),
                f("visa_type", "Visa type", col=4),
                f("work_permit_expiry", "Permit / EAD expiry", "date", col=4),
                f("permanent_resident", "Permanent resident?", "select", options=YES_NO, col=4),
                f("notes", "Notes", "textarea", col=12),
            ],
        },
    },
    {
        "id": "education",
        "title": "Education",
        "icon": "graduation",
        "blurb": "Minor, GPA scale and expected graduation are the fields that block "
                 "applications when left blank.",
        "repeat": {
            "path": "education",
            "kind": "list",
            "title_field": "institution",
            "fields": [
                f("institution", "Institution", required=True, col=6),
                f("location", "Location", col=6),
                f("degree_level", "Degree level", "select", options=DEGREE_LEVELS, col=4),
                f("degree_name", "Degree name", col=8, placeholder="Bachelor of Science"),
                f("field_of_study", "Field of study / major", col=4),
                f("minor", "Minor", col=4),
                f("second_major", "Second major", col=4),
                f("concentration", "Concentration", col=4),
                f("gpa", "GPA", col=4),
                f("gpa_scale", "GPA scale", "select", options=["4.0", "5.0", "10.0", "100", "UK Honours"],
                  col=4, free=True),
                f("start_date", "Start (YYYY-MM)", "month", col=4),
                f("end_date", "End (YYYY-MM)", "month", col=4),
                f("expected_graduation", "Expected graduation", "month", col=4),
                f("currently_attending", "Currently attending", "bool", col=6),
                f("graduated", "Graduated", "bool", col=6),
                f("honors", "Honours", col=12),
                f("relevant_coursework", "Relevant coursework", "tags", col=12),
                f("thesis", "Thesis", col=12),
            ],
        },
    },
    {
        "id": "experience",
        "title": "Experience",
        "icon": "briefcase",
        "blurb": "Bullets here are the raw material the tailoring engine ranks and rewrites - "
                 "and the ceiling on what it may claim.",
        "repeat": {
            "path": "experience",
            "kind": "list",
            "title_field": "company",
            "fields": [
                f("company", "Company", required=True, col=6),
                f("title", "Job title", required=True, col=6),
                f("employment_type", "Employment type", "select", col=4,
                  options=["Full-time", "Part-time", "Contract", "Internship", "Temporary"]),
                f("location", "Location", col=4),
                f("work_model", "Work model", "select", options=["", *WORK_MODELS], col=4),
                f("start_date", "Start (YYYY-MM)", "month", required=True, col=4),
                f("end_date", "End (YYYY-MM)", "month", col=4),
                f("currently_employed", "I currently work here", "bool", col=4),
                f("summary", "Summary", "textarea", col=12),
                f("bullets", "Bullets", "lines", col=12,
                  help="One achievement per line. Lead with a verb, include the number."),
                f("technologies", "Technologies", "tags", col=12),
                f("reason_for_leaving", "Reason for leaving", col=6),
                f("may_contact", "May we contact them?", "select", options=YES_NO, col=6),
                f("supervisor_name", "Supervisor name", col=4),
                f("supervisor_title", "Supervisor title", col=4),
                f("supervisor_phone", "Supervisor phone", col=4),
            ],
        },
    },
    {
        "id": "projects",
        "title": "Projects",
        "icon": "code",
        "repeat": {
            "path": "projects",
            "kind": "list",
            "title_field": "name",
            "fields": [
                f("name", "Project name", required=True, col=6),
                f("role", "Your role", col=6),
                f("url", "URL", "url", col=6),
                f("start_date", "Start", "month", col=3),
                f("end_date", "End", "month", col=3),
                f("description", "Description", "textarea", col=12),
                f("bullets", "Bullets", "lines", col=12),
                f("technologies", "Technologies", "tags", col=12),
            ],
        },
    },
    {
        "id": "skills",
        "title": "Skills & languages",
        "icon": "sparkles",
        "blurb": "Years per skill lets the tool answer 'how many years of X?' without asking you.",
        "repeat": {
            "path": "skills",
            "kind": "list",
            "title_field": "name",
            "fields": [
                f("name", "Skill", required=True, col=5),
                f("years", "Years", "number", col=2, step="0.5"),
                f("level", "Level", "select", options=PROFICIENCY, col=3),
                f("last_used_year", "Last used", "number", col=2),
            ],
        },
        "extra_repeats": [
            {
                "path": "skill_groups", "kind": "list", "title": "Skill groups (for the resume)",
                "title_field": "name",
                "fields": [f("name", "Group name", col=4, placeholder="Languages"),
                           f("skills", "Skills", "tags", col=8)],
            },
            {
                "path": "languages", "kind": "list", "title": "Spoken languages",
                "title_field": "name",
                "fields": [f("name", "Language", col=6),
                           f("proficiency", "Proficiency", "select", options=LANGUAGE_LEVELS, col=6)],
            },
            {
                "path": "certifications", "kind": "list", "title": "Certifications & licences",
                "title_field": "name",
                "fields": [f("name", "Name", col=6), f("issuer", "Issuer", col=6),
                           f("credential_id", "Credential ID", col=4),
                           f("issue_date", "Issued", "month", col=4),
                           f("expiry_date", "Expires", "month", col=4),
                           f("url", "URL", "url", col=12)],
            },
        ],
    },
    {
        "id": "preferences",
        "title": "Preferences & pay",
        "icon": "target",
        "fields": [
            f("preferences.work_model", "Preferred work model", "select", options=WORK_MODELS, col=4),
            f("preferences.acceptable_work_models", "Also acceptable", "multi",
              options=WORK_MODELS, col=4),
            f("preferences.max_days_in_office", "Max days in office", "number", col=4),
            f("preferences.preferred_locations", "Preferred locations", "tags", col=12),
            f("preferences.willing_to_relocate", "Willing to relocate", "select",
              options=YES_NO, col=4),
            f("preferences.relocation_locations", "Would relocate to", "tags", col=8),
            f("preferences.needs_relocation_assistance", "Needs relocation assistance", "select",
              options=YES_NO, col=4),
            f("preferences.willing_to_travel_percent", "Willing to travel (%)", "number", col=4),
            f("preferences.earliest_start_date", "Earliest start date", col=4,
              placeholder="Immediately or YYYY-MM-DD"),
            f("preferences.notice_period_weeks", "Notice period (weeks)", "number", col=4),
            f("preferences.employment_types", "Employment types", "tags", col=4),
            f("preferences.open_to_contract", "Open to contract", "bool", col=4),
            f("preferences.compensation.desired_base_min", "Desired base min", "number", col=3),
            f("preferences.compensation.desired_base_max", "Desired base max", "number", col=3),
            f("preferences.compensation.currency", "Currency", "select", col=3,
              options=["USD", "GBP", "EUR", "INR", "CAD", "AUD"], free=True),
            f("preferences.compensation.pay_period", "Pay period", "select", col=3,
              options=["annual", "hourly", "monthly"]),
            f("preferences.compensation.hourly_rate", "Hourly rate", "number", col=3),
            f("preferences.compensation.negotiable", "Negotiable", "bool", col=3),
            f("preferences.compensation.current_salary_disclosure", "Current salary", "select",
              options=["decline", "disclose"], col=3,
              help="Salary-history questions are unlawful in many places; declining is the default"),
            f("preferences.compensation.current_salary", "Current salary", "number", col=3),
            f("preferences.compensation.equity_expectation", "Equity expectation", col=6),
            f("preferences.compensation.bonus_expectation", "Bonus expectation", col=6),
            f("preferences.shift_availability", "Shift availability", col=4),
            f("preferences.weekend_availability", "Weekend availability", "select",
              options=YES_NO, col=4),
            f("preferences.overtime_availability", "Overtime availability", "select",
              options=YES_NO, col=4),
            f("preferences.industries_preferred", "Preferred industries", "tags", col=6),
            f("preferences.industries_excluded", "Excluded industries", "tags", col=6),
        ],
    },
    {
        "id": "screening",
        "title": "Screening answers",
        "icon": "shield",
        "blurb": "The recurring yes/no screeners, answered once. Criminal-history questions are "
                 "always escalated to you and never auto-answered.",
        "fields": [
            f("screening.over_18", "Are you at least 18?", "select", options=YES_NO, col=4),
            f("screening.can_perform_essential_functions",
              "Can perform essential functions (with or without accommodation)", "select",
              options=YES_NO, col=4),
            f("screening.consent_background_check", "Consent to background check", "select",
              options=YES_NO, col=4),
            f("screening.consent_drug_test", "Consent to drug test", "select", options=YES_NO, col=4),
            f("screening.has_drivers_license", "Have a driver's licence", "select",
              options=YES_NO, col=4),
            f("screening.has_reliable_transportation", "Reliable transportation", "select",
              options=YES_NO, col=4),
            f("screening.security_clearance", "Security clearance", "select", options=CLEARANCE, col=4),
            f("screening.active_clearance", "Clearance currently active", "select",
              options=YES_NO, col=4),
            f("screening.non_compete_in_force", "Bound by a non-compete", "select",
              options=YES_NO, col=4),
            f("screening.previously_employed_here", "Previously employed at target companies",
              "select", options=YES_NO, col=4),
            f("screening.previously_applied_here", "Previously applied", "select",
              options=YES_NO, col=4),
            f("screening.related_to_employee", "Related to an employee", "select",
              options=YES_NO, col=4),
            f("screening.currently_employed", "Currently employed", "select", options=YES_NO, col=4),
            f("screening.gdpr_consent", "Consent to data processing (GDPR)", "select",
              options=YES_NO, col=4),
            f("screening.gdpr_retention_months", "Data retention (months)", "number", col=4),
            f("screening.marketing_opt_in", "Marketing emails", "select", options=YES_NO, col=4,
              help="Defaults to no"),
            f("screening.criminal_history_policy", "Criminal-history questions", "select",
              options=["always_escalate", "answer_from_profile"], col=6),
            f("screening.criminal_history_answer", "Your answer (only if not escalating)",
              "textarea", col=6),
        ],
    },
    {
        "id": "eeo",
        "title": "Voluntary self-identification",
        "icon": "users",
        "blurb": "Entirely optional, and every field defaults to declining. Employers may not "
                 "use these in hiring decisions. Turn the toggle on only if you want them shared.",
        "fields": [
            f("eeo.share_eeo", "Share these answers on applications", "bool", col=12),
            f("eeo.gender", "Gender", "select", options=GENDER, col=6),
            f("eeo.race_ethnicity", "Race / ethnicity", "select", options=RACE, col=6),
            f("eeo.veteran_status", "Veteran status", "select", options=VETERAN, col=6),
            f("eeo.disability_status", "Disability status (CC-305)", "select",
              options=DISABILITY, col=6),
            f("eeo.uk_ethnicity", "UK ethnicity", col=6),
            f("eeo.gender_identity", "Gender identity", col=6),
            f("eeo.sexual_orientation", "Sexual orientation", col=6),
            f("eeo.religion", "Religion / belief", col=6),
            f("eeo.socioeconomic_background", "Socio-economic background", col=6),
        ],
    },
    {
        "id": "referral",
        "title": "How you found the role",
        "icon": "megaphone",
        "fields": [
            f("referral.default_source", "Default answer to 'how did you hear about us?'",
              "select", options=SOURCES, col=6, free=True),
            f("referral.referrer_name", "Referrer name", col=6),
            f("referral.referrer_email", "Referrer email", "email", col=6),
            f("referral.recruiter_name", "Recruiter name", col=6),
        ],
    },
    {
        "id": "documents",
        "title": "Documents & summary",
        "icon": "file",
        "fields": [
            f("headline", "Headline", col=12, placeholder="Backend engineer, distributed systems"),
            f("summary", "Professional summary", "textarea", col=12),
            f("current_title", "Current title", col=4),
            f("current_company", "Current company", col=4),
            f("years_of_experience", "Years of experience", "number", col=4, step="0.5",
              help="Leave 0 to compute it from your history"),
            f("target_titles", "Target job titles", "tags", col=12),
            f("documents.master_resume_tex", "Master resume (.tex)", "file_path", col=6),
            f("documents.master_resume_pdf", "Master resume (.pdf)", "file_path", col=6),
            f("documents.cover_letter_template", "Cover letter template", "file_path", col=6),
            f("documents.transcript", "Transcript", "file_path", col=6),
            f("documents.portfolio", "Portfolio", "file_path", col=6),
            f("documents.writing_sample", "Writing sample", "file_path", col=6),
            f("documents.references_sheet", "References sheet", "file_path", col=6),
            f("notes", "Private notes", "textarea", col=12),
        ],
    },
]


def ui_schema() -> dict[str, Any]:
    return {"version": 2, "sections": SECTIONS}


def completeness(profile_dict: dict[str, Any]) -> dict[str, Any]:
    """Per-section completion, used by the sidebar progress rings."""
    def get(path: str) -> Any:
        node: Any = profile_dict
        for part in path.split("."):
            if not isinstance(node, dict):
                return None
            node = node.get(part)
        return node

    out: dict[str, Any] = {}
    total_filled = total_fields = 0
    for section in SECTIONS:
        filled = count = 0
        for field in section.get("fields", []):
            count += 1
            value = get(field["path"])
            if value not in (None, "", [], {}, 0, False):
                filled += 1
        repeat = section.get("repeat")
        if repeat:
            count += 1
            entries = get(repeat["path"])
            if entries:
                filled += 1
        out[section["id"]] = {"filled": filled, "total": max(count, 1),
                              "pct": round(100 * filled / max(count, 1))}
        total_filled += filled
        total_fields += count
    out["_overall"] = {"filled": total_filled, "total": max(total_fields, 1),
                       "pct": round(100 * total_filled / max(total_fields, 1))}
    return out
