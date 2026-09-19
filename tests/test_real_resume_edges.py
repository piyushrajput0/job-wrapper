"""Bugs found by importing résumés the parser had never seen.

Each test here is a defect that reached a real profile: a template's own GitHub URL, an
Indian CGPA filed against a 4.0 scale, "+918" read as a country code. They are cheap to
re-break and expensive to notice, because a wrong value looks exactly like a right one.
"""
from __future__ import annotations

from jobwrapper.resume.importer import (
    find_location,
    find_postal_address,
    parse_latex,
    parse_spoken_languages,
    read_gpa,
    split_street,
)
from jobwrapper.resume.to_profile import parse_location, split_phone

TEMPLATE_HEADER = r"""
%-------------------------
% Resume in Latex
% Based off of: https://github.com/sb2nov/resume
%------------------------
\documentclass[letterpaper,11pt]{article}
\begin{document}
\begin{center}
    \textbf{\Huge \scshape Priya Ramachandran} \\
    \small +91 98450 31277 $|$ \href{mailto:priya@example.com}{priya@example.com} $|$
    \href{https://github.com/priyar}{github.com/priyar} $|$ Bengaluru, Karnataka, India
\end{center}
\section{Education}
  \resumeSubheading{National Institute of Technology}{Aug. 2017 -- May 2021}
  {Bachelor of Technology in Electronics and Communication Engineering, Minor in Computer Science; GPA: 8.64/10}{Mangalore}
\section{Languages}
  English (Professional), Hindi (Native), Kannada (Conversational)
\end{document}
"""


def test_template_comment_does_not_become_the_candidates_github():
    """sb2nov and Jake's both ship their URL in a header comment, ahead of the real one."""
    assert parse_latex(TEMPLATE_HEADER).links["github"] == "https://github.com/priyar"


def test_degree_minor_and_gpa_are_three_fields_not_one_degree_name():
    edu = parse_latex(TEMPLATE_HEADER).education[0]
    assert edu.degree == "Bachelor of Technology in Electronics and Communication Engineering"
    assert edu.minor == "Computer Science"
    assert (edu.gpa, edu.gpa_scale) == ("8.64", "10")


def test_ten_point_cgpa_keeps_its_scale():
    assert read_gpa("CGPA: 8.64/10") == ("8.64", "10")
    assert read_gpa("GPA: 3.8/4.0") == ("3.8", "4.0")
    assert read_gpa("GPA 8.9") == ("8.9", "10")       # nothing above 5 is a 4.0-scale GPA
    assert read_gpa("GPA 3.4") == ("3.4", "4")
    assert read_gpa("CGPA: 94.2%") == ("94.2", "100")


def test_country_survives_a_three_part_location():
    assert find_location("Bengaluru, Karnataka, India") == "Bengaluru, Karnataka, India"
    assert parse_location("Bengaluru, Karnataka, India")["country"] == "India"


def test_indian_mobile_is_not_split_as_plus_918():
    assert split_phone("+918765432109") == ("+91", "8765432109")
    assert split_phone("00918765432109") == ("+91", "8765432109")
    assert split_phone("+44 7700 900123") == ("+44", "7700900123")
    assert split_phone("+1 (415) 555-0142") == ("+1", "4155550142")
    assert split_phone("+353 86 123 4567") == ("+353", "861234567")


def test_street_is_kept_out_of_the_city():
    assert split_street("1600 Amphitheatre Parkway, Mountain View, CA")[1] == "Mountain View, CA"
    assert find_location("1600 Amphitheatre Parkway, Mountain View, CA 94043") == "Mountain View, CA"
    assert find_location("San Francisco, CA") == "San Francisco, CA"


def test_a_one_line_contact_header_keeps_its_city():
    """"Name · +918765432109 · Rohini, Delhi" is a header, not a street then a city."""
    line = "Test Person  test@example.com \u00b7 +918765432109 \u00b7 Rohini, Delhi 110085"
    assert split_street(line)[0] == ""
    assert find_location(line) == "Rohini, Delhi"
    assert find_postal_address(line)["postal_code"] == "110085"


def test_street_and_postal_code_are_captured_when_the_resume_prints_them():
    found = find_postal_address("House No. 12/B Pocket-4 Sector-11, Rohini, Delhi 110085")
    assert found == {"line1": "House No. 12/B Pocket-4 Sector-11", "postal_code": "110085"}
    assert find_postal_address("San Francisco, CA") == {"line1": "", "postal_code": ""}


def test_spoken_languages_are_read_and_programming_ones_are_not():
    assert parse_spoken_languages("English (Professional), Hindi - Native, Kannada (Conversational)") == {
        "English": "Professional", "Hindi": "Native", "Kannada": "Conversational"}
    assert parse_spoken_languages("Go, Java, Python, SQL") == {}
    assert parse_latex(TEMPLATE_HEADER).spoken_languages["Hindi"] == "Native"
