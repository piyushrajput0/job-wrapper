/* Companion-server client. Every call degrades to null so the extension still works offline. */
globalThis.JW = globalThis.JW || {};
JW.api = {
  async call(path, { method = "GET", body = null } = {}) {
    const { serverUrl, token, useServer } = await JW.storage.get(["serverUrl", "token", "useServer"]);
    if (!useServer) return null;
    try {
      const response = await fetch(`${serverUrl}${path}`, {
        method,
        headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        const text = await response.text();
        return { __error: `${response.status}: ${text.slice(0, 200)}` };
      }
      return response.json();
    } catch (error) {
      return { __error: `cannot reach the companion server (${error.message}). Start it with \`jobwrapper ui\`.` };
    }
  },
  ping() { return this.call("/api/ext/ping"); },
  profile() { return this.call("/api/ext/profile"); },
  analyze(job) { return this.call("/api/ext/analyze", { method: "POST", body: job }); },
  plan(payload) { return this.call("/api/ext/plan", { method: "POST", body: payload }); },
  tailor(payload) { return this.call("/api/ext/tailor", { method: "POST", body: payload }); },
  answer(payload) { return this.call("/api/ext/answer", { method: "POST", body: payload }); },
  record(payload) { return this.call("/api/ext/record", { method: "POST", body: payload }); },
};
