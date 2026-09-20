# Reddit post — draft

## Short version (use this one)

**Title:** *I built an open-source tool that tailors your résumé to each job and fills the applications — would love people to try it and tell me what breaks*

I've been building Job Wrapper for a few months. It works for me, which is exactly the point
where I stop being able to find its bugs — so I'm looking for people to actually use it and
tell me how it went.

It pulls postings from 19 job boards, scores them against your profile, then for each job it
reads the description, rewrites your LaTeX résumé around its keywords, compiles a fresh PDF,
opens the form and fills it in.

**It does not press submit.** It fills everything, screenshots each step, and stops. You look at
it and send it yourself.

The part I care about is the truthfulness firewall: it can re-order and re-phrase what your
résumé already says, but it cannot add a skill, employer, degree or metric that isn't in there.
Every generated résumé is diffed against your master copy and unsupported claims get reverted
before a PDF exists. I built it that way because "let AI write your résumé" makes things you
can't defend in an interview.

Everything runs on your machine. Your résumé and profile never leave it — there's no account, no
server of mine, nothing to upload. Works with no API key at all (there's a deterministic
fallback), or point it at Ollama and it's fully local and free. Python + Playwright, MIT,
229 tests.

**What would help most: just try it and tell me what happened.** Point it at your own résumé and
see what it gets wrong — every template is different and mine is the only one it has really been
tested against. Last week alone it was reading the GitHub URL out of the template's own header
comment, mangling Indian phone numbers, filing a 10-point CGPA against a 4.0 scale, and
defaulting everyone's country to the US, which then quietly answers the work-authorisation
questions. All of those produce a *wrong value* rather than an error, so they're easy to miss.
There are certainly more.

Feedback of any kind is welcome — "the setup docs confused me here", "this felt sketchy",
"it crashed on Windows", "I don't think this should exist". Open an issue or just reply here.
If you feel like contributing code, brilliant, and if you'd rather just kick the tyres and say
what you thought, that's genuinely just as useful.

https://github.com/piyushrajput0/job-wrapper

---

## Long version


**Status:** the repo is public and its history has been scrubbed of personal data. Ready to post.

**Where to post:** r/Python (best fit — it is a Python project with tests and CI) ·
r/SideProject · r/opensource · r/coolgithubprojects · r/madeinindia.
Most subs cap self-promotion at one post a week and some require flair — check the sidebar.
Post once, then answer comments; do not cross-post all five on the same day.

---

## Title options

1. *I built a job-application tool that tailors your résumé per posting — and I'd really like help finishing it*
2. *After 200+ applications I automated the boring half. It works, it's MIT, and it needs other people's résumés to get good*
3. *[Open source] Job Wrapper — finds jobs, tailors your LaTeX résumé to each one, fills the forms. Looking for contributors*

---

## Body

Hey everyone,

I spent the last few months building **Job Wrapper**, and I've got it to the point where it
genuinely works for me — which is exactly the point where I need other people to break it.

**What it does:** it pulls postings from a bunch of job boards, de-duplicates and scores them
against your profile, then for each job it reads the description, pulls out the keywords,
re-tailors your LaTeX résumé around them, compiles a fresh PDF for that specific application,
opens the form and fills it in.

**What it doesn't do:** press submit. By default it fills everything, screenshots each step, and
stops. You look at it and submit yourself. There is an `auto` mode behind a daily cap and a
match-score floor, but the default assumes you want to see what went out under your name.

**The part I actually care about** is the truthfulness firewall. The tailor may re-order,
re-weight and re-phrase what your résumé already says. It may **not** add a skill, employer,
degree, date or metric that isn't in there. Every generated résumé is diffed against your master
copy and unsupported claims get reverted before a PDF is compiled — whether they came from the
model or the deterministic ranker. What it *will* do is surface things you already earned: if you
described Kafka in a bullet but never listed it under Skills, an ATS keyword scan can't see it,
so it gets promoted. A skill your résumé can't back gets refused, every time.

I built it that way because "just let the AI write your résumé" produces things you can't defend
in an interview, and I didn't want to ship that.

**Some details:**

- Python 3.11+, `uv`, Playwright. No Node, no build step.
- Everything runs locally. Your profile, your résumé, your applications — all in `~/.jobwrapper/`.
  Nothing is uploaded anywhere except the job boards you're applying to.
- **Works with no API key at all** — a deterministic ranker does the tailoring. If you do want a
  model, it supports 10 providers including Ollama, so it can be fully local and free.
- Two editions: a CLI + local web UI, and a Chrome extension for company career pages no
  aggregator indexes. A parity test asserts both resolve form fields identically.
- 229 tests, CI, MIT licensed.
- It deliberately does **not** scrape LinkedIn, Indeed or Glassdoor. Their terms forbid it and
  automating a logged-in session can get your account killed. The extension is the sanctioned way
  to work a page you opened yourself.

**Where I need help, honestly:**

The single highest-value thing anyone can do is **throw a résumé at it that it parses wrong.**
I've been testing against mine, and every new template I try breaks something new. Last week alone
I found it was reading the GitHub URL out of the template's own header comment (the sb2nov and
Jake's templates both ship `% Based off of: github.com/sb2nov/resume`, and it sorted first),
splitting an Indian mobile as `+918` plus a nine-digit remainder, filing an 8.64 CGPA against a 4.0 scale, and
defaulting everyone's country to the United States — which then quietly answers the
work-authorisation questions. Every one of those produces a *wrong value* rather than an error,
which is the kind that reaches an employer. There are certainly more.

Other things that would genuinely help:

- **A job source I haven't added.** Adapters are small and self-contained.
- **An ATS it can't fill yet.** Especially non-US ones — I've mostly tested against US and Indian
  postings.
- **Windows and Linux testing.** It's been road-tested almost entirely on macOS.
- **A field it asks you about that it should have known.** Teaching it a new field is a one-line
  edit, and both editions learn it at once.

Issues describing a bug you hit in the wild are just as welcome as code. If you fork it and never
send anything back, that's completely fine too — I'd rather it was useful to you.

**Repo:** https://github.com/piyushrajput0/job-wrapper

Happy to answer anything about how the tailoring or the form-filling works. And if you think the
whole idea is a bad one, I'd like to hear that too — better now than after someone's application
goes out wrong.

---

## Before you post — checklist

- [x] **Make the repo public.** Done.
- [x] **Scrub the git history.** Done - history rewritten, verified clean from a fresh clone.



- [ ] Check the README renders correctly on GitHub once it's public.
- [x] Add repo topics. Done.

- [ ] Consider turning on Issues templates and adding a `good first issue` label to a few things
      so the asks above have somewhere to land.
