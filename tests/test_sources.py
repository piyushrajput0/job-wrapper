"""Source discovery: detection from a page, and probing the board APIs when the page is silent."""

from jobwrapper.autofill import FieldResolver, ResolveContext
from jobwrapper.models.application import FieldDescriptor as FD
from jobwrapper.sources import candidate_slugs, detect_from_text, probe_boards


class FakeHttp:
    """Answers a scripted set of URLs; everything else 404s."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def get_json(self, url, **kwargs):
        self.calls.append(url)
        for fragment, payload in self.responses.items():
            if fragment in url:
                return payload
        return None

    def get(self, url, **kwargs):
        return None


def test_detect_from_page_markup():
    cases = {
        '<script src="https://boards.greenhouse.io/embed/job_board/js?for=stripe">': ("greenhouse", "stripe"),
        "apply at https://jobs.lever.co/netflix/abc": ("lever", "netflix"),
        "https://jobs.ashbyhq.com/notion/1234": ("ashby", "notion"),
        "https://acme.recruitee.com/o/engineer": ("recruitee", "acme"),
    }
    for markup, (ats, token) in cases.items():
        found = detect_from_text(markup)
        assert found and found.ats == ats and found.token == token


def test_detect_workday_tenant():
    found = detect_from_text("https://acme.wd5.myworkdayjobs.com/en-US/External/job/x")
    assert found.ats == "workday" and found.tenant == "acme" and found.site == "External"


def test_candidate_slugs_from_a_domain():
    slugs = candidate_slugs("www.vector-labs.com", company="Vector Labs")
    assert "vector-labs" in slugs and "vectorlabs" in slugs
    assert "www" not in slugs


def test_probe_finds_a_board_the_page_never_mentions():
    """The point of the probe: JS-rendered career pages expose nothing in their HTML."""
    http = FakeHttp({"posting-api/job-board/mollie": {"jobs": [{"id": "1"}]}})
    found = probe_boards("mollie.com", http)
    assert found and found.ats == "ashby" and found.token == "mollie"


def test_probe_ignores_a_board_with_no_jobs():
    http = FakeHttp({"boards-api.greenhouse.io": {"jobs": []},
                     "api.lever.co": [],
                     "recruitee.com": {"offers": []}})
    assert probe_boards("nobody.example", http) is None


def test_probe_does_not_invent_a_board_for_an_unknown_domain():
    assert probe_boards("some-random-domain.example", FakeHttp({})) is None


def test_frame_is_carried_from_the_page_into_the_fill_plan(profile, job):
    """Greenhouse embeds its form in an iframe; a plan that loses the frame types nowhere."""
    resolver = FieldResolver(profile, ResolveContext(job=job, ats="greenhouse"))
    plan = resolver.resolve_form([
        FD(selector="#first_name", frame="grnhse_iframe", name="job_application[first_name]",
           label="First Name", required=True),
        FD(selector="#email", frame="", name="email", label="Email", input_type="email"),
    ])
    by_key = {f.field_key: f for f in plan.fields}
    assert by_key["first_name"].frame == "grnhse_iframe"
    assert by_key["email"].frame == ""
