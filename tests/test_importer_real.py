"""Importer against the LaTeX people actually write.

Each case here is a defect found by running the importer over the résumé templates in real use
(Jake's Resume, moderncv, AltaCV, Awesome-CV) rather than over a tidy fixture.
"""

import pytest

from jobwrapper.resume.importer import DEGREE_WORDS, find_phone, import_master_resume

JAKES = r"""
\documentclass{article}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\newcommand{\resumeSubheading}[4]{\textbf{#1} & #2 \\ \textit{#3} & \textit{#4}}
\begin{document}
\textbf{\Huge \scshape Jake Ryan} \\ jake@su.edu $|$ 123-456-7890
\section{Experience}
\resumeSubheading{Undergraduate Research Assistant}{June 2020 -- Present}
  {Texas A\&M University}{College Station, TX}
\resumeItemListStart
  \resumeItem{Developed a \textbf{REST API} using FastAPI to convert data from $650$ sensors.}
  \resumeItem{Cut query latency by 45\% by adding a Redis cache in front of Postgres.}
\resumeItemListEnd
\section{Technical Skills}
Languages: Python, Java, C/C++, SQL \\
Frameworks: React, Node.js, FastAPI
\end{document}
"""

MODERNCV = r"""
\documentclass{moderncv}
\name{John}{Doe}
\begin{document}
john.doe@example.com -- +49 30 12345678
\section{Experience}
\subsection{Vocational}
\cventry{2019--2024}{Senior Engineer}{Zalando}{Berlin}{}{Owned the checkout service end to end.}
\section{Education}
\cventry{2014--2018}{MEng Computing}{Imperial College London}{London}{}{First class honours.}
\end{document}
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_jakes_resume_bullets_are_found(tmp_path):
    """Jake's template wraps bullets in \\resumeItem, not \\item - the single most common case."""
    master = import_master_resume(write(tmp_path, "jakes.tex", JAKES), use_llm=False)
    assert master.name == "Jake Ryan"
    assert len(master.experience) == 1
    bullets = master.experience[0].bullets
    assert len(bullets) == 2
    assert "REST API" in bullets[0].text
    assert "45%" in bullets[1].text          # \% unescaped
    assert master.skill_groups["Languages"][0] == "Python"


def test_two_part_name_macro(tmp_path):
    master = import_master_resume(write(tmp_path, "cv.tex", MODERNCV), use_llm=False)
    assert master.name == "John Doe"


def test_subsection_entries_belong_to_their_parent_section(tmp_path):
    """\\section{Experience} then \\subsection{Vocational}: the entry is still experience."""
    master = import_master_resume(write(tmp_path, "cv.tex", MODERNCV), use_llm=False)
    assert [e.company for e in master.experience] == ["Zalando"]
    assert master.experience[0].bullets, "the trailing \\cventry argument is the description"


def test_non_us_degree_is_recognised(tmp_path):
    master = import_master_resume(write(tmp_path, "cv.tex", MODERNCV), use_llm=False)
    assert master.education and "MEng" in master.education[0].degree


def test_multi_file_project_is_inlined(tmp_path):
    """Overleaf projects are routinely split across files; parsing only main.tex finds nothing."""
    (tmp_path / "sections").mkdir()
    (tmp_path / "sections" / "experience.tex").write_text(r"""
\section{Experience}
\resumeSubheading{Staff Engineer}{Mar 2021 - Present}{Monzo}{London, UK}
\resumeItemListStart
  \resumeItem{Rebuilt the payments ledger in Go, cutting reconciliation time by 65\%.}
\resumeItemListEnd
""")
    main = write(tmp_path, "main.tex", r"""
\documentclass{article}
\name{Priya}{Sharma}
\begin{document}
priya@example.com $\cdot$ +44 7700 900123
\input{sections/experience}
\end{document}
""")
    master = import_master_resume(main, use_llm=False)
    assert master.name == "Priya Sharma"
    assert [e.company for e in master.experience] == ["Monzo"]
    assert "65%" in master.experience[0].bullets[0].text


def test_missing_input_file_does_not_crash(tmp_path):
    main = write(tmp_path, "main.tex",
                 "\\documentclass{article}\\begin{document}\\input{nope/missing}\\end{document}")
    assert import_master_resume(main, use_llm=False).experience == []


def test_input_recursion_is_bounded(tmp_path):
    """A file that includes itself must not hang the importer."""
    loop = tmp_path / "loop.tex"
    loop.write_text("\\documentclass{article}\\begin{document}\\input{loop}\\end{document}")
    assert import_master_resume(loop, use_llm=False) is not None


