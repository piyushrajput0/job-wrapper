const FIELDS = ["serverUrl", "token"];
const TOGGLES = ["useServer", "useLLM", "autoAnalyze", "confirmBeforeFill"];
const DEFAULTS = { serverUrl: "http://127.0.0.1:8787", token: "", useServer: true, useLLM: true,
                   autoAnalyze: true, confirmBeforeFill: true };
const el = (id) => document.getElementById(id);

function status(message, kind = "") {
  const node = el("status");
  node.hidden = false;
  node.className = `status ${kind}`;
  node.textContent = message;
}

async function load() {
  const stored = await chrome.storage.local.get([...FIELDS, ...TOGGLES]);
  FIELDS.forEach((k) => { el(k).value = stored[k] ?? DEFAULTS[k]; });
  TOGGLES.forEach((k) => { el(k).checked = stored[k] ?? DEFAULTS[k]; });
}

el("save").onclick = async () => {
  const values = {};
  FIELDS.forEach((k) => { values[k] = el(k).value.trim(); });
  TOGGLES.forEach((k) => { values[k] = el(k).checked; });
  await chrome.storage.local.set(values);
  status("Saved.", "good");
};

el("test").onclick = async () => {
  await chrome.storage.local.set({ serverUrl: el("serverUrl").value.trim(), token: el("token").value.trim() });
  status("Testing…");
  chrome.runtime.sendMessage({ type: "ping-server" }, (result) => {
    if (result?.ok) status(`Connected. Profile: ${result.data.name || "(unnamed)"} · autonomy ${result.data.autonomy}.`, "good");
    else status(`Could not connect: ${result?.error || "unknown error"}`, "bad");
  });
};

el("sync").onclick = () => {
  status("Syncing…");
  chrome.runtime.sendMessage({ type: "sync-profile" }, (result) => {
    if (result?.ok) status(`Profile cached for offline filling (${result.name}).`, "good");
    else status(`Sync failed: ${result?.error || "unknown error"}`, "bad");
  });
};

load();
