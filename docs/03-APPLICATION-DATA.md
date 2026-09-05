# What job applications actually ask for

Research backing the **Field Catalog** (`src/jobwrapper/data/field_catalog.json`). Every group
below is a set of fields the profile must be able to answer without asking the human twice.

Legend: **[core]** asked almost every time · **[common]** asked often · **[longtail]** occasional
but blocking when it appears · **[legal]** legally sensitive, see §12.

---

## 1. Identity [core]

| Field | Notes |
|---|---|
| Legal first name / middle name / last name | Workday and government forms insist on *legal* name; keep separate from preferred |
| Preferred / "goes by" name | Greenhouse & Ashby increasingly ask |
| Previous / maiden name | Background-check flows |
| Pronouns | Optional, offered by Ashby/Greenhouse; default "Decline" |
| Suffix (Jr., PhD) | Workday dropdown |

## 2. Contact [core]

Email (primary + alternate), mobile phone with **country calling code as its own control**
(Workday splits it; Lever does not), device type (mobile/home/work - Workday), preferred
contact method, best time to contact.

## 3. Address [core - and the #1 cause of stalled autofill]

`street_line1`, `street_line2`, `city`, `state_or_province`, `postal_code`, `country`, `county`
(US government/Workday), plus the derived questions:

- "Are you currently located in {city/state/country}?"
- "What is your current city of residence?" (free text; must render as `City, State, Country`)
- "Time zone you work in" - offered as an enum on remote-first companies.

Formatting traps: Workday validates postal code against the selected country; Greenhouse
usually has a single `location` autocomplete backed by Google Places that **must be selected
from the dropdown**, typing alone leaves the field empty on submit.

## 4. Online presence [common]

LinkedIn, GitHub, portfolio/personal site, Twitter/X, StackOverflow, Dribbble/Behance,
Google Scholar, ORCID, Kaggle, Medium/blog, "Other URL". Lever names these `urls[LinkedIn]`,
`urls[GitHub]`, `urls[Portfolio]`, `urls[Other]`.

## 5. Work authorisation & immigration [core, legal]

| Question as it appears | Answer type |
|---|---|
| "Are you legally authorized to work in the United States?" | yes/no |
| "Will you now or in the future require sponsorship for an employment visa (e.g. H-1B)?" | yes/no - **the inverted twin**; answering both consistently is a common bug |
| "What is your current work authorisation status?" | enum: US Citizen · Green Card · GC-EAD · H-1B · H-4 EAD · L-1/L-2 · TN · O-1 · E-3 · F-1 OPT · F-1 STEM OPT · F-1 CPT · J-1 · Refugee/Asylee · Other |
| OPT/STEM-OPT expiry, EAD card dates, I-20 school | date fields, appear on staffing-agency forms |
| "Do you have the right to work in the UK / EU / Canada?" | yes/no per country |
| "Are you a permanent resident of {country}?" | yes/no |
| Visa needed for travel to client sites | yes/no |

The profile stores authorisation **per country** (`work_authorization: {US: {...}, UK: {...}}`),
because the same person answers differently on a US vs UK posting.

## 6. Education [core] - including the long tail the prompt called out

- Degree level (High school · Associate · **Bachelor's** · Master's · MBA · PhD · Bootcamp · Other)
- Institution (Workday uses a typeahead against its own school list - free text often rejected)
- **Field of study / major**
- **Minor** - a genuine long-tail field; Workday and iCIMS both expose it, most people leave it
  blank and then get blocked when it is marked required
- Second major / concentration / specialisation
- GPA **and GPA scale** (4.0 / 10.0 / percentage / first-class honours) - always store both
- Start date, end date, **expected graduation date** (month + year, sometimes separate selects)
- Currently attending? · Did you graduate? · Degree conferred date
- Honours / distinctions, relevant coursework, thesis title, advisor
- Licences & certifications: name, issuer, licence number, issue date, expiry date, state

## 7. Employment history [common]

Employer, job title, employment type, location, start/end (month+year), "I currently work here",
description/responsibilities, reason for leaving, supervisor name + title + phone,
**"May we contact this employer?"**, gaps explanation, and - where still legal - prior salary.

## 8. Compensation & logistics [core]

Desired base salary (number, range, or "negotiable"), currency, pay period (annual/hourly),
total-comp expectation, equity expectation, bonus expectation, **earliest start date**,
notice period, willingness to relocate (+ target locations, + relocation assistance needed),
work-model preference (remote / hybrid / onsite) and acceptable days-in-office,
willingness to travel (%), shift/weekend/overtime availability, contract vs full-time,
currently employed?, other offers in flight + deadline.

