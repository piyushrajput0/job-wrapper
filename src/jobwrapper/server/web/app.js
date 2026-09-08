/* Router, API client, and the profile page (which is the heart of the intake). */
(() => {
  const api = {
    async get(path) { const r = await fetch(path); if (!r.ok) throw new Error(await r.text()); return r.json(); },
    async send(method, path, body) {
      const r = await fetch(path, { method, headers: { "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body) });
      if (!r.ok) throw new Error((await r.text()).slice(0, 300));
      return r.status === 204 ? null : r.json();
    },
    put(path, body) { return this.send("PUT", path, body); },
    post(path, body) { return this.send("POST", path, body); },
    del(path) { return this.send("DELETE", path); },
  };

  const el = (id) => document.getElementById(id);
  const toast = (message, kind = "") => {
    const node = document.createElement("div");
    node.className = kind; node.innerHTML = message;
    el("toast").append(node);
    setTimeout(() => node.remove(), kind === "bad" ? 6500 : 2600);
  };

  const ICONS = {
    home: "M3 9l7-6 7 6v8a1 1 0 01-1 1h-4v-5H8v5H4a1 1 0 01-1-1z",
    user: "M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zm-6 7a6 6 0 0112 0",
    list: "M6 5h11M6 10h11M6 15h11M3 5h.01M3 10h.01M3 15h.01",
    send: "M3 10l14-6-6 14-2-6-6-2z",
    chat: "M4 4h12v9H8l-4 3z",
    file: "M5 2h7l4 4v12H5zM12 2v4h4",
    bolt: "M11 2L4 11h5l-1 7 7-9h-5z",
    gear: "M10 13a3 3 0 100-6 3 3 0 000 6zM10 1v3M10 16v3M3 10H1m18 0h-2M4.2 4.2l1.4 1.4m8.8 8.8l1.4 1.4M4.2 15.8l1.4-1.4m8.8-8.8l1.4-1.4",
  };
  const icon = (name) => `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6"
    stroke-linecap="round" stroke-linejoin="round"><path d="${ICONS[name] || ICONS.list}"/></svg>`;

  const ROUTES = [
    { id: "autopilot", label: "Autopilot", icon: "bolt", title: "Autopilot",
      subtitle: "Find, tailor and apply — one job at a time" },
    { id: "dashboard", label: "Dashboard", icon: "home", title: "Dashboard",
      subtitle: "Everything at a glance" },
    { id: "profile", label: "Profile", icon: "user", title: "Your profile",
      subtitle: "The single source of truth for every application answer" },
    { id: "jobs", label: "Jobs", icon: "list", title: "Jobs",
      subtitle: "Discovered, de-duplicated and scored against your profile" },
    { id: "applications", label: "Applications", icon: "send", title: "Applications",
      subtitle: "What was filled, what was flagged, what was submitted" },
    { id: "answers", label: "Answers", icon: "chat", title: "Answer bank",
      subtitle: "Questions the tool has learned so it never asks twice" },
    { id: "resume", label: "Resume", icon: "file", title: "Resume",
      subtitle: "Your master resume and how it is parsed" },
    { id: "settings", label: "Settings", icon: "gear", title: "Settings",
      subtitle: "Search, autonomy, caps, model and sources" },
  ];

  let state = { profile: null, schema: null, completeness: {}, section: null, dirty: false };

  /* -------------------------------------------------------------- profile page */
  async function renderProfile() {
    if (!state.schema) {
      const payload = await api.get("/api/schema");
      state.schema = payload.schema;
      state.completeness = payload.completeness;
    }
    state.profile = await api.get("/api/profile");
    const sections = state.schema.sections;
    state.section = state.section || sections[0].id;
    const section = sections.find((s) => s.id === state.section) || sections[0];

    el("view").innerHTML = `
      <div class="profile-layout">
        <div class="section-nav">${sections.map((s) => {
          const c = state.completeness[s.id] || { pct: 0 };
          return `<button data-section="${s.id}" class="${s.id === state.section ? "active" : ""}${
            c.pct >= 90 ? " done" : ""}">${Form.esc(s.title)}<span class="pct">${c.pct}%</span></button>`;
        }).join("")}</div>
        <div>
          <div class="banner info">Changes save automatically. Everything stays on this machine —
            the profile lives in <span class="mono">~/.jobwrapper/profile.json</span>.</div>
          <div id="section-body">${Form.renderSection(section, state.profile)}</div>
        </div>
      </div>`;
    wireProfile();
  }

  let saveTimer = null;
  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveProfile, 700);
  }

  async function saveProfile() {
    document.querySelectorAll("#section-body [data-path]").forEach((node) => {
      Form.readControl(node, state.profile);
    });
    try {
      const result = await api.put("/api/profile", state.profile);
      state.completeness = result.completeness;
      document.querySelectorAll(".section-nav button").forEach((button) => {
        const c = state.completeness[button.dataset.section];
        if (c) {
          button.querySelector(".pct").textContent = `${c.pct}%`;
          button.classList.toggle("done", c.pct >= 90);
        }
      });
      refreshSidebar();
      toast("Saved", "good");
    } catch (error) {
      toast(`Could not save: ${Form.esc(error.message)}`, "bad");
    }
  }

  function wireProfile() {
    document.querySelectorAll(".section-nav button").forEach((button) => {
      button.onclick = async () => { await saveProfile(); state.section = button.dataset.section; renderProfile(); };
    });
    const body = el("section-body");
    body.addEventListener("input", (event) => {
      const node = event.target.closest("[data-path]");
      if (node) scheduleSave();
      if (event.target.type === "checkbox") {
        const text = event.target.parentElement.querySelector(".muted");
        if (text && (text.textContent === "Yes" || text.textContent === "No"))
          text.textContent = event.target.checked ? "Yes" : "No";
      }
    });
    body.addEventListener("change", (event) => { if (event.target.closest("[data-path]")) scheduleSave(); });

    /* collapsible entries */
    body.querySelectorAll(".entry > header").forEach((header) => {
      header.onclick = (event) => {
        if (event.target.closest("button")) return;
        header.parentElement.classList.toggle("collapsed");
      };
    });

    /* tags */
    body.querySelectorAll(".tags").forEach((box) => {
      const input = box.querySelector("input");
      input.onkeydown = (event) => {
        if (event.key !== "Enter" && event.key !== ",") return;
        event.preventDefault();
        const value = input.value.trim().replace(/,$/, "");
        if (!value) return;
        const tag = document.createElement("span");
        tag.className = "tag";
        tag.innerHTML = `${Form.esc(value)}<button type="button">×</button>`;
        box.insertBefore(tag, input);
        input.value = "";
        scheduleSave();
      };
      box.onclick = (event) => {
        if (event.target.tagName === "BUTTON") { event.target.parentElement.remove(); scheduleSave(); }
      };
    });

    /* multi-select chips */
    body.querySelectorAll(".multi").forEach((box) => {
      box.onclick = (event) => {
        const chip = event.target.closest(".chip");
        if (!chip) return;
        chip.classList.toggle("on");
        scheduleSave();
      };
    });

    /* repeatable lists */
    body.querySelectorAll("[data-add]").forEach((button) => {
      button.onclick = async () => {
        await saveProfile();
        const path = button.dataset.add;
        const list = Form.get(state.profile, path) || [];
        list.push({});
        Form.set(state.profile, path, list);
        await api.put("/api/profile", state.profile);
        renderProfile();
      };
    });
    body.querySelectorAll("[data-remove]").forEach((button) => {
      button.onclick = async () => {
        await saveProfile();
        const repeat = button.closest("[data-repeat]");
        const path = repeat.dataset.repeat;
        const list = Form.get(state.profile, path) || [];
        list.splice(Number(button.dataset.remove), 1);
        await api.put("/api/profile", state.profile);
        renderProfile();
      };
    });
    body.querySelectorAll("[data-add-key]").forEach((button) => {
      button.onclick = async () => {
        await saveProfile();
        const input = el("new-country");
        const key = (input?.value || "").trim().toUpperCase();
        if (!key) return toast("Enter a country code first", "bad");
        const path = button.dataset.addKey;
        const mapping = Form.get(state.profile, path) || {};
        if (!mapping[key]) mapping[key] = { authorized_to_work: "yes", requires_sponsorship_now: "no",
                                            requires_sponsorship_future: "no" };
        Form.set(state.profile, path, mapping);
        await api.put("/api/profile", state.profile);
        renderProfile();
      };
    });
    body.querySelectorAll("[data-remove-key]").forEach((button) => {
      button.onclick = async () => {
        const repeat = button.closest("[data-repeat-map]");
        const mapping = Form.get(state.profile, repeat.dataset.repeatMap) || {};
        delete mapping[button.dataset.removeKey];
        await api.put("/api/profile", state.profile);
        renderProfile();
      };
    });
  }

  /* -------------------------------------------------------------- other pages */
  async function pollTask(id, label) {
    const start = Date.now();
    while (Date.now() - start < 30 * 60 * 1000) {
      const task = await api.get(`/api/tasks/${id}`);
      if (task.status !== "running") {
        if (task.status === "failed") toast(`${label} failed: ${Form.esc((task.error || "").split("\n")[0])}`, "bad");
        else toast(`${label} finished: ${Form.esc(JSON.stringify(task.result))}`, "good");
        return task;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
  }


  /* -------------------------------------------------------------- autopilot */
  let apTimer = null;

  function renderRun(task) {
    const live = el("ap-live");
    if (!live) return;
    live.hidden = false;
    const events = task.events || [];
    const last = events[events.length - 1] || {};
    const done = last.total ? `${last.index}/${last.total}` : "—";
    el("ap-count").textContent = last.total ? `job ${done}` : (task.progress || "starting…");
    el("ap-bar").style.width = last.total ? `${Math.round((last.index / last.total) * 100)}%` : "0%";
    el("ap-state").textContent = task.status === "running"
      ? (task.progress || "working…") : task.status;
    el("ap-log").innerHTML = events.slice(-40).map((e) => {
      const cls = e.status === "submitted" ? "good"
        : ["needs_input", "failed"].includes(e.status) ? "warn" : "";
      const who = e.company ? `<b>${Form.esc(e.company)}</b> · ${Form.esc(e.title || "")} — ` : "";
      return `<div class="${cls === "good" ? "r" : cls === "warn" ? "g" : "muted"}">
        <span class="muted">[${Form.esc(e.stage)}]</span> ${who}${Form.esc(e.message)}</div>`;
    }).join("");
    el("ap-log").scrollTop = el("ap-log").scrollHeight;

    const running = task.status === "running";
    if (el("ap-start")) el("ap-start").disabled = running;
    if (el("ap-start")) el("ap-start").textContent = running ? "Running…" : "Start run";
    if (el("ap-stop")) el("ap-stop").disabled = !running;

    if (!running && task.result) {
      const r = task.result;
      el("ap-result").hidden = false;
      el("ap-result-body").innerHTML = `
        <div class="grid stats" style="margin-bottom:12px">
          <div class="stat"><div class="k">Submitted</div><div class="v">${r.submitted}</div></div>
          <div class="stat"><div class="k">Ready for review</div><div class="v">${r.ready_for_review}</div></div>
          <div class="stat"><div class="k">Need you</div><div class="v">${r.needs_input}</div></div>
          <div class="stat"><div class="k">Résumés built</div><div class="v">${r.resumes_built}</div></div>
        </div>
        ${(r.applications || []).length ? `<table><tbody>${r.applications.map((a) => `<tr>
          <td>${Form.esc(a.title)}<div class="muted">${Form.esc(a.company)}</div></td>
          <td style="width:150px">${Views.statusPill(a.status)}</td>
          <td style="width:90px" class="muted">${a.fields_filled} fields</td>
          <td style="width:110px">${a.resume
            ? `<a href="/api/artifact?path=${encodeURIComponent(a.resume)}" target="_blank">résumé</a>` : ""}</td>
        </tr>`).join("")}</tbody></table>` : ""}
        <div class="toolbar" style="margin-top:12px">
          <a class="btn" href="#/applications">Open applications</a></div>`;
    }
  }

  async function pollRun() {
    try {
      const task = await api.get("/api/autopilot/current");
      if (task.status === "idle") return;
      renderRun(task);
      if (task.status !== "running") {
        clearInterval(apTimer); apTimer = null;
        toast(task.status === "failed"
          ? `Run failed: ${Form.esc((task.error || "").split("\n")[0])}`
          : "Run finished", task.status === "failed" ? "bad" : "good");
        refreshSidebar();
      }
    } catch { /* server restarting */ }
  }

  function wireAutopilot() {
    const start = el("ap-start");
    if (start) start.onclick = async () => {
      start.disabled = true;
      start.innerHTML = '<span class="spin"></span> Starting';
      try {
        await api.post("/api/autopilot", {
          limit: Number(el("ap-limit").value) || 5,
          autonomy: el("ap-autonomy").value,
          search: el("ap-search").checked,
          overleaf: el("ap-overleaf").checked,
        });
        toast("Run started — a browser window will open", "good");
        if (apTimer) clearInterval(apTimer);
        apTimer = setInterval(pollRun, 1500);
        pollRun();
      } catch (error) {
        toast(Form.esc(error.message), "bad");
        start.disabled = false; start.textContent = "Start run";
      }
    };
    const install = el("ap-install-browser");
    if (install) install.onclick = async () => {
      install.disabled = true;
      install.innerHTML = '<span class="spin"></span> Downloading';
      const task = await api.post("/api/setup/browser", {});
      const done = await pollTask(task.id, "Browser download");
      if (done?.result?.ok) { toast("Browser installed", "good"); render(); }
      else { install.disabled = false; install.textContent = "Try again"; }
    };

    const stop = el("ap-stop");
    if (stop) stop.onclick = async () => {
      await api.post("/api/autopilot/stop", {});
      toast("Stopping after the job in flight");
    };
    pollRun();
    if (!apTimer) apTimer = setInterval(pollRun, 2000);
  }

  async function wireSecrets() {
    const key = el("api-key");
    if (!key) return;
    const status = (message, kind) => {
      el("key-status").innerHTML = `<span class="pill ${kind}">${message}</span>`;
    };
    el("btn-save-key").onclick = async () => {
      if (!key.value.trim()) return toast("Paste a key first", "bad");
      try {
        const result = await api.put("/api/secrets", { anthropic_api_key: key.value.trim() });
        key.value = "";
        status(result.usable ? "key saved and in use" : "key saved", "good");
        toast("API key saved (encrypted)", "good");
      } catch (error) { toast(Form.esc(error.message), "bad"); }
    };
    el("btn-test-key").onclick = async (event) => {
      event.target.innerHTML = '<span class="spin"></span>';
      const result = await api.post("/api/secrets/test", {});
      event.target.textContent = "Test";
      if (result.ok) { status(`working — ${Form.esc(result.model)}`, "good"); toast("Key works", "good"); }
      else { status("not working", "bad"); toast(Form.esc(result.error || "failed"), "bad"); }
    };
    el("btn-clear-key").onclick = async () => {
      await api.put("/api/secrets", { anthropic_api_key: "" });
      status("no key — deterministic fallbacks", "warn");
      toast("Key removed", "good");
    };
  }

  function wireJobs(params) {
    const refresh = () => {
      const query = new URLSearchParams();
      const q = el("job-q").value.trim(); if (q) query.set("q", q);
      const min = el("job-min").value; if (min !== "0") query.set("min", min);
      const status = el("job-status").value; if (status) query.set("status", status);
      location.hash = `#/jobs${query.toString() ? `?${query}` : ""}`;
    };
    el("job-q").onchange = refresh;
    el("job-min").onchange = refresh;
    el("job-status").onchange = refresh;

    el("btn-search").onclick = async (event) => {
      event.target.disabled = true;
      event.target.innerHTML = '<span class="spin"></span> Searching';
      const task = await api.post("/api/search", {});
      toast("Search started across your enabled sources");
      await pollTask(task.id, "Search");
      render();
    };

    const picks = () => [...document.querySelectorAll(".pick:checked")].map((c) => c.dataset.id);
    const applyButton = el("btn-apply-selected");
    document.querySelectorAll(".pick").forEach((box) => {
      box.onclick = (event) => {
        event.stopPropagation();
        const n = picks().length;
        applyButton.disabled = !n;
        applyButton.textContent = n ? `Apply to ${n} selected` : "Apply to selected";
      };
    });
    applyButton.onclick = async () => {
      const ids = picks();
      if (!ids.length) return;
      if (!confirm(`Run the application flow for ${ids.length} job(s)?\n\nA browser window will open. At autonomy "review" nothing is submitted without you.`)) return;
      const task = await api.post("/api/apply", { job_ids: ids });
      toast("Application run started - watch the browser window");
      await pollTask(task.id, "Apply run");
      render();
    };

    document.querySelectorAll("tr.clickable").forEach((row) => {
      row.onclick = (event) => {
        if (event.target.closest("a,input,button")) return;
        const detail = document.querySelector(`[data-detail="${row.dataset.id}"]`);
        if (detail) detail.hidden = !detail.hidden;
      };
    });
    document.querySelectorAll("[data-apply]").forEach((button) => {
      button.onclick = async () => {
        const task = await api.post("/api/apply", { job_ids: [button.dataset.apply] });
        toast("Applying - a browser window will open");
        await pollTask(task.id, "Apply");
        render();
      };
    });
    document.querySelectorAll("[data-tailor]").forEach((button) => {
      button.onclick = async () => {
        button.innerHTML = '<span class="spin"></span> Tailoring';
        try {
          const result = await api.post("/api/resume/tailor", { job_id: button.dataset.tailor });
          const violations = result.violations.length
            ? `<br><b>${result.violations.length} truthfulness flag(s)</b>` : "";
          toast(`ATS score ${result.ats_score}/100 · keyword coverage ${Math.round(result.coverage * 100)}%${violations}`, "good");
        } catch (error) { toast(Form.esc(error.message), "bad"); }
        button.textContent = "Preview tailored resume";
      };
    });
    document.querySelectorAll("[data-hide]").forEach((button) => {
      button.onclick = async () => {
        await api.post(`/api/jobs/${button.dataset.hide}/status`, { status: "skipped" });
        render();
      };
    });
  }

  function wireApplications() {
    document.querySelectorAll("[data-review]").forEach((button) => {
      button.onclick = async () => {
        const id = button.dataset.review;
        button.innerHTML = '<span class="spin"></span> Opening';
        try {
          await api.post(`/api/applications/${id}/review`, {});
          toast("Browser opening — the form is being refilled for you", "good");
          button.outerHTML = `
            <button class="btn sm primary" data-submitted="${id}">I submitted it</button>
            <button class="btn sm" data-close="${id}">Close browser</button>`;
          document.querySelector(`[data-submitted="${id}"]`).onclick = async () => {
            await api.post(`/api/applications/${id}/review/close`, { submitted: true });
            toast("Recorded as submitted", "good");
            render();
          };
          document.querySelector(`[data-close="${id}"]`).onclick = async () => {
            await api.post(`/api/applications/${id}/review/close`, { submitted: false });
            render();
          };
        } catch (error) {
          toast(Form.esc(error.message), "bad");
          button.textContent = "Open & refill";
        }
      };
    });
  }

  function wireAnswers() {
    const filter = el("ans-q");
    if (filter) filter.oninput = () => {
      const needle = filter.value.toLowerCase();
      document.querySelectorAll("#ans-table tbody tr").forEach((row) => {
        row.hidden = !row.dataset.q.toLowerCase().includes(needle);
      });
    };
    document.querySelectorAll("[data-answer]").forEach((input) => {
      input.onchange = async () => {
        await api.post("/api/answers", { question: input.dataset.answer, answer: input.value,
          company: input.dataset.company || "" });
        toast("Answer updated", "good");
      };
    });
    document.querySelectorAll("[data-del]").forEach((button) => {
      button.onclick = async () => {
        await api.del(`/api/answers?question=${encodeURIComponent(button.dataset.del)}&company=${
          encodeURIComponent(button.dataset.company || "")}`);
        render();
      };
    });
  }

  function wireResume() {
    el("btn-import").onclick = async (event) => {
      const path = el("import-path").value.trim();
      if (!path) return toast("Give the path to your resume file", "bad");
      event.target.innerHTML = '<span class="spin"></span> Importing';
      try {
        const result = await api.post("/api/resume/import", { path, use_llm: el("import-llm").checked });
        toast(`Imported ${result.roles} role(s), ${result.education} education entr(ies), ${result.skill_groups} skill group(s)`, "good");
        render();
      } catch (error) { toast(Form.esc(error.message), "bad"); event.target.textContent = "Import"; }
    };
  }

  async function wireSettings() {
    const config = await api.get("/api/config");
    const split = (id) => el(id).value.split(",").map((s) => s.trim()).filter(Boolean);
    el("btn-save-config").onclick = async () => {
      Object.assign(config.search, {
        titles: split("s-titles"), exclude_titles: split("s-extitles"),
        keywords: split("s-keywords"), exclude_keywords: split("s-exkeywords"),
        locations: split("s-locations"), posted_within_days: Number(el("s-days").value),
        min_salary: el("s-salary").value ? Number(el("s-salary").value) : null,
        remote_only: el("s-remote").checked,
        require_sponsorship_friendly: el("s-sponsor").checked,
      });
      Object.assign(config.apply, {
        autonomy: el("a-autonomy").value, daily_cap: Number(el("a-daily").value),
        per_company_cap: Number(el("a-company").value), headless: el("a-headless").checked,
        auto_signup: el("a-signup").checked, generate_cover_letter: el("a-cover").checked,
        min_seconds_between_applications: Number(el("a-gap").value),
      });
      config.match.min_score_to_apply = Number(el("m-apply").value);
      Object.assign(config.resume, {
        truthfulness: el("r-truth").value, max_pages: Number(el("r-pages").value),
        engine: el("r-engine").value, overleaf_git_url: el("r-overleaf").value || null,
      });
      Object.assign(config.llm, {
        enabled: el("l-enabled").checked, model: el("l-model").value, effort: el("l-effort").value,
      });
      document.querySelectorAll("[data-src]").forEach((box) => {
        config.sources[Number(box.dataset.src)].enabled = box.checked;
      });
      try { await api.put("/api/config", config); toast("Settings saved", "good"); }
      catch (error) { toast(Form.esc(error.message), "bad"); }
    };
    el("btn-detect").onclick = async (event) => {
      const url = el("src-url").value.trim();
      if (!url) return;
      event.target.innerHTML = '<span class="spin"></span> Detecting';
      try {
        const found = await api.post("/api/sources/detect", { url, save: true });
        toast(`Found a ${found.ats} board for ${Form.esc(found.company)} and added it`, "good");
        render();
      } catch (error) { toast(Form.esc(error.message), "bad"); event.target.textContent = "Detect & add"; }
    };
    el("btn-copy-token").onclick = () => {
      navigator.clipboard.writeText(document.querySelector(".mono[readonly]").value);
      toast("Token copied", "good");
    };
  }

  /* -------------------------------------------------------------- shell */
  async function refreshSidebar() {
    try {
      const status = await api.get("/api/status");
      el("pct").textContent = `${status.profile_complete.pct}%`;
      el("pctbar").style.width = `${status.profile_complete.pct}%`;
      const counts = { jobs: status.jobs.total,
                       applications: Object.values(status.applications || {}).reduce((a, b) => a + b, 0) };
      document.querySelectorAll("#nav a").forEach((link) => {
        const id = link.dataset.route;
        const badge = link.querySelector(".count");
        if (badge) badge.textContent = counts[id] ?? "";
      });
    } catch { /* server still starting */ }
  }

  function parseHash() {
    const [path, query] = location.hash.replace(/^#\/?/, "").split("?");
    return { route: path || "dashboard", params: Object.fromEntries(new URLSearchParams(query || "")) };
  }

  async function render() {
    const { route, params } = parseHash();
    if (apTimer && route !== "autopilot") { clearInterval(apTimer); apTimer = null; }
    const meta = ROUTES.find((r) => r.id === route) || ROUTES[0];
    el("title").textContent = meta.title;
    el("subtitle").textContent = meta.subtitle;
    el("actions").innerHTML = route === "profile"
      ? '<button class="btn primary" id="btn-save-now">Save now</button>' : "";
    document.querySelectorAll("#nav a").forEach((link) =>
      link.classList.toggle("active", link.dataset.route === meta.id));

    el("view").innerHTML = '<div class="empty"><span class="spin"></span></div>';
    try {
      if (meta.id === "profile") { await renderProfile(); }
      else {
        el("view").innerHTML = await Views[meta.id](api, params);
        if (meta.id === "autopilot") wireAutopilot();
        if (meta.id === "jobs") wireJobs(params);
        if (meta.id === "applications") wireApplications();
        if (meta.id === "answers") wireAnswers();
        if (meta.id === "resume") wireResume();
        if (meta.id === "settings") { await wireSettings(); await wireSecrets(); }
      }
    } catch (error) {
      el("view").innerHTML = `<div class="empty"><h3>Something went wrong</h3>
        <p class="mono">${Form.esc(error.message)}</p></div>`;
    }
    const saveNow = el("btn-save-now");
    if (saveNow) saveNow.onclick = saveProfile;
    refreshSidebar();
  }

  function boot() {
    el("nav").innerHTML = ROUTES.map((r) =>
      `<a href="#/${r.id}" data-route="${r.id}">${icon(r.icon)}<span>${r.label}</span>
       <span class="count"></span></a>`).join("");
    const saved = localStorage.getItem("jw-theme");
    if (saved) document.documentElement.dataset.theme = saved;
    el("theme-toggle").onclick = () => {
      const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      localStorage.setItem("jw-theme", next);
    };
    window.addEventListener("hashchange", render);
    window.addEventListener("beforeunload", (event) => {
      if (saveTimer) { saveProfile(); }
    });
    render();
  }

  document.addEventListener("DOMContentLoaded", boot);
})();
