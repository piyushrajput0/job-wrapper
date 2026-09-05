"""V1 and V2 must resolve the same form the same way.

The Python resolver (Playwright) and the JS resolver (extension) are two implementations of one
algorithm over one JSON knowledge base. This test runs both over an identical field list and
asserts they agree, so the two editions cannot silently drift apart.
"""

import json
from pathlib import Path

import pytest

from jobwrapper.autofill import FieldResolver, ResolveContext
from jobwrapper.models.application import FieldDescriptor as FD

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "extension"

FIELDS = [
    FD(selector="#fn", name="job_application[first_name]", label="First Name", required=True),
    FD(selector="#ln", name="job_application[last_name]", label="Last Name", required=True),
    FD(selector="#em", name="email", label="Email Address", input_type="email", required=True),
    FD(selector="#ph", name="phone", label="Phone", input_type="tel"),
    FD(selector="#li", name="q1", label="LinkedIn Profile", input_type="url"),
    FD(selector="#addr", name="q2", label="Street Address"),
    FD(selector="#zip", name="q3", label="Zip Code"),
    FD(selector="#auth", name="q4", input_type="radio", options=["Yes", "No"],
       label="Are you legally authorized to work in the United States?"),
    FD(selector="#spon", name="q5", input_type="radio", options=["Yes", "No"],
       label="Will you now or in the future require sponsorship for employment visa status?"),
    FD(selector="#minor", name="q6", label="What was your minor field of study?"),
    FD(selector="#gpa", name="q7", label="GPA"),
    FD(selector="#deg", name="q8", input_type="select", label="Highest level of education completed",
       options=["High School", "Bachelor's Degree", "Master's Degree", "PhD"]),
    FD(selector="#sal", name="q9", label="Desired salary"),
    FD(selector="#gender", name="q10", input_type="select", label="Gender",
       options=["Male", "Female", "Decline To Self Identify"]),
    FD(selector="#felony", name="q11", label="Have you ever been convicted of a felony?",
       input_type="radio", options=["Yes", "No"], required=True),
    FD(selector="#start", name="q12", label="Earliest start date"),
]

HARNESS = """
<!doctype html><meta charset=utf-8><body><script>
  window.chrome = { runtime: { getURL: (p) => "https://ext.local/" + p } };
</script></body>
"""


@pytest.mark.parity
def test_python_and_javascript_resolvers_agree(profile, job, tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")

    context = ResolveContext(job=job, company="Vector Labs", ats="greenhouse",
                             resume_path="/tmp/resume.pdf")
    python_plan = FieldResolver(profile, context).resolve_form(FIELDS, url="https://x/apply")
    python_values = {f.field_key: f.value for f in python_plan.fields}

    scripts = [EXT / "shared" / "util.js", EXT / "shared" / "storage.js",
               EXT / "shared" / "catalog.js", EXT / "shared" / "resolver.js"]

    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()

        # stand in for chrome-extension:// packaging: serve the bundled data files over http
        def serve(route):
            name = route.request.url.rsplit("/", 1)[-1]
            path = EXT / "shared" / "data" / name
            route.fulfill(status=200, content_type="application/json", body=path.read_text()) \
                if path.exists() else route.abort()

        page.route("https://ext.local/**", serve)
        page.route("https://harness.local/**", lambda r: r.fulfill(
            status=200, content_type="text/html", body=HARNESS))
        page.goto("https://harness.local/index.html")
        for script in scripts:
            page.add_script_tag(content=script.read_text())
        js_plan = page.evaluate(
            """async ([fields, profile, ats]) => {
                 await JW.catalog.load();
                 return JW.resolver.resolveForm(fields, profile, { ats });
               }""",
            [[f.model_dump(mode="json") for f in FIELDS],
             json.loads(profile.model_dump_json()), "greenhouse"])
        browser.close()

    js_values = {f["field_key"]: f["value"] for f in js_plan["fields"]}

    # the same fields must resolve, to the same values
    assert set(python_values) == set(js_values), (
        f"only in python: {set(python_values) - set(js_values)}; "
        f"only in js: {set(js_values) - set(python_values)}")
    for key, value in python_values.items():
        assert js_values[key] == value, f"{key}: python={value!r} js={js_values[key]!r}"

    # and both must refuse the felony question
    assert python_plan.blocking and js_plan["blocking"]
    assert any("convicted" in b for b in python_plan.blocking)
    assert any("convicted" in b for b in js_plan["blocking"])
