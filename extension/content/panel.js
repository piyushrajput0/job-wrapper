/* The side panel. Lives in a shadow root so no career site can restyle it and it cannot
   restyle the career site. */
globalThis.JW = globalThis.JW || {};
JW.panel = {
  root: null, shadow: null, state: { job: null, analysis: null, plan: null, tailored: null,
                                     busy: false, message: "" },

  css: `
  :host { all: initial; }
  * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif; }
  .wrap { position: fixed; top: 0; right: 0; bottom: 0; width: 396px; background: #0f1115;
    color: #e8ecf3; box-shadow: -12px 0 40px rgba(0,0,0,.4); display: flex; flex-direction: column;
    font-size: 13.5px; line-height: 1.5; }
  header { display: flex; align-items: center; gap: 10px; padding: 14px 16px;
    border-bottom: 1px solid #262d3b; }
  .logo { width: 26px; height: 26px; border-radius: 8px; background: linear-gradient(135deg,#5b8cff,#9d6bff);
    display: grid; place-items: center; font-weight: 700; font-size: 12px; color: #fff; }
  header b { font-size: 14px; } header .sub { color: #6f7b91; font-size: 11.5px; }
  header .x { margin-left: auto; background: none; border: 0; color: #6f7b91; font-size: 20px;
    cursor: pointer; line-height: 1; }
  .body { flex: 1; overflow-y: auto; padding: 14px 16px; }
  .card { background: #151922; border: 1px solid #262d3b; border-radius: 11px; padding: 13px; margin-bottom: 11px; }
  .card h4 { margin: 0 0 6px; font-size: 12.5px; text-transform: uppercase; letter-spacing: .06em; color: #a4aec1; }
  .row { display: flex; gap: 8px; align-items: center; }
  .btn { flex: 1; padding: 9px 12px; border-radius: 9px; border: 1px solid #262d3b; background: #1b202b;
    color: #e8ecf3; cursor: pointer; font-weight: 600; font-size: 13px; }
  .btn:hover { border-color: #5b8cff; color: #7aa2ff; }
  .btn.primary { background: #5b8cff; border-color: #5b8cff; color: #fff; }
  .btn.primary:hover { background: #7aa2ff; color: #fff; }
  .btn:disabled { opacity: .5; cursor: not-allowed; }
  .score { font-size: 30px; font-weight: 700; }
  .score.hi { color: #3fb984; } .score.mid { color: #e0a33e; } .score.lo { color: #6f7b91; }
  .muted { color: #6f7b91; } .good { color: #3fb984; } .warn { color: #e0a33e; } .bad { color: #e05f5f; }
  .kw { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 8px; }
  .kw span { padding: 2px 8px; border-radius: 99px; font-size: 11.5px; background: #1b202b; color: #a4aec1; }
  .kw span.have { background: rgba(63,185,132,.16); color: #3fb984; }
  .kw span.gap { background: rgba(224,95,95,.14); color: #e05f5f; }
  ul.reasons { margin: 6px 0 0; padding-left: 16px; font-size: 12.5px; color: #a4aec1; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  td { padding: 6px 4px; border-bottom: 1px solid #1b202b; vertical-align: top; }
  td.q { color: #a4aec1; width: 45%; }
  td input { width: 100%; background: #0f1115; border: 1px solid #262d3b; color: #e8ecf3;
    border-radius: 6px; padding: 4px 6px; font-size: 12.5px; }
  .flag { color: #e0a33e; font-size: 11px; }
  .foot { border-top: 1px solid #262d3b; padding: 12px 16px; display: flex; gap: 8px; }
  .msg { font-size: 12.5px; padding: 8px 10px; border-radius: 8px; background: #1b202b;
    border-left: 3px solid #5b8cff; margin-bottom: 10px; }
  .msg.bad { border-left-color: #e05f5f; } .msg.good { border-left-color: #3fb984; }
  .spin { display: inline-block; width: 12px; height: 12px; border: 2px solid #262d3b;
    border-top-color: #5b8cff; border-radius: 50%; animation: s .7s linear infinite; }
  @keyframes s { to { transform: rotate(360deg); } }
  a { color: #7aa2ff; }`,

  mount() {
    if (this.root) return;
    this.root = document.createElement("div");
    this.root.id = "jobwrapper-root";
    this.shadow = this.root.attachShadow({ mode: "open" });
    document.documentElement.appendChild(this.root);
    this.render();
  },
  unmount() { this.root?.remove(); this.root = null; },
  toggle() { this.root ? this.unmount() : this.mount(); },
  set(patch) { Object.assign(this.state, patch); if (this.root) this.render(); },

  render() {
    const s = this.state;
    const esc = JW.util.esc;
    const analysis = s.analysis;
    const scoreClass = analysis ? (analysis.score >= 75 ? "hi" : analysis.score >= 55 ? "mid" : "lo") : "lo";
    const plan = s.plan;

    this.shadow.innerHTML = `<style>${this.css}</style>
    <div class="wrap">
      <header>
        <div class="logo">JW</div>
        <div><b>Job Wrapper</b><div class="sub">${esc(s.job?.company || JW.util.host(location.href))}</div></div>
        <button class="x" id="close">×</button>
      </header>
      <div class="body">
        ${s.message ? `<div class="msg ${s.messageKind || ""}">${s.message}</div>` : ""}
        <div class="card">
          <h4>This posting</h4>
          <div><b>${esc(s.job?.title || "—")}</b></div>
          <div class="muted">${esc(s.job?.company || "")}${s.job?.location ? ` · ${esc(s.job.location)}` : ""}</div>
          <div class="row" style="margin-top:10px">
            <button class="btn" id="analyze">${analysis ? "Re-analyse" : "Analyse fit"}</button>
            <button class="btn" id="tailor">Tailor resume</button>
          </div>
        </div>

        ${analysis ? `<div class="card">
          <h4>Match</h4>
          <div class="row"><div class="score ${scoreClass}">${analysis.score}</div>
            <div class="muted">out of 100</div></div>
          <ul class="reasons">${(analysis.reasons || []).slice(0, 5).map((r) => `<li class="good">${esc(r)}</li>`).join("")}
            ${(analysis.gaps || []).slice(0, 4).map((g) => `<li class="warn">${esc(g)}</li>`).join("")}</ul>
          ${(analysis.keywords || []).length ? `<div class="kw">${analysis.keywords.slice(0, 18).map((k) =>
            `<span class="${k.in_master ? "have" : "gap"}">${esc(k.term)}</span>`).join("")}</div>` : ""}
        </div>` : ""}

        ${s.tailored ? `<div class="card"><h4>Tailored resume</h4>
          <div>ATS score <b>${s.tailored.ats_score}</b>/100 · coverage ${Math.round((s.tailored.coverage || 0) * 100)}%</div>
          ${(s.tailored.violations || []).length ? `<div class="warn" style="margin-top:6px">
            ${s.tailored.violations.length} truthfulness flag(s) — nothing unsupported was added</div>` : ""}
          <div class="muted" style="margin-top:6px;word-break:break-all">${esc(s.tailored.resume_path || "")}</div>
          <div class="row" style="margin-top:9px">
            <button class="btn" id="download">Download PDF</button>
            <button class="btn" id="copy-path">Copy path</button></div>
          <div class="muted" style="margin-top:6px;font-size:11.5px">
            Browsers will not let an extension attach a file for you — download it, then pick it in the form.</div>
        </div>` : ""}

        <div class="card">
          <h4>Application form</h4>
          ${plan ? `
            <div class="muted">${plan.fields.length} field(s) ready${plan.unresolved?.length
              ? `, ${plan.unresolved.length} need you` : ""}${plan.blocking?.length
              ? `, ${plan.blocking.length} blocked` : ""}</div>
            <table>${plan.fields.map((f, i) => `<tr>
              <td class="q">${esc(f.question)}${f.needs_review ? ' <span class="flag">check</span>' : ""}</td>
              <td><input data-i="${i}" value="${esc(f.value)}"></td></tr>`).join("")}</table>
            ${(plan.blocking || []).length ? `<div class="msg bad" style="margin-top:9px">
              ${plan.blocking.map((b) => esc(b)).join("<br>")}</div>` : ""}
            ${(plan.unresolved || []).length ? `<div class="muted" style="margin-top:8px">
              Not answered: ${plan.unresolved.slice(0, 6).map((u) => esc(u.label || u.name)).join(", ")}</div>` : ""}
          ` : `<div class="muted">Scan the page to see what can be filled.</div>`}
          <div class="row" style="margin-top:10px">
            <button class="btn" id="scan">${plan ? "Re-scan" : "Scan form"}</button>
            <button class="btn primary" id="fill" ${plan && plan.fields.length ? "" : "disabled"}>Fill</button>
          </div>
        </div>
      </div>
      <div class="foot">
        <button class="btn" id="options">Settings</button>
        <button class="btn" id="record">I submitted this</button>
      </div>
    </div>`;

    const on = (id, fn) => { const node = this.shadow.getElementById(id); if (node) node.onclick = fn; };
    on("close", () => this.unmount());
    on("analyze", () => JW.main.analyze());
    on("tailor", () => JW.main.tailor());
    on("scan", () => JW.main.scan());
    on("fill", () => JW.main.fill());
    on("options", () => chrome.runtime.sendMessage({ type: "open-options" }));
    on("record", () => JW.main.record());
    on("download", () => JW.main.download());
    on("copy-path", () => navigator.clipboard.writeText(this.state.tailored?.resume_path || ""));
    this.shadow.querySelectorAll("input[data-i]").forEach((input) => {
      input.onchange = () => { this.state.plan.fields[Number(input.dataset.i)].value = input.value; };
    });
  },
};
