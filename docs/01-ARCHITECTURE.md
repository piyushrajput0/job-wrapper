# Architecture

## The shape of it

```
                              ┌──────────────────────────┐
                              │  ~/.jobwrapper/          │
                              │   profile.json           │
                              │   master_resume.json     │
                              │   config.yaml            │
                              │   vault.enc  (AES-GCM)   │
                              │   jobwrapper.db (SQLite) │
                              │   artifacts/ pdf,shots   │
                              └───────────┬──────────────┘
                                          │
      ┌───────────────────────────────────┼───────────────────────────────┐
      │                                   │                               │
┌─────▼──────┐                    ┌───────▼────────┐              ┌───────▼────────┐
│  CLI       │                    │ FastAPI server │              │  Chrome MV3    │
│ typer+rich │                    │ 127.0.0.1:8787 │◀── token ───▶│  extension     │
└─────┬──────┘                    └───────┬────────┘              └───────┬────────┘
      │                                   │  serves the web UI            │
      └──────────────┬────────────────────┘                               │
                     ▼                                                    │
        ┌────────────────────────────────────────────────┐                │
        │  core                                          │                │
        │  sources ▶ pipeline ▶ resume ▶ autofill ▶ apply │                │
        └────────────────────┬───────────────────────────┘                │
                             │                                            │
                    ┌────────▼─────────┐                    ┌─────────────▼────────┐
                    │ src/jobwrapper/  │  sync_extension_   │ extension/shared/    │
                    │ data/*.json      │─────data.py───────▶│ data/*.json (copy)   │
                    │ extract_fields.js│                    │ extract_fields.js    │
                    └──────────────────┘                    └──────────────────────┘
                       ONE knowledge base, two runtimes
```

## Why the knowledge base is data, not code

The field catalog (109 field types), the ATS maps (13 vendors), the question patterns and the
skill taxonomy are JSON. Both editions read the same files; only the ~220-line resolver algorithm
exists twice (Python for Playwright, JavaScript for the DOM).

That is enforced, not just intended: `tests/test_parity.py` runs both implementations over the
same 16-field form and asserts they produce the same plan, key for key and value for value.

## The resolution cascade

Given a form control, decide what goes in it — cheapest and most certain first, and record why.

| Stage | Signal | Confidence |
|---|---|---|
| 1. ATS map | `name="job_application[first_name]"` on Greenhouse | 0.98 |
| 2. Dynamic rule | "how many years of **Python**?" → look up that skill | 0.82–0.88 |
| 3. Answer bank | this exact question was answered before | up to 0.97 |
| 4. Strong token | label contains a catalog term exactly | 0.80–1.00 |
| 5. Fuzzy | weighted token overlap, type affinity, negative evidence | 0.60–0.85 |
| 6. Model | one batched call classifies everything still unresolved | its own |
| 7. Human | required and still unknown → blocks the submit | — |

`≥0.85` fills silently · `0.60–0.85` fills and flags for review · below that it never auto-fills a
required field. Anything on the sensitive list (SSN, DOB, criminal history, salary history) or
matching a human-required signal (CAPTCHA, MFA, assessment link) skips the whole cascade and
escalates.

A rule that matched but could not answer is **terminal**: "how many years with COBOL?" does not
fall through to the generic "years of experience" field, because answering it with your total
years would be worse than not answering.

## Data flow, V1

```
config.search ─▶ 19 source adapters (threaded, throttled per host)
              ─▶ normalise (salary, dates, work model, seniority, sponsorship)
              ─▶ dedupe (exact identity, then company-scoped fuzzy title match)
              ─▶ score 0-100 against the profile, with reasons and gaps
              ─▶ SQLite

apply(job)    ─▶ guardrails (caps, score floor, domain lists, already-applied)
              ─▶ tailor résumé ▶ firewall ▶ render ▶ compile ▶ ATS lint
              ─▶ browser: open form, detect ATS, sign in / pre-fill sign-up
              ─▶ per step: extract fields ▶ resolve ▶ answer ▶ fill ▶ screenshot
              ─▶ review queue, or submit at autonomy=auto
              ─▶ application record + append-only audit log
```

## Data flow, V2

```
content script ─▶ is this a posting? a form? both?
               ─▶ extract JD (JSON-LD first, then heuristics)
               ─▶ POST /api/ext/analyze   → score, reasons, keywords
               ─▶ POST /api/ext/tailor    → a PDF for this posting
               ─▶ extract fields (the shared extractor)
               ─▶ POST /api/ext/plan      → fill plan  ── or, offline ──▶ JW.resolver
               ─▶ show the plan, let the user edit values, then fill the DOM
               ─▶ the user submits; POST /api/ext/record
```

## Storage

SQLite via the standard library — no native build step, works wherever Python does.
Tables: `jobs`, `applications`, `answers`, `resumes`, `events`, `source_state`,
`company_profiles`. Migrations are a numbered list applied against `PRAGMA user_version`.

`events` is append-only and every fill, submit and escalation writes to it, so any application
can be reconstructed after the fact from the audit trail plus the per-step screenshots.

## Failure policy

- A broken source logs and is skipped; the run continues.
- A failed résumé compile falls back LaTeX → remote (opt-in) → HTML/Chromium.
- A failed field fill is recorded on the field, not raised; the plan continues.
- An unhandled error in one application does not stop the batch.
- A CAPTCHA, MFA prompt or identity check pauses and hands you the browser.
