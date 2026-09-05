# The plugin edition (V2)

A Manifest V3 extension that does everything V1 does *except* look for jobs — it works on the
career page you are already looking at, whoever runs it.

## Install

1. `jobwrapper ui` → **Settings** → copy the extension token
2. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select `extension/`
3. Open the extension's options page, paste the token, **Test connection**, **Sync profile**

No build step. The extension is plain ES modules and the knowledge base is copied in by
`scripts/sync_extension_data.py`.

## What you get on a page

| | |
|---|---|
| **Match** | score 0-100 with the reasons and the gaps, plus JD keywords coloured by whether your résumé can back them |
| **Tailor résumé** | a fresh PDF for this posting, with its ATS score and any truthfulness flags |
| **Scan form** | every control it found, what it will type, and what it refuses to answer |
| **Fill** | types the values with real events (so React and Vue register them) and highlights each field |
| **I submitted this** | records the application in the same tracker V1 writes to |

It **never presses submit**. That is not a setting.

## Files

```
extension/
  manifest.json              MV3, host permission for 127.0.0.1 only by default
  background/service_worker.js   downloads, options, server ping, profile sync
  content/
    detect.js      is this a posting / a form? JSON-LD first, then heuristics
    panel.js       the side panel, in a shadow root so no site can restyle it
    autofill.js    applies a plan to the DOM with native setters + real events
    main.js        wiring: launcher button, actions, offline fallback
    panel.css      just the launcher; the panel styles itself inside the shadow root
  shared/
    util.js storage.js api.js      helpers, chrome.storage, companion-server client
    catalog.js                     loads the shared JSON, computes profile values
    resolver.js                    the resolution cascade, mirroring resolver.py
    data/                          copied from src/jobwrapper/data - do not edit here
  options/  popup/  icons/
```

## Online and offline

With the companion server reachable, the extension gets the answer bank, the model-backed answer
engine and résumé tailoring. Without it, `shared/resolver.js` resolves the form against a profile
cached in `chrome.storage.local` using the same catalog, the same thresholds and the same
escalation rules — verified by `tests/test_parity.py`.

## Endpoints it uses

All under `/api/ext/`, all requiring `Authorization: Bearer <token>`:

| Endpoint | Purpose |
|---|---|
| `GET /ping` | connection test |
| `GET /profile` | sync the profile for offline use |
| `POST /analyze` | score this posting, store it as a job, return keywords |
| `POST /plan` | fields in → fill plan out (answer bank + model included) |
| `POST /tailor` | build a PDF for this posting |
| `POST /answer` | answer one awkward question |
| `POST /record` | log that you submitted |

## Known browser limits

- **File uploads cannot be automated.** `input[type=file]` is not scriptable for security
  reasons. The panel gives you the tailored PDF to download, and you pick it. V1 (Playwright)
  has no such restriction.
- Some sites' CSP blocks injecting the shared extractor into the page; the content script falls
  back to an isolated-world extractor with the same output shape.
- Sites inside cross-origin iframes are out of scope for the content script.

## Privacy

The extension talks to exactly two origins: the page you are on, and `127.0.0.1`. It has no
analytics, no remote config and no update channel beyond the unpacked folder on your disk.
`host_permissions` covers only localhost; access to career sites comes from the content script
match pattern, which you can narrow in `manifest.json` if you would rather list domains
explicitly.
