/* Service worker: downloads, options, and the toolbar action. */
chrome.runtime.onInstalled.addListener(async () => {
  const stored = await chrome.storage.local.get(["serverUrl"]);
  if (!stored.serverUrl) {
    await chrome.storage.local.set({ serverUrl: "http://127.0.0.1:8787" });
    chrome.runtime.openOptionsPage();
  }
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.type === "open-options") { chrome.runtime.openOptionsPage(); return; }
  if (message?.type === "download" && message.url) {
    chrome.downloads.download({ url: message.url, saveAs: true });
    return;
  }
  if (message?.type === "ping-server") {
    (async () => {
      const { serverUrl, token } = await chrome.storage.local.get(["serverUrl", "token"]);
      try {
        const response = await fetch(`${serverUrl}/api/ext/ping`, {
          headers: { authorization: `Bearer ${token}` } });
        respond(response.ok ? { ok: true, data: await response.json() }
          : { ok: false, error: `${response.status} ${await response.text()}` });
      } catch (error) {
        respond({ ok: false, error: error.message });
      }
    })();
    return true;                                  // keep the channel open for the async reply
  }
  if (message?.type === "sync-profile") {
    (async () => {
      const { serverUrl, token } = await chrome.storage.local.get(["serverUrl", "token"]);
      try {
        const response = await fetch(`${serverUrl}/api/ext/profile`, {
          headers: { authorization: `Bearer ${token}` } });
        if (!response.ok) return respond({ ok: false, error: `${response.status}` });
        const payload = await response.json();
        await chrome.storage.local.set({ profile: payload.profile, profileSyncedAt: 1 });
        respond({ ok: true, name: payload.profile?.identity?.legal_first_name || "" });
      } catch (error) { respond({ ok: false, error: error.message }); }
    })();
    return true;
  }
});
