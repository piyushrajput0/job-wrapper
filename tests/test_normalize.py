from jobwrapper.pipeline.normalize import (
    detect_employment_type,
    detect_seniority,
    detect_work_model,
    extract_requirements,
    html_to_text,
    iso_date,
    parse_salary,
    sponsorship_signal,
)


def test_parse_salary_range():
    salary = parse_salary("The base range is $150,000 - $180,000 per year")
    assert (salary.min, salary.max, salary.currency, salary.period) == (150000, 180000, "USD", "annual")


def test_parse_salary_k_notation_and_currency():
    salary = parse_salary("£45k – £60k")
    assert (salary.min, salary.max, salary.currency) == (45000, 60000, "GBP")


def test_parse_salary_hourly():
    salary = parse_salary("$65 - $85 per hour")
    assert salary.period == "hourly" and salary.max == 85


def test_parse_salary_absent():
    assert parse_salary("no numbers here").min is None


def test_html_to_text_handles_double_encoding():
    text = html_to_text("&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;ul&gt;&lt;li&gt;One&lt;/li&gt;&lt;/ul&gt;")
    assert "<" not in text and "Hello & welcome" in text and "- One" in text


def test_detect_work_model():
    assert detect_work_model("This is a fully remote role", "Anywhere") == "remote"
    assert detect_work_model("Hybrid, 3 days in office", "NYC") == "hybrid"


def test_detect_seniority():
    assert detect_seniority("Senior Software Engineer") == "senior"
    assert detect_seniority("Staff Engineer") == "staff"
    assert detect_seniority("Software Engineer", "requires 8+ years") == "senior"


def test_seniority_does_not_match_substrings():
    assert detect_seniority("Sremote Engineer") != "senior"


def test_sponsorship_signal():
    assert sponsorship_signal("We are unable to provide sponsorship") == (True, False)
    assert sponsorship_signal("Visa sponsorship available") == (True, True)
    assert sponsorship_signal("nothing relevant") == (False, False)


def test_employment_type():
    assert detect_employment_type("This is a contract role") == "contract"
    assert detect_employment_type("A permanent position") == "full_time"


def test_iso_date_variants():
    assert iso_date("2025-03-04").startswith("2025-03-04")
    assert iso_date(1719878400).startswith("2024-07-")
    assert iso_date("") == ""


def test_extract_requirements():
    text = "About us\nWe are great.\nRequirements\n- Five years of Go experience here\n- Kubernetes in production\nBenefits\n- Free lunch"
    found = extract_requirements(text)
    assert any("Go experience" in r for r in found)
    assert not any("Free lunch" in r for r in found)