@pytest.mark.parametrize("raw,expected", [
    ("+44 7700 900123", "+44 7700 900123"),
    ("+91 98765 43210", "+91 98765 43210"),
    ("(415) 555-0142", "(415) 555-0142"),
    ("+49 30 12345678", "+49 30 12345678"),
    ("9876543210", "9876543210"),
])
def test_international_phone_numbers(raw, expected):
    assert find_phone(raw) == expected


@pytest.mark.parametrize("text", ["Worked 2014 - 2018 at Acme", "40k events per second",
                                  "GPA 3.7 / 4.0", "no digits at all"])
def test_phone_finder_does_not_match_dates_or_metrics(text):
    assert find_phone(text) == ""


@pytest.mark.parametrize("degree", ["MEng Computing", "B.Tech in Computer Science", "M.Tech",
                                    "BCA", "MBA", "Bachelor of Science", "LLB"])
def test_degree_vocabulary_covers_non_us_qualifications(degree):
    assert DEGREE_WORDS.search(degree)


@pytest.mark.parametrize("text", ["London, UK", "Senior Engineer", "Northwind Data"])
def test_degree_vocabulary_does_not_match_places_or_titles(text):
    assert not DEGREE_WORDS.search(text)


PLAIN_PDF_TEXT = """Alex Rivera
(415) 555-0142 · alex.rivera@example.com · San Francisco, CA
SKILLS
Languages Python, Go, TypeScript, SQL
Infrastructure AWS, Docker, Kubernetes
EXPERIENCE
Senior Software Engineer Jan 2022 - Present
Northwind Data San Francisco, CA
Built a multi-region ingestion service in Go handling 40k events per second.
Cut p99 API latency from 850ms to 120ms by adding a Redis read-through cache.
Software Engineer Jun 2019 - Dec 2021
Blue Harbor Oakland, CA
Designed a PostgreSQL schema supporting 12 million daily rows.
EDUCATION
University of California, Berkeley Aug 2015 - May 2019
Bachelor of Science in Computer Science. Minor in Applied Mathematics. GPA: 3.7
"""


def test_plain_text_resume_from_a_pdf(tmp_path):
    """Text pulled out of a PDF has no bullet markers and no colons - the common real case."""
    path = tmp_path / "resume.txt"
    path.write_text(PLAIN_PDF_TEXT)
    master = import_master_resume(path, use_llm=False)

    assert master.name == "Alex Rivera"
    assert master.email == "alex.rivera@example.com"
    assert master.skill_groups["Languages"] == ["Python", "Go", "TypeScript", "SQL"]
    assert [e.company for e in master.experience] == ["Northwind Data", "Blue Harbor"]
    assert master.experience[0].location == "San Francisco, CA"
    assert master.experience[0].start_date == "2022-01"
    assert len(master.experience[0].bullets) == 2
    assert master.education and master.education[0].gpa == "3.7"
    assert master.education[0].minor == "Applied Mathematics"


@pytest.mark.parametrize("line,company,location", [
    ("Northwind Data San Francisco, CA", "Northwind Data", "San Francisco, CA"),
    ("Google Mountain View, CA", "Google", "Mountain View, CA"),
    ("Meta Menlo Park, CA", "Meta", "Menlo Park, CA"),
    ("Stripe New York, NY", "Stripe", "New York, NY"),
    ("Infosys Bengaluru, India", "Infosys", "Bengaluru, India"),
    ("Acme Corp | Remote", "Acme Corp", "Remote"),
    ("Just A Company Name", "Just A Company Name", ""),
])
def test_company_and_location_split(line, company, location):
    from jobwrapper.resume.importer import _split_company_location

    assert _split_company_location(line) == (company, location)


def test_skills_are_derived_when_there_is_no_skills_section(tmp_path):
    """A résumé that lists technologies only inside bullets still needs a skills section."""
    path = tmp_path / "no-skills.tex"
    path.write_text(r"""
\documentclass{article}\begin{document}
\Huge Sam Lee \\ sam@example.com
\section{Experience}
\resumeSubheading{Engineer}{2020 - 2024}{Acme}{Remote}
\begin{itemize}
\item Built services in Python and Go, deployed on Kubernetes with Terraform.
\end{itemize}
\end{document}""")
    master = import_master_resume(path, use_llm=False)
    derived = {s for group in master.skill_groups.values() for s in group}
    assert {"Python", "Go", "Kubernetes", "Terraform"} <= derived