## 9. Screening questions [common]

Years of experience with a named technology, self-rated proficiency (1-5 or Beginner..Expert),
language fluency, "have you built/shipped X", team size managed, industry experience,
security clearance level (None · Public Trust · Secret · Top Secret · TS/SCI · with poly),
driver's licence + own vehicle, ability to perform essential functions with or without
reasonable accommodation, minimum age, drug-screen consent, background-check consent,
non-compete in force, previously employed here?, previously applied here?, related to an employee?

## 10. Voluntary self-identification (US) [legal]

Presented on nearly every US posting; **all four are optional and must default to decline**
unless the user explicitly chooses otherwise in their profile.

1. **Gender** - Male · Female · Decline to self-identify (increasingly + Non-binary)
2. **Race/Ethnicity** (EEO-1 categories) - Hispanic or Latino · White · Black or African
   American · Native Hawaiian or Other Pacific Islander · Asian · American Indian or Alaska
   Native · Two or More Races · Decline to self-identify
3. **Protected veteran status** - "I identify as one or more of the classifications of a
   protected veteran" (disabled veteran · recently separated · active-duty wartime or campaign
   badge · Armed Forces service medal) · "I am not a protected veteran" · "I don't wish to answer"
4. **Disability status - Form CC-305, OMB Control Number 1250-0005**. Three options: "Yes, I
   have a disability, or have had one in the past" · "No, I do not have a disability" · "I do
   not want to answer". The form also requires **Name** and **Today's date** fields, which
   autofill must populate or the page fails validation silently.

## 11. Non-US diversity forms [longtail]

UK: right-to-work confirmation, ethnicity per ONS census categories, religion/belief, sexual
orientation, gender identity/trans status, socio-economic background (school type, parental
occupation at 14, free school meals), disability under the Equality Act 2010.
EU/DE: none by law in most cases; instead **GDPR consent** for storing the application, with a
retention period, plus consent to be considered for other roles.
CA: employment equity self-declaration (Aboriginal, visible minority, disability, woman).

## 12. Legally sensitive areas the tool must respect

- **Salary-history bans** (CA, NY, WA, CO, MA, IL, NJ, and many cities): the field may still
  appear; the profile default is "prefer not to say / not applicable".
- **Ban-the-Box**: conviction questions are unlawful pre-offer in many jurisdictions. The tool
  never auto-answers a criminal-history question - it always escalates to the human.
- **Date of birth / age**: never volunteered; "are you over 18?" is answered from the profile,
  full DOB is escalated.
- **Photos / national ID / passport / SSN**: never auto-filled. These belong to post-offer
  onboarding, and a form asking for them pre-offer is a red flag the tool surfaces.

## 13. "How did you hear about us?" [core]

Enum with a free-text twin: Company website · LinkedIn · Indeed · Glassdoor · Referral
(+ employee name and email) · Recruiter (+ name) · Job fair · University career centre ·
Twitter/X · Hacker News · Conference · Other. Referral is the single highest-signal answer and
the profile stores a per-company override.

## 14. Documents [core]

Resume/CV (PDF preferred; some Workday tenants still demand .doc/.docx; typical cap 2-10 MB),
cover letter (file *or* textarea - both must be supported), transcript, portfolio, writing
sample, references sheet, certifications, work-authorisation document, photo (non-US only).

## 15. Free-text essays [common]

"Why do you want to work here?" · "Why this role?" · "What interests you about our product?" ·
"Describe a project you are proud of" · "Tell us about a time you..." · "What is your favourite
{tool/book/bug}?" · "Anything else we should know?" · "Salary expectations and reasoning".
These are generated per-application from the profile + JD, cached by question hash, and always
shown to the human in `review` mode before submission.

## 16. Account creation [core for Workday/iCIMS/Taleo/SuccessFactors]

Email, password + confirm, security question/answer, phone verification, terms-of-use checkbox,
privacy-policy checkbox, **marketing opt-in (default: unchecked)**, "create profile from resume"
upload. Passwords are generated to the site's stated policy and written to the encrypted vault -
never reused, never derived from the user's other passwords.

## 17. Assessments (always human-escalated)

HackerRank / Codility / CodeSignal invitations, Predictive Index / Criteria cognitive tests,
personality inventories, HireVue one-way video interviews, take-home projects. The tool records
that they exist, stores the link, and notifies - it never attempts them.
