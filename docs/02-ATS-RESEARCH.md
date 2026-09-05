# ATS & job-source research

Everything the adapters are built on. Endpoints are public, documented, unauthenticated job-board
APIs unless marked otherwise.

---

## Part A - Discovery sources (V1 only)

### A1. ATS job-board APIs (per company; the highest-quality source)

| ATS | Endpoint | Notes |
|---|---|---|
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | `content=true` returns the full HTML JD. `GET .../jobs/{id}?questions=true` returns **the actual application questions** - field names, types, required flags and select options. This is the single most valuable endpoint in the whole system: it lets us build a fill plan before opening a browser. |
| Lever | `GET https://api.lever.co/v0/postings/{site}?mode=json&limit=100&skip=N` | Includes `categories` (team/location/commitment), `lists` (the bulleted JD sections), `applyUrl`. |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | Returns `compensation` tiers - real salary data. |
| Workable | `GET https://apply.workable.com/api/v1/widget/accounts/{subdomain}?details=true` | Public widget feed. |
| SmartRecruiters | `GET https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100&offset=N` | Detail at `/postings/{id}`; a public candidate-create endpoint also exists but is opt-in per company. |
| Recruitee | `GET https://{company}.recruitee.com/api/offers/` | |
| Personio | `GET https://{company}.jobs.personio.de/xml` | XML feed. |
| Breezy | `GET https://{company}.breezy.hr/json` | |
| Workday | `POST https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` body `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}` | Detail: `GET .../job/{externalPath}`. Undocumented-but-stable CXS endpoint used by Workday's own SPA. |

Company->board-token discovery is a solved problem in practice: the token appears in the career
page's iframe/script URL. `jobwrapper sources add` accepts a career-page URL and sniffs the ATS
and token from it (see `sources/careerpage.py`).

### A2. Aggregators with public APIs

| Source | Endpoint | Key? |
|---|---|---|
| RemoteOK | `https://remoteok.com/api` | no (UA header required; element 0 is a legal notice, skip it) |
| Remotive | `https://remotive.com/api/remote-jobs?search=&limit=` | no (UA header required) |
| Arbeitnow | `https://www.arbeitnow.com/api/job-board-api` | no |
| Jobicy | `https://jobicy.com/api/v2/remote-jobs?count=50&geo=&industry=` | no |
| Himalayas | `https://himalayas.app/jobs/api?limit=100` | no |
| The Muse | `https://www.themuse.com/api/public/jobs?page=N&category=` | optional |
| Adzuna | `https://api.adzuna.com/v1/api/jobs/{country}/search/1?app_id=&app_key=` | free key |
| USAJOBS | `https://data.usajobs.gov/api/search` | free key + `User-Agent: <email>` |
| HN "Who is hiring?" | `https://hn.algolia.com/api/v1/search_by_date?query=Ask HN: Who is hiring?&tags=story` then `https://hn.algolia.com/api/v1/items/{id}` | no |

### A3. Sources deliberately **not** implemented as scrapers

LinkedIn, Indeed, Glassdoor, ZipRecruiter, Dice, Monster, Naukri. Their terms prohibit automated
collection, and automating a logged-in session risks the user's account. The architecture leaves
a `LICENSED_API` slot for anyone who holds a legitimate partner key, and V2 (the extension) is
the sanctioned way to work a page the human has opened themselves.

---

## Part B - Application forms (V1 + V2)

### B1. Greenhouse

- Apply URLs: `https://boards.greenhouse.io/{token}/jobs/{id}`, `job-boards.greenhouse.io/...`,
  or embedded at `{company}.com/careers#grnhse_app` via `#grnhse_iframe`.
- Field names: `first_name`, `last_name`, `email`, `phone`, `resume` (file input, often hidden
  behind a styled "Attach" button), `cover_letter`, `job_application[location]`,
  and custom questions as `question_{id}` / `job_application_answers_attributes_{n}_*`.
