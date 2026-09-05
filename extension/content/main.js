/* Wiring: decide whether to show the launcher, then drive the panel's actions. */
globalThis.JW = globalThis.JW || {};
JW.main = {
  settings: null,

  async init() {
    if (window.top !== window) return;                       // main frame only
    this.settings = await JW.storage.settings();
    await JW.catalog.load();
    const isForm = JW.detect.isApplicationForm();
    const isPosting = JW.detect.isJobPosting();
    if (!isForm && !isPosting) return;

    this.ats = JW.catalog.detectATS();
    this.launcher = document.createElement("button");
    this.launcher.id = "jobwrapper-launcher";
    this.launcher.textContent = "JW";
    this.launcher.title = "Job Wrapper";
    this.launcher.onclick = () => JW.panel.toggle();
    document.documentElement.appendChild(this.launcher);

    JW.panel.set({ job: JW.detect.extractJob() });
    if (this.settings.autoAnalyze && isPosting) this.analyze(true);
  },

  msg(message, kind = "") { JW.panel.set({ message, messageKind: kind }); },

  async profile() {
    const { profile } = await JW.storage.get(["profile"]);
    if (profile) return profile;
    const fetched = await JW.api.profile();
    if (fetched && !fetched.__error) {
      await JW.storage.set({ profile: fetched.profile, profileSyncedAt: 1 });
      return fetched.profile;
    }
    return null;
  },

  async analyze(quiet = false) {
    const job = JW.detect.extractJob();
    JW.panel.set({ job });
    if (!quiet) this.msg('<span class="spin"></span> Analysing this posting…');
    const result = await JW.api.analyze({ ...job, ats: this.ats, use_llm: false });
    if (!result || result.__error) {
      if (!quiet) this.msg(result?.__error || "Companion server unreachable — offline mode.", "bad");
      return;
    }
    this.jobId = result.job_id;
    if (this.launcher) this.launcher.dataset.score = result.score;
    JW.panel.set({ analysis: result, message: "" });
    if (quiet && result.score >= 70) JW.panel.mount();
  },

  async tailor() {
    if (!this.jobId) await this.analyze(true);
    if (!this.jobId) return this.msg("Analyse the posting first.", "bad");
    this.msg('<span class="spin"></span> Tailoring your resume for this role…');
    const result = await JW.api.tailor({ job_id: this.jobId });
    if (!result || result.__error) return this.msg(result?.__error || "Tailoring failed.", "bad");
    JW.panel.set({ tailored: result, message: "Fresh resume built for this posting." , messageKind: "good"});
  },

  async download() {
    const path = JW.panel.state.tailored?.download;
    if (!path) return;
    const { serverUrl } = await JW.storage.get(["serverUrl"]);
    chrome.runtime.sendMessage({ type: "download", url: `${serverUrl}${path}` });
  },

  async scan() {
    this.msg('<span class="spin"></span> Reading the form…');
    const fields = await JW.detect.extractFields();
    if (!fields.length) return this.msg("No form fields found on this page.", "bad");

    const payload = {
      fields, url: location.href, ats: this.ats, job_id: this.jobId || "",
      company: JW.panel.state.job?.company || "",
      resume_path: JW.panel.state.tailored?.resume_path || "",
      use_llm: this.settings.useLLM,
    };
    let plan = await JW.api.plan(payload);
    if (!plan || plan.__error) {
      const profile = await this.profile();
      if (!profile) {
        return this.msg(`${plan?.__error || "Server unreachable"} — and no cached profile to fall
          back on. Open Settings and sync your profile once.`, "bad");
      }
      plan = JW.resolver.resolveForm(fields, profile, { ats: this.ats });
      this.msg(`Offline: resolved ${plan.fields.length} of ${fields.length} field(s) from the cached profile.`, "");
    } else {
      this.msg(`Resolved ${plan.fields.length} of ${fields.length} field(s).`, "good");
    }
    JW.panel.set({ plan });
    JW.panel.mount();
  },

  async fill() {
    const plan = JW.panel.state.plan;
    if (!plan?.fields?.length) return;
    if (this.settings.confirmBeforeFill
        && !confirm(`Fill ${plan.fields.length} field(s) on this page?\n\nJob Wrapper never presses submit — you review and submit yourself.`)) return;
    this.msg('<span class="spin"></span> Filling…');
    const results = await JW.autofill.apply(plan);
    const ok = results.filter((r) => r.ok).length;
    const failed = results.filter((r) => !r.ok);
    const uploads = failed.filter((r) => /file uploads/.test(r.error || ""));
    this.msg(`Filled ${ok} of ${results.length}. ${failed.length ? `${failed.length} left for you`
      + (uploads.length ? ` (including the resume upload)` : "") : "Review and submit when you are happy."}`,
      failed.length ? "" : "good");
    const stats = (await JW.storage.get(["stats"])).stats;
    await JW.storage.set({ stats: { ...stats, filled: stats.filled + ok } });
  },

  async record() {
    const job = JW.panel.state.job;
    const result = await JW.api.record({
      job_id: this.jobId || "", company: job?.company, title: job?.title, url: location.href,
      ats: this.ats, status: "submitted",
      resume_path: JW.panel.state.tailored?.resume_path || "",
      fields_filled: JW.panel.state.plan?.fields?.length || 0,
    });
    if (result && !result.__error) {
      const stats = (await JW.storage.get(["stats"])).stats;
      await JW.storage.set({ stats: { ...stats, applications: stats.applications + 1 } });
      this.msg("Recorded in your application tracker.", "good");
    } else {
      this.msg(result?.__error || "Could not reach the tracker.", "bad");
    }
  },
};

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "toggle-panel") JW.panel.toggle();
  if (message?.type === "scan") JW.main.scan();
});

if (document.readyState === "complete" || document.readyState === "interactive") {
  JW.main.init();
} else {
  document.addEventListener("DOMContentLoaded", () => JW.main.init());
}
