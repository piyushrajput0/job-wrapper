/* Small helpers shared by every extension script. */
globalThis.JW = globalThis.JW || {};
JW.util = {
  esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  },
  clean(s) { return String(s ?? "").replace(/\s+/g, " ").trim(); },
  get(obj, path) {
    return String(path).split(".").reduce((n, p) => (n == null ? undefined : n[p]), obj);
  },
  host(url) { try { return new URL(url).hostname; } catch { return ""; } },
  sleep(ms) { return new Promise((r) => setTimeout(r, ms)); },
  debounce(fn, ms) {
    let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  },
  async resource(name) {
    const url = chrome.runtime.getURL(`shared/data/${name}`);
    const response = await fetch(url);
    return name.endsWith(".json") ? response.json() : response.text();
  },
};
