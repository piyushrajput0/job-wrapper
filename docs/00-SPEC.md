# Job Wrapper - Enhanced Specification

> This document is the "enhanced prompt": the original one-paragraph idea expanded into a
> buildable specification, with the ambiguities resolved and the hard parts named.

## 1. The original request, restated

Build a system that:

1. Takes inputs from a user (what job they want, where, seniority, work authorisation, ...).
2. Searches **many job platforms** and merges the results into one de-duplicated list.
3. For each job worth applying to, **tailors the user's master resume** (kept in Overleaf as
   LaTeX) to that specific job description - injecting the JD's important keywords - compiles a
   **fresh PDF per application**, and uses that PDF for that one application.
4. **Applies** to the job: signs in to the ATS if an account exists, signs up if it does not,
   fills every field of the application form, including the awkward long tail (minor degree,
   street address, work-location preference, sponsorship, veteran status, ...).
5. Ships in **two editions**:
   - **V1 - Aggregator edition**: discovers jobs across the internet, then applies.
   - **V2 - Plugin edition**: a browser extension that runs *on a company's own career site*,
     never searches outside it, and provides identical tailoring + autofill functionality.

## 2. Ambiguities in the original prompt, and how they are resolved

| # | Ambiguity | Resolution |
|---|---|---|
| 1 | "go through different platforms" - scraping LinkedIn/Indeed violates their ToS and gets accounts banned. | Tier sources by legitimacy. **Tier A** = official public JSON APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, RemoteOK, Remotive, Arbeitnow, Jobicy, Himalayas, The Muse, Adzuna, USAJOBS, HN Who's Hiring). Ship these on by default. **Tier B** = browser-driven boards that forbid automation; ship the adapter interface + a disabled-by-default `assisted` mode where the human drives the session and the tool only reads the page the human opened. Never ship a credential-stuffing LinkedIn scraper. |
| 2 | "if we already are user then sign in otherwise signup" - automated account creation is where this tool goes from "assistant" to "bot". | Sign-in is automated using credentials **the user supplies**, stored in a local encrypted vault. Sign-up is a **guided** flow: the tool fills the registration form and stops at the submit button for a human keystroke unless the user sets `auto_signup: true` per-domain. CAPTCHAs and MFA are never solved or bypassed - the browser is handed to the human, and the run resumes after. |
| 3 | "based on the JD we will update the resume" - the line between tailoring and lying. | A **truthfulness firewall**: the tailor may re-order, re-weight, re-phrase, and surface content that already exists in the master profile; it may never introduce a skill, employer, title, date, degree or metric that is not in `master_resume.json`. Every generated resume is diffed against the master and any unsupported claim is rejected (`strict`) or flagged (`review`). |
| 4 | "download it from Overleaf" - Overleaf has no compile API. | Sync the *source* via Overleaf's Git bridge (`git.overleaf.com/<project-id>`), then compile **locally** (Tectonic -> pdflatex -> XeLaTeX -> latexmk), falling back to a remote LaTeX service (opt-in), falling back to an HTML template printed to PDF by the Playwright Chromium that is already installed. Something always produces a PDF. |
| 5 | "it will start applying" - unattended mass-applying is how people get blacklisted and how bad applications get sent. | Three escalating autonomy levels: `dryrun` (fill nothing, produce a plan), `review` (fill everything, screenshot, wait for approval - **default**), `auto` (fill and submit, subject to daily caps, per-domain rate limits, and a minimum match score). |
| 6 | "all the details that it will have and other details sometimes needed" | A canonical **Field Catalog** of 140+ application fields (see `03-APPLICATION-DATA.md`), plus a persistent **Answer Bank**: any question the tool cannot answer is asked once, the answer is stored, and it is never asked again. |
| 7 | Two editions - how much code is duplicated? | Zero duplicated *knowledge*. The field catalog, synonym table, question bank and matching rules live in language-neutral JSON (`src/jobwrapper/data/*.json`) that is consumed by the Python resolver (V1, Playwright) and shipped verbatim into the extension bundle (V2, DOM). Only the ~200-line resolver algorithm exists twice. |

## 3. Non-goals (explicitly out of scope)

- Solving CAPTCHAs, bypassing bot detection, or rotating residential proxies.
- Creating accounts with fabricated identities.
- Fabricating experience, degrees, dates, employers, or metrics.
- Mass-blasting: hard daily caps, per-company caps, and a match-score floor are enforced.
- Scraping platforms whose ToS forbid it, in the default configuration.

## 4. System decomposition

