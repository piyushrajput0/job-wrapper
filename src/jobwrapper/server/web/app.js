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

  /* ---------------------------------------------------------------- resume */
  function wireResume() {
    const status = (message, tone) => {
      const box = el("import-status");
      if (box) box.innerHTML = tone === "bad"
        ? `<span style="color:var(--bad)">${Form.esc(message)}</span>`
        : Form.esc(message);
    };

    const chooser = el("import-file");
    const choose = el("btn-choose");
    if (choose && chooser) {
      choose.onclick = () => chooser.click();
      chooser.onchange = async () => {
        const file = chooser.files && chooser.files[0];
        if (!file) return;
        status(`Uploading ${file.name}…`);
        try {
          const buffer = await file.arrayBuffer();
          // chunked so a multi-MB PDF does not blow the argument limit
          const bytes = new Uint8Array(buffer);
          let binary = "";
          for (let i = 0; i < bytes.length; i += 0x8000)
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          const saved = await api.post("/api/resume/upload",
            { name: file.name, content: btoa(binary) });
          el("import-path").value = saved.path;
          status(`${file.name} uploaded — now click Import.`);
        } catch (error) {
          status(error.message, "bad");
        }
      };
    }

    const importButton = el("btn-import");
    if (importButton) importButton.onclick = async () => {
      const path = el("import-path").value.trim();
      if (!path) return status("Choose a file, or paste its path.", "bad");
      importButton.disabled = true;
      status("Parsing…");
      try {
        const out = await api.post("/api/resume/import", {
          path,
          use_llm: el("import-llm").checked,
          fill_profile: el("import-fill").checked,
        });
        const filled = out.profile_fields_filled;
        const summary = `Parsed ${out.roles} role(s), ${out.education} education entr(ies), `
          + `${out.skill_groups} skill group(s)`
          + (el("import-fill").checked ? ` · filled ${filled} profile field(s)` : "");
        // the page shows what was parsed, so it has to be rebuilt, and the sidebar counts
        // and the profile form both changed underneath us - report after, or the fresh
        // DOM throws the message away
        await render();
        status(summary);
      } catch (error) {
        status(error.message, "bad");
      } finally {
        importButton.disabled = false;
      }
    };

    const renderFill = (result, applied) => {
      const box = el("fill-preview");
      if (!box) return;
      const rows = (result.changes || []).map((c) =>
        `<tr><td>${Form.esc(c.label || c.path)}</td>
             <td class="mono">${Form.esc(String(c.proposed ?? ""))}</td></tr>`).join("");
      box.innerHTML = rows
        ? `<p class="muted" style="margin:10px 0 6px">${applied
            ? `Filled ${result.changes.length} field(s).`
            : `${result.changes.length} field(s) would be filled`}${
            result.skipped && result.skipped.length
              ? ` · ${result.skipped.length} left alone because you already answered them` : ""}</p>
           <table class="table"><thead><tr><th>Field</th><th>From your résumé</th></tr></thead>
           <tbody>${rows}</tbody></table>`
        : `<p class="muted" style="margin:10px 0 0">Nothing new to fill — your profile already
           answers everything this résumé does.</p>`;
    };

    const preview = el("btn-preview-fill");
    if (preview) preview.onclick = async () => {
      try {
        renderFill(await api.post("/api/profile/from-resume",
          { apply: false, overwrite: el("fill-overwrite").checked }), false);
      } catch (error) { status(error.message, "bad"); }
    };

    const applyFill = el("btn-apply-fill");
    if (applyFill) applyFill.onclick = async () => {
      applyFill.disabled = true;
      try {
        const result = await api.post("/api/profile/from-resume",
          { apply: true, overwrite: el("fill-overwrite").checked });
        renderFill(result, true);
        refreshSidebar();
      } catch (error) {
        status(error.message, "bad");
      } finally {
        applyFill.disabled = false;
      }
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
      // provider and model belong to the AI model card, which saves itself
      Object.assign(config.llm, {
        enabled: el("l-enabled").checked, effort: el("l-effort").value,
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

  async function wireSecrets() {
    const providerSelect = el("ai-provider");
    if (!providerSelect) return;
    const catalogue = await api.get("/api/providers");
    const byId = Object.fromEntries(catalogue.providers.map((p) => [p.id, p]));
    const status = (message, kind) => {
      el("ai-status").innerHTML = `<span class="pill ${kind}">${message}</span>`;
    };

    async function loadModels(providerId, selected) {
      const select = el("ai-model");
      select.innerHTML = "<option>loading…</option>";
      let models = byId[providerId]?.models || [];
      try {
        const live = await api.get(`/api/providers/${providerId}/models`);
        if (live.models?.length) models = live.models;
      } catch { /* fall back to the bundled list */ }
      const want = selected || byId[providerId]?.default_model;
      select.innerHTML = models.map((m) =>
        `<option value="${Form.esc(m)}"${m === want ? " selected" : ""}>${Form.esc(m)}</option>`).join("");
      if (want && !models.includes(want)) {
        select.insertAdjacentHTML("afterbegin",
          `<option value="${Form.esc(want)}" selected>${Form.esc(want)} (current)</option>`);
      }
    }

    function paintProvider(providerId) {
      const provider = byId[providerId] || {};
      el("ai-key-field").style.display = provider.needs_key ? "" : "none";
      el("ai-provider-note").textContent = provider.notes || "";
      el("ai-key-help").innerHTML = provider.needs_key
        ? `Get one at <a href="${Form.esc(provider.key_url)}" target="_blank" rel="noopener">${
            Form.esc((provider.key_url || "").replace(/^https?:\/\//, ""))}</a>`
        : "";
    }

    paintProvider(providerSelect.value);
    await loadModels(providerSelect.value, catalogue.current.model);

    providerSelect.onchange = async () => {
      paintProvider(providerSelect.value);
      await loadModels(providerSelect.value, null);
    };
    el("ai-refresh").onclick = async (event) => {
      event.target.textContent = "…";
      await loadModels(providerSelect.value, el("ai-model").value);
      event.target.textContent = "↻";
    };

    el("ai-save").onclick = async () => {
      const body = {
        provider: providerSelect.value,
        model: el("ai-model-custom").value.trim() || el("ai-model").value,
        api_key: el("ai-key").value.trim(),
      };
      try {
        const result = await api.put("/api/secrets", body);
        el("ai-key").value = "";
        status(result.usable ? `ready · ${result.model}` : "saved, but no key yet",
               result.usable ? "good" : "warn");
        toast(`Using ${byId[result.provider]?.label || result.provider} · ${result.model}`, "good");
      } catch (error) { toast(Form.esc(error.message), "bad"); }
    };

    el("ai-test").onclick = async (event) => {
      event.target.innerHTML = '<span class="spin"></span>';
      const result = await api.post("/api/secrets/test", {});
      event.target.textContent = "Test it";
      if (result.ok) {
        status(`working · ${Form.esc(result.model)}`, "good");
        toast(`${Form.esc(result.provider)} replied: ${Form.esc(result.reply)}`, "good");
      } else {
        status("not working", "bad");
        toast(Form.esc(result.error || "failed"), "bad");
      }
    };

    el("ai-clear").onclick = async () => {
      await api.put("/api/secrets", { provider: providerSelect.value, clear: true });
      status("key removed", "warn");
      toast("Key removed", "good");
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
