"""Importer, tailoring, the truthfulness firewall, and the ATS lint."""


from jobwrapper.config import Config
from jobwrapper.models.resume import BulletRewrite, TailoringPlan
from jobwrapper.resume.ats import ats_lint
from jobwrapper.resume.keywords import extract_keywords
from jobwrapper.resume.render import latex_escape, render_html, render_latex
from jobwrapper.resume.tailor import Tailor, TailorOptions


def test_importer_reads_a_latex_resume(master):
    assert master.name == "Alex Rivera"
    assert master.email == "alex.rivera@example.com"
    assert len(master.experience) == 2
    assert master.experience[0].title == "Senior Software Engineer"
    assert master.experience[0].company == "Northwind Data"
    assert len(master.experience[0].bullets) == 4


def test_importer_reads_the_minor(master):
    assert master.education[0].minor == "Applied Mathematics"
    assert master.education[0].gpa == "3.7"
    assert master.education[0].institution == "University of California, Berkeley"


def test_importer_unescapes_latex(master):
    text = master.text_corpus()
    assert "70%" in text and "\\%" not in text


def test_keywords_flag_what_the_master_cannot_support(master, job):
    keywords = extract_keywords(job, master, None, use_llm=False)
    terms = {k.term: k for k in keywords}
    assert terms["Go"].in_master
    assert "Rust" in terms and not terms["Rust"].in_master


def test_tailoring_reorders_without_inventing(master, profile, job):
    result = Tailor(Config(), master, profile).tailor(job)
    assert result.violations == []
    assert result.ats_score >= 70
    infra = result.resume.skill_groups["Infrastructure"]
    assert infra.index("Kubernetes") < infra.index("AWS")   # JD-relevant skills float up


def test_firewall_catches_invented_skills_and_metrics(master, profile):
    tailor = Tailor(Config(), master, profile)
    plan = TailoringPlan(summary="Rust and Elixir expert.", bullet_rewrites=[
        BulletRewrite(experience_index=0, bullet_index=0,
                      new_text="Built a Rust platform handling 90k events per second.")])
    tailored = tailor._apply_plan(plan, [], TailorOptions())
    violations = tailor._firewall(tailored, plan)
    kinds = {v.kind for v in violations}
    assert "unsupported_keyword" in kinds and "new_metric" in kinds


def test_firewall_repairs_in_strict_mode(master, profile):
    tailor = Tailor(Config(), master, profile)
    plan = TailoringPlan(summary="Rust expert.", bullet_rewrites=[
        BulletRewrite(experience_index=0, bullet_index=0,
                      new_text="Built a Rust platform handling 90k events per second.")])
    tailored = tailor._apply_plan(plan, [], TailorOptions())
    repaired, remaining = tailor._repair(tailored, tailor._firewall(tailored, plan))
    assert remaining == []
    assert "Rust" not in repaired.experience[0].bullets[0].text
    assert "Rust" not in repaired.summary


def test_ats_lint_scores_a_good_resume(master):
    report = ats_lint(master)
    assert report.score >= 70
    assert any("strong verb" in p for p in report.passed)


def test_ats_lint_flags_a_bad_one(master):
    master.email = ""
    master.skill_groups = {}
    master.experience[0].bullets[0].text = "Responsible for various tasks"
    report = ats_lint(master)
    assert report.score < 80
    assert any("email" in n for n in report.notes)


def test_latex_escaping():
    assert latex_escape("100% & $5 #1 _x") == r"100\% \& \$5 \#1 \_x"


def test_renderers_produce_output(master, profile):
    tex = render_latex(master, profile)
    html = render_html(master, profile)
    assert "\\documentclass" in tex and "Northwind Data" in tex
    assert "<h2>Experience</h2>" in html and "Northwind Data" in html
    assert "70\\%" in tex          # escaped for LaTeX
    assert "70%" in html           # plain in HTML


def test_trim_drops_the_weakest_bullets(master):
    before = sum(len(e.bullets) for e in master.experience)
    trimmed = Tailor.trim(master, drop=2)
    assert sum(len(e.bullets) for e in trimmed.experience) < before
