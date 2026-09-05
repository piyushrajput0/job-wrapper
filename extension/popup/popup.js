const el = (id) => document.getElementById(id);

chrome.runtime.sendMessage({ type: "ping-server" }, (result) => {
  el("dot").className = `dot ${result?.ok ? "on" : "off"}`;
  el("server").textContent = result?.ok ? "companion server connected" : "server offline (local mode)";
});

chrome.storage.local.get(["stats"]).then(({ stats }) => {
  el("filled").textContent = stats?.filled ?? 0;
  el("apps").textContent = stats?.applications ?? 0;
});

const send = async (type) => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab?.id) chrome.tabs.sendMessage(tab.id, { type });
  window.close();
};
el("panel").onclick = () => send("toggle-panel");
el("scan").onclick = () => send("scan");
el("options").onclick = () => chrome.runtime.openOptionsPage();
