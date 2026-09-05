from jobwrapper.config import MatchConfig, SearchConfig
from jobwrapper.models import Job
from jobwrapper.pipeline.dedupe import dedupe_jobs
from jobwrapper.pipeline.match import extract_skills, score_job


def make(**kwargs):
    return Job(**{"company": "Acme", "title": "Backend Engineer", "location": "Remote", **kwargs})


def test_dedupe_exact_identity():
    jobs = [make(source="remoteok"), make(source="greenhouse", description="full text here")]
    out = dedupe_jobs(jobs)
    assert len(out) == 1
    assert out[0].source == "greenhouse"          # the richer source wins
    assert "also:remoteok" in out[0].tags


def test_dedupe_near_duplicate_titles():
    jobs = [make(title="Senior Backend Engineer", source="lever"),
            make(title="Backend Engineer (Senior)", source="remotive")]
    assert len(dedupe_jobs(jobs)) == 1


def test_dedupe_keeps_different_roles():
    jobs = [make(title="Backend Engineer"), make(title="Product Designer")]
    assert len(dedupe_jobs(jobs)) == 2


def test_extract_skills_aliases():
    found = extract_skills("We use Golang, postgres and k8s")
    assert {"Go", "PostgreSQL", "Kubernetes"} <= found


def test_extract_skills_avoids_substrings():
    assert "Go" not in extract_skills("We are going to Google things")


def test_score_job_rewards_overlap(profile, job):
    result = score_job(job, profile, SearchConfig(titles=["Backend Engineer"]), MatchConfig())
    assert result.score > 55
    assert any("skills" in r for r in result.reasons)


def test_score_job_excluded_title(profile, job):
    search = SearchConfig(titles=["Backend Engineer"], exclude_titles=["Senior"])
    result = score_job(job, profile, search, MatchConfig())
    assert result.disqualified


def test_score_job_remote_only(profile):
    onsite = Job(company="Acme", title="Backend Engineer", location="Austin, TX",
                 description="onsite five days a week")
    result = score_job(onsite, profile, SearchConfig(remote_only=True), MatchConfig())
    assert result.disqualified and "remote" in result.disqualified_reason


def test_score_penalises_no_sponsorship(profile, job):
    profile.work_authorization.by_country["US"].requires_sponsorship_future = "yes"
    job.description += " We are unable to provide sponsorship for this role."
    result = score_job(job, profile, SearchConfig(titles=["Backend Engineer"]), MatchConfig())
    assert any("sponsor" in g for g in result.gaps)