- EEO block: `job_application[eeoc_gender]`, `_race`, `_veteran_status`, `_disability_status`.
- **Traps**: the location field is a Google-Places autocomplete - must click a suggestion;
  the file input is `display:none` (set files directly, do not click); the whole form may be in
  an iframe.

### B2. Lever

- Apply URL: `https://jobs.lever.co/{site}/{id}/apply`.
- Field names: `name` (single full-name field!), `email`, `phone`, `org` (current company),
  `urls[LinkedIn]`, `urls[GitHub]`, `urls[Portfolio]`, `urls[Other]`, `comments` (additional
  information), `resume`, custom cards as `cards[{cardId}][{fieldName}]`,
  EEO as `eeo[gender]`, `eeo[race]`, `eeo[veteran]`, `eeo[disability]`.
- **Traps**: single `name` field means the profile must be able to render a display name;
  radio groups are `<input type=radio>` with the value in the sibling label text.

### B3. Ashby

- Apply URL: `https://jobs.ashbyhq.com/{org}/{jobId}/application`.
- Fully React-controlled: values must be set through real user events, not `value=`. Fields are
  keyed by `_fieldEntryId`; labels are reliable, `name` attributes are not.
- File upload is a drop-zone wrapping a hidden `<input type=file>`.

### B4. Workable

- Apply URL: `https://apply.workable.com/{account}/j/{shortcode}/apply/`.
- `data-ui` attributes are the stable hooks (`data-ui="firstname"`, `"lastname"`, `"email"`,
  `"phone"`, `"resume"`). Multi-section single page.

### B5. SmartRecruiters

- Apply URL: `https://jobs.smartrecruiters.com/{company}/{id}`; the form is a hosted SPA with
  `#firstName`, `#lastName`, `#email`, `#phoneNumber`, plus a LinkedIn/Indeed import bar.

### B6. Workday (the hard one)

- Apply URL: `https://{tenant}.wd{N}.myworkdayjobs.com/en-US/{site}/job/{path}/apply`.
- **Requires an account** - this is the "sign in, else sign up" case from the brief.
- Wizard steps: *Start* -> *My Information* -> *My Experience* -> *Application Questions* ->
  *Voluntary Disclosures* -> *Self Identify* -> *Review* -> *Submit*.
- Everything is addressed by `data-automation-id` (`legalNameSection_firstName`,
  `addressSection_addressLine1`, `phone-device-type`, `country-phone-code`, `formField-*`,
  `bottom-navigation-next-button`). These IDs are stable across tenants - which is what makes a
  Workday adapter viable at all.
- **Traps**: "Resume upload can auto-fill your experience" - it half-fills and then must be
  corrected; every dropdown is a custom listbox, not a `<select>`; the phone country code is its
  own required control; the session times out after ~15 min of inactivity.

### B7. iCIMS / Taleo / SuccessFactors / Jobvite / BambooHR / JazzHR / Polymer / Rippling

Handled by the **generic adapter**: label-driven resolution, no per-vendor map. iCIMS is
iframe-heavy (`#icims_content_iframe`); Taleo is the oldest and most brittle and is marked
`assisted-only` (human drives, tool advises).

### B8. Universal traps every adapter must handle

1. **Hidden file inputs** - never click, always `set_input_files` on the `input[type=file]`.
2. **Custom listboxes** - a `<div role="listbox">` needs click -> wait for options -> click option.
3. **Iframes** - Greenhouse and iCIMS embed; always search nested frames.
4. **Multi-step wizards** - detect a "Next"/"Continue" button and loop with a step budget.
5. **Autofill-from-resume** - if the ATS pre-fills from the PDF, *verify* rather than overwrite.
6. **Required-field validation on blur** - fill, then blur, then re-read the error region.
7. **CAPTCHA / MFA / identity check** - stop, screenshot, hand the browser to the human.
8. **Duplicate application detection** - "you have already applied" must be recognised as a
   terminal, non-error state.
