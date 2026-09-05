/* The resolution cascade, mirroring autofill/resolver.py.
   Same JSON knowledge base, same stage order, same thresholds - so V2 fills a form the way V1
   would. The server is preferred when reachable (it adds the answer bank and the model); this
   is the offline path. */
globalThis.JW = globalThis.JW || {};
JW.resolver = {
  FILL: 0.85,
  REVIEW: 0.6,
  ABBREV: [
    [/\be[- ]?mail\b/g, "email"], [/\bdob\b/g, "date of birth"], [/\bph\b/g, "phone"],
    [/\btel\b/g, "phone"], [/\bmob\b/g, "mobile"], [/\bexp\b/g, "experience"],
    [/\byrs\b/g, "years"], [/#/g, " number "], [/\buni\b/g, "university"],
    [/\bgrad\b/g, "graduation"], [/\bpref\b/g, "preferred"],
  ],
  TYPE_AFFINITY: {
    email: ["email"], tel: ["tel", "phone"], url: ["url"], date: ["date"], number: ["number"],
    file: ["file"], password: ["password"], checkbox: ["checkbox"], radio: ["radio", "select"],
    "select-one": ["select", "radio"], select: ["select", "radio"], textarea: ["textarea"],
  },

  normalize(text) {
    let out = String(text || "").toLowerCase()
      .replace(/\((?:optional|required)\)/g, " ")
      .replace(/[*✱]/g, " ")
      .replace(/\brequired\b|\boptional\b/g, " ");
    this.ABBREV.forEach(([re, to]) => { out = out.replace(re, to); });
    return out.replace(/[_\-/\\]+/g, " ").replace(/[^a-z0-9+#.,' ]+/g, " ")
      .replace(/\s+/g, " ").trim();
  },
  tokens(text) { return (text.match(/[a-z0-9+#]+/g) || []); },
  question(field) {
    return JW.util.clean(field.label || field.aria_label || field.placeholder
      || field.name || field.element_id || field.selector);
  },

  atsLookup(field, atsName) {
    const spec = JW.catalog.data.ats[atsName] || JW.catalog.data.ats.generic;
    const maps = [
      [spec.name_map, field.name], [spec.id_map, field.element_id],
      [spec.automation_id_map, field.name], [spec.automation_id_map, field.element_id],
    ];
    for (const [map, key] of maps) {
      if (map && key && map[key]) return map[key];
    }
    if (spec.attribute_map) {
      for (const map of Object.values(spec.attribute_map)) {
        const key = field.name || field.element_id;
        if (map[key]) return map[key];
      }
    }
    if (spec.automation_id_map) {
      const hay = `${field.name} ${field.element_id} ${field.selector}`;
      for (const [token, key] of Object.entries(spec.automation_id_map)) {
        if (token && hay.includes(token)) return key;
      }
    }
    return null;
  },

  score(field, spec) {
    const label = this.normalize(this.question(field));
    if (!label) return [0, ""];
    const labelTokens = new Set(this.tokens(label));
    let best = 0, reason = "";
    const wordRe = (t) => new RegExp(`(?<![a-z0-9])${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![a-z0-9])`);

    for (const term of spec.strong || []) {
      const norm = this.normalize(term);
      if (!norm) continue;
      if (label === norm) return [1, `label equals '${term}'`];
      if (wordRe(norm).test(label)) {
        const score = 0.8 + 0.15 * Math.min(1, norm.length / Math.max(label.length, 1));
        if (score > best) { best = score; reason = `label contains '${term}'`; }
      }
    }
    for (const term of spec.synonyms || []) {
      const norm = this.normalize(term);
      if (!norm) continue;
      let score;
      if (label === norm) score = 0.95;
      else if (wordRe(norm).test(label))
        score = 0.72 + 0.15 * Math.min(1, norm.length / Math.max(label.length, 1));
      else {
        const termTokens = new Set(this.tokens(norm));
        if (!termTokens.size) continue;
        const overlap = [...termTokens].filter((t) => labelTokens.has(t)).length / termTokens.size;
        score = overlap * 0.62;
      }
      if (score > best) { best = score; reason = `matches '${term}'`; }
    }
    for (const term of spec.negative || []) {
      if (wordRe(this.normalize(term)).test(label)) { best -= 0.45; reason += ` (penalised: '${term}')`; }
    }
    const expected = spec.type || "text";
    const observed = String(field.input_type || field.tag || "text").toLowerCase();
    const affinity = this.TYPE_AFFINITY[observed] || [];
    if (affinity.length) {
      if (affinity.includes(expected)) best += 0.06;
      else if (["text", "textarea"].includes(expected) && ["text", "textarea"].includes(observed)) best += 0.02;
      else if (expected !== "text" && ["email", "tel", "url", "file", "password", "date", "number"].includes(observed)) best -= 0.3;
    }
    if ((field.options || []).length && ["select", "radio", "checkbox"].includes(expected)) best += 0.05;
    best += (spec.priority || 50) / 10000;
    return [Math.max(0, Math.min(1, best)), reason];
  },

  dynamic(field, profile) {
    const question = this.normalize(this.question(field));
    for (const rule of JW.catalog.data.patterns.dynamic) {
      const match = question.match(new RegExp(rule.pattern));
      if (!match) continue;
      const captured = (rule.capture && match[1]) ? match[1].trim() : "";
      if (rule.handler === "years_with_skill" && captured) {
        const skill = (profile.skills || []).find((s) => s.name.toLowerCase() === captured.toLowerCase());
        const years = skill?.years || 0;
        // answering "years with COBOL" from total years of experience would mislead, so leave
        // it for the model or the human (mirrors autofill/resolver.py)
        if (!years) return rule.terminal ? { unanswered: true } : null;
        const value = String(years);
        if ((field.options || []).length) {
          const picked = JW.catalog.matchOption(value, field.options) || this.closestNumeric(years, field.options);
          return picked ? { key: "years_with_skill", value: picked, confidence: 0.86, action: "select" } : null;
        }
        return { key: "years_with_skill", value, confidence: 0.88, action: "fill" };
      }
      if (rule.handler === "has_skill" && captured) {
        const names = new Set((profile.skills || []).map((s) => s.name.toLowerCase()));
        const value = names.has(captured.toLowerCase()) ? "Yes" : "No";
        const picked = (field.options || []).length ? JW.catalog.matchOption(value, field.options) : value;
        return picked ? { key: "has_skill", value: picked, confidence: 0.82,
                          action: field.options?.length ? "select" : "fill" } : null;
      }
      if (rule.handler === "notice_period") {
        const value = JW.catalog.valueFor("notice_period", profile);
        const picked = (field.options || []).length ? JW.catalog.matchOption(value, field.options) : value;
        return picked ? { key: "notice_period", value: picked, confidence: 0.82,
                          action: field.options?.length ? "select" : "fill" } : null;
      }
    }
    return null;
  },
  closestNumeric(years, options) {
    let best = null, bestDistance = Infinity;
    for (const option of options) {
      const numbers = (option.match(/\d+(?:\.\d+)?/g) || []).map(Number);
      if (!numbers.length) continue;
      const low = numbers[0];
      const high = numbers[1] ?? (/\+|more/i.test(option) ? low + 99 : low);
      if (years >= low && years <= high) return option;
      const distance = Math.min(Math.abs(years - low), Math.abs(years - high));
      if (distance < bestDistance) { bestDistance = distance; best = option; }
    }
    return best;
  },

  resolveField(field, profile, context) {
    const question = this.question(field);
    const signal = JW.catalog.needsHuman(`${question} ${(field.options || []).join(" ")}`);
    if (signal) return { blocked: `needs a human: '${signal}'`, confidence: 0 };
    if (JW.catalog.isSensitive(question)) return { blocked: `sensitive field: '${question}'`, confidence: 0 };

    const mapped = this.atsLookup(field, context.ats);
    if (mapped) {
      const value = this.valueFor(mapped, field, profile, context);
      if (value) return { key: mapped, value, confidence: 0.98, method: "ats_map",
                          action: this.action(field, mapped), reason: `${context.ats} field map` };
    }
    const dyn = this.dynamic(field, profile);
    if (dyn?.unanswered) return { confidence: 0, reason: "pattern matched, profile cannot answer" };
    if (dyn) return { key: dyn.key, value: dyn.value, confidence: dyn.confidence,
                      method: "token", action: dyn.action, reason: "pattern rule" };

    let bestKey = "", bestScore = 0, bestReason = "";
    for (const spec of JW.catalog.data.fields) {
      const [score, reason] = this.score(field, spec);
      if (score > bestScore) { bestKey = spec.key; bestScore = score; bestReason = reason; }
    }
    if (bestKey && bestScore >= this.REVIEW) {
      const spec = JW.catalog.data.byKey[bestKey];
      if (spec.escalate) return { blocked: `policy: '${question}' is always escalated`, confidence: bestScore };
      const value = this.valueFor(bestKey, field, profile, context);
      if (value) {
        return { key: bestKey, value, confidence: bestScore,
                 method: bestScore >= this.FILL ? "token" : "fuzzy",
                 action: this.action(field, bestKey),
                 needsReview: bestScore < this.FILL, reason: bestReason };
      }
    }
    return { confidence: bestScore, reason: "no catalog match" };
  },

  valueFor(key, field, profile, context) {
    const value = JW.catalog.valueFor(key, profile, context);
    if (!value) return "";
    if ((field.options || []).length) return JW.catalog.matchOption(value, field.options) || "";
    return value;
  },
  action(field, key) {
    const spec = JW.catalog.data.byKey[key] || {};
    const observed = String(field.input_type || field.tag || "").toLowerCase();
    if (spec.type === "file" || observed === "file") return "upload";
    if (observed === "checkbox") return "check";
    if (["radio", "select", "select-one"].includes(observed) || (field.options || []).length) return "select";
    return "fill";
  },

  resolveForm(fields, profile, context) {
    const plan = { fields: [], unresolved: [], blocking: [], url: location.href, ats: context.ats };
    for (const field of fields) {
      if (!field.visible && field.input_type !== "file") continue;
      const resolution = this.resolveField(field, profile, context);
      if (resolution.blocked) {
        plan.blocking.push(`${this.question(field)} - ${resolution.blocked}`);
        plan.unresolved.push(field);
        continue;
      }
      if (!resolution.value) {
        if (field.required) plan.unresolved.push(field);
        continue;
      }
      plan.fields.push({
        selector: field.selector, field_key: resolution.key, question: this.question(field),
        value: resolution.value, method: resolution.method, confidence: resolution.confidence,
        action: resolution.action, needs_review: !!resolution.needsReview,
      });
    }
    return plan;
  },
};
