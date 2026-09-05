#!/usr/bin/env python3
"""Generates src/jobwrapper/data/field_catalog.json - the shared V1/V2 knowledge base.

Editing this file is how you teach the tool about a new application field. The generated JSON
is consumed by the Python resolver (Playwright) and shipped verbatim into the Chrome extension,
so there is exactly one place where field knowledge lives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "src" / "jobwrapper" / "data" / "field_catalog.json"

# Tokens that mean the field is about somebody other than the applicant.
OTHER_PERSON = ["manager", "supervisor", "reference", "referee", "emergency", "referrer",
                "referred by", "friend", "spouse", "recruiter", "contact person", "beneficiary"]


def f(key: str, *, type: str = "text", path: str | None = None, compute: str | None = None,
      const: str | None = None, syn: list[str] | None = None, strong: list[str] | None = None,
      neg: list[str] | None = None, priority: int = 50, group: str = "",
      sensitive: bool = False, enum: str | None = None, escalate: bool = False,
      input_types: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {}
    if path:
        value["path"] = path
    if compute:
        value["compute"] = compute
    if const is not None:
        value["const"] = const
    return {
        "key": key,
        "type": type,
        "value": value,
        "synonyms": syn or [],
        "strong": strong or [],
        "negative": neg or [],
        "priority": priority,
        "group": group,
        "sensitive": sensitive,
        "escalate": escalate,
        "enum": enum,
        "input_types": input_types or [],
    }


FIELDS: list[dict[str, Any]] = []

# ------------------------------------------------------------------ identity
FIELDS += [
    f("first_name", path="identity.legal_first_name", group="identity", priority=95,
      strong=["first name", "firstname", "given name", "first_name"],
      syn=["legal first name", "forename", "fname", "first", "applicant first name",
           "your first name", "prenom", "nombre"],
      neg=OTHER_PERSON, input_types=["text"]),
    f("middle_name", path="identity.legal_middle_name", group="identity", priority=60,
      strong=["middle name", "middlename", "middle initial"],
      syn=["legal middle name", "middle name (optional)", "mi"], neg=OTHER_PERSON),
    f("last_name", path="identity.legal_last_name", group="identity", priority=95,
      strong=["last name", "lastname", "surname", "family name", "last_name"],
      syn=["legal last name", "lname", "apellido", "second name"], neg=OTHER_PERSON),
    f("full_name", compute="full_name", group="identity", priority=90,
      strong=["full name", "name", "your name", "candidate name", "applicant name"],
      syn=["legal name", "full legal name", "complete name", "name (first and last)"],
      neg=OTHER_PERSON + ["first", "last", "middle", "company", "school", "university",
                          "employer", "file", "user", "product", "team", "job", "position"]),
    f("preferred_name", path="identity.preferred_name", group="identity", priority=55,
      strong=["preferred name", "nickname"], syn=["what should we call you", "goes by",
      "preferred first name", "display name"], neg=OTHER_PERSON),
    f("previous_name", path="identity.previous_name", group="identity", priority=30,
      strong=["previous name", "maiden name"], syn=["former name", "other names used"]),
    f("suffix", path="identity.suffix", group="identity", priority=25,
      strong=["suffix"], syn=["name suffix", "jr/sr"]),
    f("pronouns", path="identity.pronouns", group="identity", priority=30,
      strong=["pronouns"], syn=["preferred pronouns", "what are your pronouns"]),
]

# ------------------------------------------------------------------ contact
FIELDS += [
    f("email", type="email", path="contact.email", group="contact", priority=95,
      strong=["email", "e-mail", "email address"],
      syn=["your email", "contact email", "primary email", "work email", "correo"],
      neg=OTHER_PERSON + ["confirm", "verify", "re-enter", "referrer"], input_types=["email"]),
    f("email_confirm", type="email", path="contact.email", group="contact", priority=70,
      strong=["confirm email", "re-enter email", "verify email", "email confirmation"],
      syn=["repeat email", "confirm your email address"]),
    f("alternate_email", type="email", path="contact.alternate_email", group="contact", priority=25,
      strong=["alternate email", "secondary email"], syn=["other email"]),
    f("phone", type="tel", path="contact.phone", group="contact", priority=95,
      strong=["phone", "phone number", "mobile", "telephone", "cell"],
      syn=["mobile number", "contact number", "primary phone", "cell phone", "your phone",
           "phone (mobile)", "daytime phone", "telefono"],
      neg=OTHER_PERSON + ["country code", "extension", "device type"], input_types=["tel"]),
    f("phone_country_code", type="select", path="contact.phone_country_code", group="contact",
      priority=60, strong=["country phone code", "phone code", "country code"],
      syn=["dial code", "phone country code", "+1"]),
    f("phone_device_type", type="select", path="contact.phone_device_type", group="contact",
      priority=50, strong=["phone device type", "device type"], syn=["phone type", "type of phone"]),
    f("phone_extension", type="text", const="", group="contact", priority=20,
      strong=["extension", "ext"], syn=["phone extension"]),
]

# ------------------------------------------------------------------ address
FIELDS += [
    f("address_line1", path="address.line1", group="address", priority=85,
      strong=["address line 1", "address", "street address", "addressline1", "address1"],
      syn=["street", "current address", "home address", "mailing address", "residential address",
           "address line one", "street name and number"],
      neg=["email", "line 2", "ip", "website", "url", "company address"]),
    f("address_line2", path="address.line2", group="address", priority=60,
      strong=["address line 2", "address2", "addressline2"],
      syn=["apt", "apartment", "suite", "unit", "line 2", "address line two"]),
    f("city", path="address.city", group="address", priority=85,
      strong=["city", "town", "city name"], syn=["current city", "city of residence",
      "city/town", "locality", "ciudad"], neg=["company", "birth", "employer"]),
    f("state", type="select", path="address.state", group="address", priority=85,
      strong=["state", "province", "region", "state/province"],
      syn=["state or province", "county/state", "estado", "state/region"],
      neg=["united states", "employment state", "state of incorporation"]),
    f("postal_code", path="address.postal_code", group="address", priority=85,
      strong=["zip", "zip code", "postal code", "postcode", "zipcode"],
      syn=["post code", "pin code", "zip/postal code"]),
    f("country", type="select", path="address.country", group="address", priority=85,
      strong=["country", "country of residence"],
      syn=["nation", "country/region", "which country do you live in"],
      neg=["country code", "citizenship", "birth"]),
    f("county", path="address.county", group="address", priority=25, strong=["county"]),
    f("location", compute="location_city_state_country", group="address", priority=80,
      strong=["location", "current location", "where are you located", "your location"],
      syn=["where are you based", "location (city, state)", "city, state", "current city and state",
           "primary location", "where do you live", "location preference"],
      neg=["job location", "office location", "work location", "preferred office"]),
    f("timezone", path="address.timezone", group="address", priority=30,
      strong=["time zone", "timezone"], syn=["what timezone are you in", "working timezone"]),
]

# ------------------------------------------------------------------ links
for k, label, extra in [
    ("linkedin", "linkedin", ["linkedin url", "linkedin profile", "linkedin.com", "li profile"]),
    ("github", "github", ["github url", "github profile", "github.com", "git profile"]),
    ("portfolio", "portfolio", ["portfolio url", "portfolio link", "personal site", "portfolio/website"]),
    ("website", "website", ["personal website", "website url", "your website", "homepage", "web site"]),
    ("twitter", "twitter", ["twitter url", "x.com", "twitter handle", "x profile"]),
    ("stackoverflow", "stack overflow", ["stackoverflow url", "stack overflow profile"]),
    ("dribbble", "dribbble", ["dribbble url"]),
    ("behance", "behance", ["behance url"]),
    ("google_scholar", "google scholar", ["scholar profile", "publications url"]),
    ("orcid", "orcid", ["orcid id"]),
    ("kaggle", "kaggle", ["kaggle profile"]),
    ("blog", "blog", ["blog url", "medium", "substack", "writing"]),
    ("other", "other website", ["other url", "other link", "additional link", "other profile"]),
]:
    FIELDS.append(f(f"link_{k}", type="url", path=f"links.{k}", group="links",
                    priority=70 if k in {"linkedin", "github", "portfolio"} else 45,
                    strong=[label], syn=extra, input_types=["url"]))

# ------------------------------------------------------------------ work authorisation
FIELDS += [
    f("work_authorized", type="radio", compute="work_authorized", group="authorization",
      priority=90, enum="yes_no",
      strong=["legally authorized to work", "authorized to work", "work authorization",
              "eligible to work", "right to work"],
      syn=["are you legally authorized to work in the united states",
           "are you legally eligible to work", "do you have the legal right to work",
           "are you authorised to work", "legally entitled to work",
           "are you able to work lawfully", "us work authorization"],
      neg=["sponsorship", "visa sponsorship"]),
    f("requires_sponsorship", type="radio", compute="requires_sponsorship", group="authorization",
      priority=92, enum="yes_no",
      strong=["require sponsorship", "need sponsorship", "visa sponsorship", "sponsorship"],
      syn=["will you now or in the future require sponsorship",
           "do you now or will you in the future require sponsorship",
           "will you require visa sponsorship", "require immigration sponsorship",
           "do you require sponsorship to work", "need visa support",
           "will you require the company to commence an immigration case"]),
    f("visa_status", type="select", compute="visa_status", group="authorization", priority=70,
      strong=["visa status", "work authorization status", "immigration status"],
      syn=["current work authorization", "what is your visa status", "employment authorization",
           "which best describes your work authorization", "citizenship status"]),
    f("work_permit_expiry", type="date", compute="work_permit_expiry", group="authorization",
      priority=30, strong=["work permit expiry", "ead expiration", "visa expiration"],
      syn=["opt end date", "authorization expiration date"]),
    f("permanent_resident", type="radio", compute="permanent_resident", group="authorization",
      priority=40, enum="yes_no", strong=["permanent resident"],
      syn=["are you a permanent resident", "pr status"]),
]

# ------------------------------------------------------------------ education
FIELDS += [
    f("school", compute="school", group="education", priority=75,
      strong=["school", "university", "college", "institution", "school name"],
      syn=["name of institution", "educational institution", "alma mater", "university/college"],
      neg=["high school graduation", "school district"]),
    f("degree", type="select", compute="degree", group="education", priority=75,
      strong=["degree", "degree level", "highest degree", "education level"],
      syn=["level of education", "highest level of education completed", "qualification",
           "degree earned", "what degree"]),
    f("field_of_study", compute="field_of_study", group="education", priority=70,
      strong=["field of study", "major", "discipline", "course of study"],
      neg=["minor", "second major"],
      syn=["area of study", "concentration", "subject", "specialization", "major/field of study",
           "what did you study"]),
    f("minor", compute="minor", group="education", priority=45,
      strong=["minor", "minor field of study", "minor degree", "academic minor", "minor(s)"],
      syn=["secondary field of study", "what was your minor"]),
    f("gpa", compute="gpa", group="education", priority=50,
      strong=["gpa", "grade point average"], syn=["cgpa", "gpa (out of 4.0)", "academic average",
      "percentage/gpa", "final grade"]),
    f("gpa_scale", compute="gpa_scale", group="education", priority=20,
      strong=["gpa scale", "grading scale"], syn=["out of"]),
    f("education_start", type="date", compute="education_start", group="education", priority=40,
      strong=["education start date", "from (education)"], syn=["attended from", "start year"]),
    f("education_end", type="date", compute="education_end", group="education", priority=45,
      strong=["graduation date", "education end date", "degree completion date"],
      syn=["expected graduation", "graduation year", "year of graduation", "completion date",
           "to (education)", "end year", "date of graduation"]),
    f("currently_attending", type="checkbox", compute="currently_attending", group="education",
      priority=25, enum="yes_no", strong=["currently attending"], syn=["still enrolled",
      "i currently attend this school"]),
]

# ------------------------------------------------------------------ experience
FIELDS += [
    f("current_company", compute="current_company", group="experience", priority=75,
      strong=["current company", "company", "employer", "current employer", "organization"],
      syn=["most recent employer", "company name", "current organization", "where do you work",
           "present employer", "org"],
      neg=["company size", "why this company", "school", "reference", "manager", "supervisor",
           "recruiter", "referrer"]),
    f("current_title", compute="current_title", group="experience", priority=75,
      strong=["current title", "job title", "current role", "your title", "position title"],
      syn=["most recent title", "current job title", "occupation", "what is your current role",
           "present position"],
      neg=["job title you are applying", "position applied for", "desired title"]),
    f("years_experience", type="number", compute="years_experience", group="experience",
      priority=65, strong=["years of experience", "total experience", "years experience"],
      syn=["how many years of experience", "yrs of experience", "relevant experience (years)",
           "total years of professional experience", "experience in years"]),
    f("employment_start", type="date", compute="employment_start", group="experience", priority=35,
      strong=["employment start date", "start date (employment)"], syn=["from date", "date started"],
      neg=["available start", "earliest start"]),
    f("employment_end", type="date", compute="employment_end", group="experience", priority=35,
      strong=["employment end date"], syn=["to date", "date ended", "last day"]),
    f("reason_for_leaving", type="textarea", compute="reason_for_leaving", group="experience",
      priority=25, strong=["reason for leaving"], syn=["why did you leave"]),
    f("may_contact_employer", type="radio", compute="may_contact_employer", group="experience",
      priority=30, enum="yes_no", strong=["may we contact this employer", "may we contact"],
      syn=["can we contact your current employer", "ok to contact"]),
    f("supervisor_name", compute="supervisor_name", group="experience", priority=20,
      strong=["supervisor name", "supervisor", "manager name", "manager's name"],
      syn=["reporting manager", "name of your manager", "direct manager"]),
]

# ------------------------------------------------------------------ compensation & logistics
FIELDS += [
    f("desired_salary", compute="desired_salary", group="compensation", priority=70,
      strong=["desired salary", "salary expectation", "expected salary", "compensation expectation",
              "salary requirements"],
      syn=["what are your salary expectations", "desired compensation", "expected ctc",
           "target salary", "salary desired", "base salary expectation", "compensation requirement",
           "what is your expected salary range", "pay expectation"],
      neg=["current salary", "salary history", "last drawn"]),
    f("current_salary", compute="current_salary", group="compensation", priority=40,
      sensitive=True, strong=["current salary", "salary history", "current compensation"],
      syn=["last drawn salary", "current ctc", "present salary", "existing compensation"]),
    f("hourly_rate", type="number", compute="hourly_rate", group="compensation", priority=35,
      strong=["hourly rate", "rate per hour"], syn=["expected hourly rate", "bill rate"]),
    f("start_date_available", type="date", compute="earliest_start_date", group="logistics",
      priority=70, strong=["available start date", "earliest start date", "when can you start",
                           "availability date", "start date"],
      syn=["date available to start", "earliest available start date", "when are you available",
           "notice period end", "available from"]),
    f("notice_period", compute="notice_period", group="logistics", priority=45,
      strong=["notice period"], syn=["how much notice", "notice required", "current notice period"]),
    f("willing_to_relocate", type="radio", compute="willing_to_relocate", group="logistics",
      priority=60, enum="yes_no", strong=["willing to relocate", "open to relocation", "relocate"],
      syn=["are you willing to relocate", "would you relocate", "relocation"]),
    f("relocation_assistance", type="radio", compute="relocation_assistance", group="logistics",
      priority=30, enum="yes_no", strong=["relocation assistance"],
      syn=["do you need relocation assistance", "require relocation support"]),
    f("work_model_preference", type="select", compute="work_model_preference", group="logistics",
      priority=55, strong=["work model", "remote or onsite", "work preference", "work arrangement"],
      syn=["do you prefer remote", "hybrid or remote", "preferred work location",
           "work location preference", "office preference", "onsite/hybrid/remote"]),
    f("commute_ok", type="radio", compute="commute_ok", group="logistics", priority=40,
      enum="yes_no", strong=["able to commute", "willing to commute", "comfortable commuting"],
      syn=["can you commute to the office", "reliably commute"]),
    f("willing_to_travel", type="radio", compute="willing_to_travel", group="logistics",
      priority=35, enum="yes_no", strong=["willing to travel", "able to travel"],
      syn=["travel requirement", "comfortable with travel"]),
    f("employment_type_pref", type="select", compute="employment_type_pref", group="logistics",
      priority=30, strong=["employment type", "type of employment"],
      syn=["full-time or part-time", "contract or full time"]),
]

# ------------------------------------------------------------------ screening
FIELDS += [
    f("over_18", type="radio", path="screening.over_18", group="screening", priority=50,
      enum="yes_no", strong=["are you at least 18", "over 18", "18 years of age"],
      syn=["are you 18 years or older", "minimum age requirement"]),
    f("essential_functions", type="radio", path="screening.can_perform_essential_functions",
      group="screening", priority=40, enum="yes_no",
      strong=["essential functions", "perform the essential functions"],
      syn=["with or without reasonable accommodation", "able to perform the duties"]),
    f("background_check", type="radio", path="screening.consent_background_check",
      group="screening", priority=45, enum="yes_no",
      strong=["background check", "background screening"],
      syn=["consent to a background check", "willing to undergo a background check"]),
    f("drug_test", type="radio", path="screening.consent_drug_test", group="screening",
      priority=40, enum="yes_no", strong=["drug test", "drug screening"],
      syn=["willing to submit to a drug test", "pre-employment drug screen"]),
    f("drivers_license", type="radio", path="screening.has_drivers_license", group="screening",
      priority=35, enum="yes_no", strong=["driver's license", "drivers license", "driving licence"],
      syn=["valid driver's license", "do you have a license to drive"]),
    f("security_clearance", type="select", path="screening.security_clearance", group="screening",
      priority=40, strong=["security clearance", "clearance level"],
      syn=["do you hold a security clearance", "active clearance", "what level of clearance"]),
    f("non_compete", type="radio", path="screening.non_compete_in_force", group="screening",
      priority=30, enum="yes_no", strong=["non-compete", "noncompete"],
      syn=["are you bound by a non-compete", "restrictive covenant"]),
    f("previously_employed", type="radio", path="screening.previously_employed_here",
      group="screening", priority=45, enum="yes_no",
      strong=["previously employed", "former employee", "worked here before"],
      syn=["have you ever worked for", "are you a former employee", "prior employment with us"]),
    f("previously_applied", type="radio", path="screening.previously_applied_here",
      group="screening", priority=40, enum="yes_no",
      strong=["previously applied", "applied before"],
      syn=["have you applied to this company before", "prior application"]),
    f("related_to_employee", type="radio", path="screening.related_to_employee", group="screening",
      priority=35, enum="yes_no", strong=["related to an employee", "relatives employed"],
      syn=["do you know anyone who works here", "family member employed",
           "do you have relatives working at"]),
    f("criminal_history", type="radio", compute="criminal_history", group="screening",
      priority=60, escalate=True, sensitive=True,
      strong=["convicted", "criminal", "felony", "misdemeanor", "criminal record"],
      syn=["have you ever been convicted", "criminal background", "pleaded guilty"]),
    f("gdpr_consent", type="checkbox", path="screening.gdpr_consent", group="screening",
      priority=55, enum="yes_no",
      strong=["privacy policy", "gdpr", "data processing consent", "terms and conditions"],
      syn=["i agree to the processing of my personal data", "consent to store my data",
           "i have read and accept the privacy notice", "data retention consent",
           "i accept the terms"]),
    f("future_roles_consent", type="checkbox", const="yes", group="screening", priority=35,
      enum="yes_no", strong=["consider me for future roles", "future opportunities"],
      syn=["keep my details for other positions", "add me to the talent pool"]),
    f("marketing_opt_in", type="checkbox", path="screening.marketing_opt_in", group="screening",
      priority=45, enum="yes_no", strong=["marketing", "newsletter", "promotional"],
      syn=["send me updates", "subscribe to job alerts", "receive emails about"]),
]

# ------------------------------------------------------------------ EEO / self-identification
FIELDS += [
    f("eeo_gender", type="select", compute="eeo_gender", group="eeo", priority=60, sensitive=True,
      strong=["gender", "sex"], syn=["what is your gender", "gender identity (eeo)",
      "please select your gender"], neg=["gender identity", "pronoun"]),
    f("eeo_race", type="select", compute="eeo_race", group="eeo", priority=60, sensitive=True,
      strong=["race", "ethnicity", "race/ethnicity"],
      syn=["racial identity", "which race or ethnicity", "ethnic background", "hispanic or latino"]),
    f("eeo_veteran", type="select", compute="eeo_veteran", group="eeo", priority=60, sensitive=True,
      strong=["veteran", "veteran status", "protected veteran"],
      syn=["are you a protected veteran", "military service", "veteran self-identification"]),
    f("eeo_disability", type="select", compute="eeo_disability", group="eeo", priority=60,
      sensitive=True, strong=["disability", "disability status"],
      syn=["do you have a disability", "voluntary self-identification of disability",
           "cc-305", "form cc-305", "1250-0005"]),
    f("eeo_name", compute="full_name", group="eeo", priority=40,
      strong=["your name (cc-305)", "please enter your name"],
      syn=["name (voluntary self-identification)", "employee name"]),
    f("eeo_date", type="date", compute="today", group="eeo", priority=40,
      strong=["today's date", "date (cc-305)"], syn=["date signed", "current date"]),
    f("uk_ethnicity", type="select", path="eeo.uk_ethnicity", group="eeo", priority=30,
      sensitive=True, strong=["ethnic group", "ethnic origin"], syn=["ons ethnicity"]),
    f("sexual_orientation", type="select", path="eeo.sexual_orientation", group="eeo", priority=30,
      sensitive=True, strong=["sexual orientation"], syn=["how do you describe your sexuality"]),
    f("religion", type="select", path="eeo.religion", group="eeo", priority=25, sensitive=True,
      strong=["religion", "religious belief"], syn=["faith"]),
    f("gender_identity", type="select", path="eeo.gender_identity", group="eeo", priority=30,
      sensitive=True, strong=["gender identity", "transgender"],
      syn=["do you identify as transgender", "gender identity (voluntary)"]),
]

# ------------------------------------------------------------------ source / referral
FIELDS += [
    f("how_heard", type="select", compute="how_heard", group="source", priority=55,
      strong=["how did you hear about us", "how did you find", "source"],
      syn=["how did you hear about this job", "where did you hear about this role",
           "how did you learn about this opportunity", "referral source",
           "how did you find out about this position", "what brought you here"]),
    f("referrer_name", compute="referrer_name", group="source", priority=40,
      strong=["referred by", "referrer name", "employee referral"],
      syn=["name of the person who referred you", "who referred you"]),
    f("referrer_email", type="email", compute="referrer_email", group="source", priority=30,
      strong=["referrer email"], syn=["email of the person who referred you"]),
]

# ------------------------------------------------------------------ documents
FIELDS += [
    f("resume_file", type="file", compute="resume_path", group="documents", priority=95,
      strong=["resume", "cv", "resume/cv", "upload resume", "attach resume"],
      syn=["curriculum vitae", "resume file", "upload your cv", "attach your resume",
           "resume upload", "cv upload", "drop your resume"],
      neg=["cover letter", "portfolio", "transcript", "writing sample"]),
    f("cover_letter_file", type="file", compute="cover_letter_path", group="documents",
      priority=70, strong=["cover letter", "covering letter"],
      syn=["upload cover letter", "attach a cover letter", "motivation letter"]),
    f("cover_letter_text", type="textarea", compute="cover_letter_text", group="documents",
      priority=65, strong=["cover letter", "why do you want to work"],
      syn=["tell us why you are a good fit", "message to hiring manager",
           "additional information", "paste your cover letter"]),
    f("transcript_file", type="file", path="documents.transcript", group="documents", priority=30,
      strong=["transcript"], syn=["academic transcript", "upload transcript"]),
    f("portfolio_file", type="file", path="documents.portfolio", group="documents", priority=30,
      strong=["portfolio file"], syn=["upload portfolio", "work samples"]),
    f("writing_sample_file", type="file", path="documents.writing_sample", group="documents",
      priority=25, strong=["writing sample"], syn=["upload writing sample"]),
]

# ------------------------------------------------------------------ account creation
FIELDS += [
    f("account_password", type="password", compute="generated_password", group="account",
      priority=80, sensitive=True, strong=["password", "create password"],
      syn=["choose a password", "new password", "account password"],
      neg=["confirm", "current password", "re-enter"]),
    f("account_password_confirm", type="password", compute="generated_password", group="account",
      priority=75, sensitive=True,
      strong=["confirm password", "re-enter password", "verify password", "retype password"],
      syn=["repeat password", "password confirmation"]),
    f("terms_accept", type="checkbox", const="yes", group="account", priority=60, enum="yes_no",
      strong=["i agree to the terms", "terms of use", "terms of service"],
      syn=["accept terms and conditions", "i have read and agree"]),
]

# ------------------------------------------------------------------ free-text essays
FIELDS += [
    f("why_company", type="textarea", compute="essay", group="essay", priority=50,
      strong=["why do you want to work here", "why our company", "why us"],
      syn=["what interests you about this company", "why are you interested in this company",
           "what excites you about", "why do you want to join"]),
    f("why_role", type="textarea", compute="essay", group="essay", priority=50,
      strong=["why this role", "why are you interested in this position"],
      syn=["what interests you about this role", "why are you a good fit for this role",
           "what makes you a strong candidate"]),
    f("additional_info", type="textarea", compute="essay", group="essay", priority=35,
      strong=["additional information", "anything else"],
      syn=["is there anything else you would like us to know", "other comments", "notes"]),
]

DATA = {
    "version": 3,
    "generated_by": "scripts/build_field_catalog.py",
    "fields": FIELDS,
    "option_synonyms": {
        "yes": ["yes", "y", "true", "yes i am", "i am", "i do", "i have", "affirmative",
                "yes - i am", "yes, i am", "yes i do", "agree", "i agree", "accept", "confirmed"],
        "no": ["no", "n", "false", "no i am not", "i am not", "i do not", "i don't", "i have not",
               "negative", "no - i am not", "no, i am not", "decline", "disagree"],
        "decline": ["decline to self identify", "decline to self-identify", "i don't wish to answer",
                    "i do not want to answer", "prefer not to say", "prefer not to answer",
                    "choose not to disclose", "not specified", "i decline to answer",
                    "do not wish to disclose", "prefer not to disclose", "n/a"],
    },
    "enum_maps": {
        "yes_no": {"yes": ["yes"], "no": ["no"], "prefer_not_to_say": ["decline"]},
    },
    "sensitive_never_fill": [
        "social security", "ssn", "national insurance number", "passport number", "date of birth",
        "driver's license number", "bank account", "routing number", "credit card", "mother's maiden",
        "aadhaar", "pan number", "tax id",
    ],
    "human_required_signals": [
        "captcha", "recaptcha", "hcaptcha", "verify you are human", "i'm not a robot",
        "two-factor", "verification code", "one-time code", "hirevue", "hackerrank",
        "codility", "codesignal", "assessment invitation", "video interview",
    ],
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(DATA, indent=2, ensure_ascii=False))
keys = [x["key"] for x in FIELDS]
assert len(keys) == len(set(keys)), f"duplicate keys: {[k for k in keys if keys.count(k) > 1]}"
print(f"wrote {OUT} with {len(FIELDS)} fields across {len({x['group'] for x in FIELDS})} groups")
