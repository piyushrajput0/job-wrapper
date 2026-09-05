/* chrome.storage wrapper: settings, the cached profile, and per-page state. */
globalThis.JW = globalThis.JW || {};
JW.storage = {
  DEFAULTS: {
    serverUrl: "http://127.0.0.1:8787",
    token: "",
    autoAnalyze: true,
    useServer: true,
    useLLM: true,
    confirmBeforeFill: true,
    neverSubmit: true,
    profile: null,
    profileSyncedAt: 0,
    stats: { filled: 0, applications: 0 },
  },
  async get(keys) {
    const wanted = keys || Object.keys(this.DEFAULTS);
    const stored = await chrome.storage.local.get(wanted);
    const out = {};
    (Array.isArray(wanted) ? wanted : [wanted]).forEach((k) => {
      out[k] = stored[k] === undefined ? this.DEFAULTS[k] : stored[k];
    });
    return out;
  },
  async set(values) { await chrome.storage.local.set(values); },
  async settings() { return this.get(); },
};
