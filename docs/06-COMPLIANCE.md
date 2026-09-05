# Compliance, ethics and the lines this tool does not cross

A tool that applies to jobs on your behalf can very easily become a tool that spams employers,
misrepresents you, or gets your accounts banned. These are the constraints built into the code,
not just written down here.

## Hard limits in the code

| Limit | Where |
|---|---|
| Never solves a CAPTCHA, MFA prompt or identity check — pauses and hands you the browser | `apply/browser.py: needs_human`, `pause_for_human` |
| Never fabricates résumé content | `resume/tailor.py: _firewall`, `_repair` |
| Never auto-answers criminal-history questions | `data/field_catalog.json: escalate`, `question_patterns.json: escalate_always` |
| Never types an SSN, national ID, passport number, bank detail or DOB | `sensitive_never_fill` |
| Salary history defaults to "prefer not to disclose" | `Compensation.current_salary_disclosure` |
| EEO answers default to declining unless you opt in | `EEOInfo.share_eeo` |
| Marketing opt-in defaults to off | `Screening.marketing_opt_in` |
| Cookie banners: reject non-essential where offered | `browser.py: dismiss_cookie_banner` |
| Submits only at `autonomy: auto`, under a daily cap, a per-company cap and a score floor | `apply/runner.py: guardrail_block` |
| The extension never submits at all | `content/main.js` |
| Per-host request throttling and a real identifying User-Agent | `sources/base.py: HttpClient` |
| Credentials encrypted at rest, never logged, never printed | `vault.py` |
| The local API binds to 127.0.0.1 and the extension endpoints need a bearer token | `server/app.py` |

## Sources we do not scrape

LinkedIn, Indeed, Glassdoor, ZipRecruiter, Dice, Monster, Naukri. Their terms of service prohibit
automated collection, and driving a logged-in session through them risks the user's account.
The nineteen implemented sources are official, documented, public JSON feeds.

If you hold a legitimate partner API key for one of those platforms, the adapter interface in
`sources/base.py` is the place to add it.

## Accounts

Some ATSes (Workday, iCIMS, SuccessFactors) require an account before you can apply. The tool:

- signs in with credentials **you** supplied, held in an AES-256-GCM vault under a scrypt-derived
  key;
- when no account exists, generates a unique strong password, **pre-fills** the registration form
  and stops at the submit button — you press it — unless you explicitly set
  `apply.auto_signup: true` for yourself;
- never reuses a password across sites and never derives one from anything you already use.

## Truthfulness

Tailoring is legitimate: the same experience, described in the vocabulary of the posting, with the
most relevant evidence first. Fabrication is not. The firewall enforces the line mechanically —
new skills, new metrics, new employers and new degrees are detected in the *output* and reverted
in strict mode, no matter whether a model or the deterministic ranker produced them.

You are still the author of what you send. `review` mode exists so you read it.

## Rate and volume

Defaults: 15 applications a day, 3 per company, 45 seconds between applications, and a match-score
floor of 65. Mass-blasting produces worse outcomes for you and real cost for the people reading
the applications. Raise the caps knowingly.

## Data protection

Everything lives in `~/.jobwrapper/`. Nothing is uploaded anywhere except (a) the job boards you
are applying to, and (b) the Anthropic API, if you set a key — which receives your profile, your
master résumé and the job descriptions, and nothing else. Turn it off with `llm.enabled: false`
or `JOBWRAPPER_NO_LLM=1` and the tool keeps working on its deterministic paths.

The remote LaTeX compile service is **off by default** precisely because it would upload your
résumé to a third party.

## Jurisdictional notes the tool respects

- **Ban-the-Box**: conviction questions are unlawful pre-offer in many places. Always escalated.
- **Salary-history bans** (CA, NY, WA, CO, MA, IL, NJ and many cities): the field still appears on
  forms; the default answer declines.
- **EEO / CC-305**: voluntary, cannot lawfully affect the decision, and defaults to declining.
- **GDPR**: consent checkboxes are recognised as their own field type with a retention preference.

## If you are an employer reading this

The tool identifies itself in its User-Agent, throttles per host, respects application caps, and
does not attempt to defeat any bot-detection measure. If you would rather it did not touch your
site, block the User-Agent `jobwrapper/0.1` and it will stop.
