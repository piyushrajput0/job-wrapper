# The résumé pipeline

One PDF per application, generated from one master, with a firewall in the middle.

```
Overleaf (git bridge)  ─┐
resume.tex / .json / md ├─▶ import ─▶ master_resume.json ──┐
                        ┘   (parser + optional model pass)  │
                                                            ▼
job description ─▶ keyword extraction ─▶ gap analysis ─▶ tailoring plan
                   taxonomy + phrases      what the        (structured,
                   + optional model        master proves    validated)
                                                            │
                                                            ▼
                                            apply plan ─▶ TRUTHFULNESS FIREWALL
                                                            │
                                        render (Jinja2 → LaTeX or HTML)
                                                            │
                              compile: tectonic → latexmk → pdflatex → xelatex
                                       → remote (opt-in) → Chromium print
                                                            │
                                       page-count check ─▶ trim ─▶ recompile
                                                            │
                                                    ATS lint ▶ PDF
```

## Import

`.tex` is parsed without a TeX engine: comments stripped, environments removed, escapes
un-escaped (`\%` → `%`), then macro *arguments* are read as balanced brace groups and classified
by content rather than position — because `\resumeSubheading{a}{b}{c}{d}` means different things
in different templates. A date range, an institution keyword, a "City, ST" pattern and a
job-title keyword each claim their slot; whatever is left becomes the company.

With an API key, a model pass runs as well and whichever pass found more structure wins.

## Keyword extraction

Two passes producing one shape:

1. **Deterministic** — 166 canonical skills with 521 aliases (so *Golang*, *Go lang* and *Go* are
   one keyword), plus capitalised phrase mining for the domain vocabulary a taxonomy can never
   enumerate. Importance rises with frequency, with appearing in the first third of the posting,
   and hits 1.0 if the term is in the job title.
2. **Model** (optional) — catches methodology and domain nouns, and marks the hard requirements.

Every keyword carries `in_master`: whether your résumé can actually back it. That flag is what
the tailoring prompt and the firewall are built on.

## Tailoring

The model returns a **structured** `TailoringPlan` — a summary, an experience ordering, bullet
rewrites addressed by index, dropped bullets, skill-group ordering — never free text. So it can be
validated, diffed, cached and replayed.

Cost control: the system prompt + profile + master résumé form a stable prefix marked for prompt
caching, so tailoring 40 jobs in a run pays for the profile once and the JD forty times.

With no API key, a deterministic ranker produces the same plan shape: bullets scored by weighted
keyword hits plus a bonus for containing a number, roles ordered by relevance and recency, skills
re-ordered so the JD's stack appears first. It is blunter, and it never invents anything either.

## The truthfulness firewall

Runs on the **output**, not on the model's promises — the deterministic path is audited the same
way. Three checks against the master résumé:

1. **Unsupported skills** — any canonical skill extractable from the tailored text but not from
   the master. Compared canonical-to-canonical, so "GitHub Actions" in the master supports "Git"
   in the output rather than raising a false alarm.
2. **Invented metrics** — every number in a rewritten bullet must appear in the original bullet or
   somewhere in the master.
3. **New employers or degrees** — must match the master exactly.

In `strict` mode (the default), an offending rewritten bullet is reverted to the original and a
summary containing an unsupported term is reset. In `review` the violations are surfaced and the
PDF still compiles. `off` disables it.

## Compilation

`tectonic` → `latexmk` → `pdflatex` → `xelatex` → remote LaTeX service (opt-in, off by default,
because it uploads your résumé) → **print the HTML template with the Chromium Playwright already
installed**. The last fallback means a user with no TeX install still gets a per-job PDF.

The HTML print runs in a worker thread on purpose: résumés are compiled while the apply loop
already holds a sync Playwright session, and the sync API refuses to start inside a thread that
already has a running event loop.

Page overflow is handled deterministically: count the pages in the PDF, drop the lowest-impact
bullets, re-render, re-compile.

## ATS lint

Scores the output 0-100 on the mechanical things that decide whether a parser reads it: contact
block present, sections present, weak opening verbs, share of quantified bullets, over-long
bullets, missing dates, keyword coverage, and characters that mangle parsers.

## Overleaf

Overleaf has no compile API, so the *source* is synced over the git bridge
(`https://git.overleaf.com/<project-id>`) with a token kept in the encrypted vault, and everything
is compiled locally. `jobwrapper resume overleaf-pull` clones or fast-forwards, finds the main
`.tex`, and imports it.