```
                       ┌──────────────────────────────────────────────┐
                       │  Profile  (the single source of truth)        │
                       │  identity · address · work auth · education   │
                       │  experience · skills · EEO · preferences      │
                       │  answer bank · credentials (encrypted vault)  │
                       └───────────────┬──────────────────────────────┘
                                       │
   V1 ─────────────────────────────────┼──────────────────────────── V2
                                       │
  ┌────────────┐   ┌───────────┐       │        ┌───────────────────────┐
  │  Sources   │──▶│ Normalize │       │        │ Chrome MV3 extension  │
  │ 16 adapters│   │  dedupe   │       │        │  on any career site   │
  └────────────┘   └─────┬─────┘       │        └───────────┬───────────┘
                         ▼             │                    │ JD text
                  ┌─────────────┐      │                    ▼
                  │   Matcher   │      │        ┌───────────────────────┐
                  │  score 0-100│      │        │ Companion server      │
                  └──────┬──────┘      │        │ 127.0.0.1:8787 (auth) │
                         ▼             │        └───────────┬───────────┘
                  ┌──────────────────────────────────────────────────┐
                  │  Resume pipeline                                  │
                  │  JD keywords ▶ tailor (Claude) ▶ truth-check ▶     │
                  │  render LaTeX/HTML ▶ compile PDF ▶ ATS lint        │
                  └──────────────────────┬───────────────────────────┘
                                         ▼
                  ┌──────────────────────────────────────────────────┐
                  │  Autofill engine (shared JSON knowledge base)      │
                  │  field catalog · synonyms · answer bank · LLM      │
                  └──────────────────────┬───────────────────────────┘
                          ┌──────────────┴─────────────┐
                          ▼                            ▼
                  ┌───────────────┐            ┌───────────────┐
                  │ Playwright    │            │ DOM adapter   │
                  │ ATS adapters  │            │ (extension)   │
                  └───────────────┘            └───────────────┘
                          │                            │
                          └──────────┬─────────────────┘
                                     ▼
                          ┌──────────────────────┐
                          │ SQLite + audit trail │
                          │ jobs · applications  │
                          │ answers · artifacts  │
                          └──────────────────────┘
```

## 5. The hard parts, and the chosen approach

### 5.1 Field resolution (the core of both editions)

Given a raw form control - a `<label>`, a placeholder, an `aria-label`, a `name` attribute, a
React component with no `<label>` at all - decide *which* profile value belongs in it.

Approach: a **cascade**, cheapest first, and each stage records why it fired.

1. **ATS-specific map** - `name="job_application[first_name]"` on Greenhouse is unambiguous.
   Exact map lookups per ATS, highest confidence.
2. **Token match** against the catalog's synonym lists, normalising the label
   (`lower`, strip punctuation, strip `*`/`(required)`, expand `#`->`number`, `dob`->`date of birth`).
3. **Weighted fuzzy score** - token overlap + prefix bonus + type compatibility
   (a `type="email"` input scores email fields up; a `<select>` scores enum fields up)
   - negative evidence (a field whose label contains "manager" is not the applicant's name).
4. **Answer bank** - has this exact question been answered before, for this company or globally?
5. **LLM fallback** - one batched call classifies every unresolved field at once, given the
   profile summary and the JD; results are written back to the answer bank so stage 4 catches
   them next time. Costs ~1 cheap call per *new* form shape, not per application.
6. **Ask the human** - anything still unresolved and required blocks the submit and is surfaced.

Confidence thresholds: `>=0.85` fill silently, `0.6-0.85` fill and flag for review,
`<0.6` never auto-fill a required field.

### 5.2 Resume tailoring without lying

```
master_resume.json ─┐
                    ├─▶ keyword extraction ─▶ gap analysis ─▶ tailoring plan ─▶ render ─▶ compile
job description ────┘         (JD)              (what the        (bullet          (LaTeX)   (PDF)
                                                 master           rewrites,
                                                 already          re-ordering,
                                                 proves)          skill surfacing)
                                                     │
                                                     ▼
                                           truthfulness firewall
                                     every keyword in the output must trace
                                     to evidence in the master; unsupported
                                     claims are dropped or escalated
```

- Keyword extraction is hybrid: a curated 900-term skill taxonomy catches the canonical stack
  terms deterministically, and the LLM catches the rest (domain nouns, methodologies, phrasing).
  Each keyword gets `importance` (0-1) and `evidence_in_master` (bool).
- The tailoring call is **prompt-cached**: system prompt + master resume + profile form a stable
  prefix (~4-8K tokens) reused across every job in a run, so per-job marginal cost is the JD only.
- Output is a structured `TailoringPlan` (Pydantic, via `messages.parse`), not free text - so it
  can be validated, diffed, cached and replayed.
- **Length guard**: the renderer measures the compiled PDF page count and, if it overflows,
  re-runs the trimming pass deterministically (drop lowest-scored bullets first).

### 5.3 ATS coverage

Six first-class adapters cover the overwhelming majority of the startup/tech market
(Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday), plus a **generic adapter** that
uses the resolver alone and works on anything - which is what makes V2 useful on a random
company career page. See `02-ATS-RESEARCH.md` for the per-ATS field maps and quirks.

### 5.4 Two editions, one brain

| | V1 aggregator | V2 plugin |
|---|---|---|
| Job discovery | 16 source adapters | none - the page you are on |
| Runs in | Python CLI + Playwright | Chrome/Edge MV3 extension |
| Resume tailoring | in-process | companion server at `127.0.0.1:8787` |
| Profile store | SQLite + JSON | `chrome.storage.local`, synced from server |
| Autofill | Playwright locators | DOM `HTMLElement`s |
| Shared | field catalog, synonyms, answer bank, ATS maps, scoring rules (all JSON) | same files, bundled |

## 6. Deliverables

- `jobwrapper` CLI: `init`, `profile`, `resume`, `search`, `list`, `match`, `apply`, `answers`,
  `status`, `export`, `serve`, `doctor`.
- Companion HTTP server for the extension.
- Chrome MV3 extension (`extension/`), loadable unpacked, no build step.
- Documented, versioned knowledge base under `src/jobwrapper/data/`.
- Full audit trail: every field filled, every answer given, every page submitted, screenshotted.
