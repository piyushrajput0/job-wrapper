/* Loads the shared knowledge base that V1 also uses, and computes profile values locally. */
globalThis.JW = globalThis.JW || {};
JW.catalog = {
  data: null,
  async load() {
    if (this.data) return this.data;
    const [fields, ats, patterns] = await Promise.all([
      JW.util.resource("field_catalog.json"),
      JW.util.resource("ats_maps.json"),
      JW.util.resource("question_patterns.json"),
    ]);
    this.data = {
      version: fields.version,
      fields: fields.fields,
      byKey: Object.fromEntries(fields.fields.map((f) => [f.key, f])),
      optionSynonyms: fields.option_synonyms,
      sensitive: fields.sensitive_never_fill,
      humanSignals: fields.human_required_signals,
      ats: ats.ats,
      patterns,
    };
    return this.data;
  },

  detectATS(url = location.href, html = document.documentElement.outerHTML.slice(0, 20000)) {
    const haystack = `${url}\n${html}`.toLowerCase();
    for (const [name, spec] of Object.entries(this.data.ats)) {
      if (name === "generic") continue;
      const detect = spec.detect || {};
      if ((detect.url || []).some((t) => url.toLowerCase().includes(t.toLowerCase()))) return name;
      if ((detect.text || []).some((t) => haystack.includes(t.toLowerCase()))) return name;
      if ((detect.dom || []).some((sel) => { try { return document.querySelector(sel); } catch { return false; } })) return name;
    }
    return "generic";
  },

  isSensitive(question) {
    const q = question.toLowerCase();
    return this.data.sensitive.some((t) => q.includes(t));
  },
  needsHuman(text) {
    const t = text.toLowerCase();
    return this.data.humanSignals.find((s) => t.includes(s))
      || this.data.patterns.escalate_always.find((s) => t.includes(s))
      || null;
  },

  /* profile -> value, mirroring autofill/catalog.py for the offline path */
  valueFor(key, profile, context = {}) {
    const spec = this.data.byKey[key];
    if (!spec || !profile) return "";
    const g = (p) => JW.util.get(profile, p);
    const yn = { yes: "Yes", no: "No", prefer_not_to_say: "Prefer not to say" };
    const edu = (profile.education || [])[0] || {};
    const exp = (profile.experience || []).find((e) => e.currently_employed)
      || (profile.experience || [])[0] || {};
    const auth = (profile.work_authorization?.by_country || {})[
      (profile.address?.country_code || "US").toUpperCase()] || {};
    const comp = profile.preferences?.compensation || {};
    const computed = {
      full_name: [profile.identity?.preferred_name || profile.identity?.legal_first_name,
                  profile.identity?.legal_last_name].filter(Boolean).join(" "),
      location_city_state_country: [profile.address?.city,
        profile.address?.state_code || profile.address?.state,
        profile.address?.country].filter(Boolean).join(", "),
      today: new Date().toISOString().slice(0, 10),
      work_authorized: yn[auth.authorized_to_work || "yes"],
      requires_sponsorship: (auth.requires_sponsorship_now === "yes"
        || auth.requires_sponsorship_future === "yes") ? "Yes" : "No",
      visa_status: auth.status || auth.visa_type || "",
      permanent_resident: yn[auth.permanent_resident || "no"],
      school: edu.institution || "",
      degree: edu.degree_name || edu.degree_level || "",
      field_of_study: edu.field_of_study || "",
      minor: edu.minor || "",
      gpa: edu.gpa || "",
      gpa_scale: edu.gpa_scale || "",
      education_start: edu.start_date || "",
      education_end: edu.end_date || edu.expected_graduation || "",
      currently_attending: edu.currently_attending ? "Yes" : "No",
      current_company: profile.current_company || exp.company || "",
      current_title: profile.current_title || exp.title || "",
      years_experience: String(profile.years_of_experience || ""),
      employment_start: exp.start_date || "",
      employment_end: exp.end_date || "",
      reason_for_leaving: exp.reason_for_leaving || "",
      may_contact_employer: yn[exp.may_contact || "no"],
      supervisor_name: exp.supervisor_name || "",
      desired_salary: comp.desired_base_min && comp.desired_base_max
        ? `$${Number(comp.desired_base_min).toLocaleString()} - $${Number(comp.desired_base_max).toLocaleString()}`
        : (comp.desired_base_min ? `$${Number(comp.desired_base_min).toLocaleString()}` : "Negotiable"),
      current_salary: comp.current_salary_disclosure === "disclose"
        ? String(comp.current_salary || "") : "Prefer not to disclose",
      hourly_rate: String(comp.hourly_rate || ""),
      earliest_start_date: profile.preferences?.earliest_start_date || "Immediately",
      notice_period: profile.preferences?.notice_period_weeks
        ? `${profile.preferences.notice_period_weeks} weeks` : "None",
      willing_to_relocate: yn[profile.preferences?.willing_to_relocate || "no"],
      relocation_assistance: yn[profile.preferences?.needs_relocation_assistance || "no"],
      work_model_preference: (profile.preferences?.work_model || "remote").replace(/^./, (c) => c.toUpperCase()),
      commute_ok: "Yes",
      willing_to_travel: profile.preferences?.willing_to_travel_percent ? "Yes" : "No",
      employment_type_pref: (profile.preferences?.employment_types || ["Full-time"])[0],
      criminal_history: "",
      eeo_gender: profile.eeo?.share_eeo ? profile.eeo.gender : "Decline To Self Identify",
      eeo_race: profile.eeo?.share_eeo ? profile.eeo.race_ethnicity : "Decline To Self Identify",
      eeo_veteran: profile.eeo?.share_eeo ? profile.eeo.veteran_status : "I don't wish to answer",
      eeo_disability: profile.eeo?.share_eeo ? profile.eeo.disability_status : "I do not want to answer",
      how_heard: profile.referral?.default_source || "Company website",
      referrer_name: profile.referral?.referrer_name || "",
      referrer_email: profile.referral?.referrer_email || "",
      resume_path: context.resumePath || profile.documents?.master_resume_pdf || "",
      cover_letter_path: context.coverLetterPath || "",
      cover_letter_text: context.coverLetterText || "",
      generated_password: context.generatedPassword || "",
      essay: "",
    };
    const value = spec.value || {};
    let out = "";
    if (value.const !== undefined) out = value.const;
    else if (value.compute) out = computed[value.compute] ?? "";
    else if (value.path) out = g(value.path) ?? "";
    if (typeof out === "boolean") out = out ? "yes" : "no";
    if (spec.enum === "yes_no" && yn[out]) out = yn[out];
    return out == null ? "" : String(out);
  },

  matchOption(value, options) {
    if (!options || !options.length) return value || null;
    // drop placeholders - "" is a substring of everything and would always win
    const PLACEHOLDER = ["select", "select...", "select one", "choose", "choose one", "-", "--"];
    options = options.filter((o) => String(o).trim()
      && !PLACEHOLDER.includes(String(o).trim().toLowerCase()));
    if (!options.length) return null;
    const target = String(value || "").toLowerCase().trim();
    if (!target) return null;
    const lowered = options.map((o) => String(o).toLowerCase().trim());
    let index = lowered.indexOf(target);
    if (index >= 0) return options[index];
    index = lowered.findIndex((o) => (o.includes(target) || target.includes(o))
      && Math.abs(o.length - target.length) < 25);
    if (index >= 0) return options[index];

    const syn = this.data.optionSynonyms;
    const bucket = Object.keys(syn).find((k) => syn[k].includes(target)
      || syn[k].some((t) => target.startsWith(t)));
    if (bucket) {
      index = lowered.findIndex((o) => syn[bucket].includes(o)
        || syn[bucket].some((t) => o.startsWith(t)));
      if (index >= 0) return options[index];
      if (bucket === "decline") {
        index = lowered.findIndex((o) => ["decline", "not wish", "not want", "prefer not",
          "not disclose"].some((t) => o.includes(t)));
        if (index >= 0) return options[index];
      }
    }
    const words = (s) => new Set(s.match(/[a-z0-9]+/g) || []);
    const tw = words(target);
    let best = null, bestScore = 0;
    lowered.forEach((option, i) => {
      const ow = words(option);
      if (!ow.size) return;
      const inter = [...tw].filter((w) => ow.has(w)).length;
      const score = inter / new Set([...tw, ...ow]).size;
      if (score > bestScore) { best = options[i]; bestScore = score; }
    });
    if (bestScore >= 0.34) return best;
    const stems = (s) => new Set((s.match(/[a-z]+/g) || []).filter((w) => w.length > 2).map((w) => w.slice(0, 5)));
    const ts = stems(target);
    best = null; bestScore = 0;
    lowered.forEach((option, i) => {
      const os = stems(option);
      if (!os.size) return;
      const score = [...ts].filter((w) => os.has(w)).length / (ts.size || 1);
      if (score > bestScore) { best = options[i]; bestScore = score; }
    });
    return bestScore >= 0.5 ? best : null;
  },
};
