/* Works out whether this page is a job posting, an application form, or neither. */
globalThis.JW = globalThis.JW || {};
JW.detect = {
  FORM_HINTS: ["apply", "application", "submit your", "resume", "cover letter"],

  isApplicationForm() {
    const controls = document.querySelectorAll(
      "form input:not([type=hidden]):not([type=search]), form textarea, form select");
    if (controls.length >= 4) return true;
    if (document.querySelector("input[type=file]")
        && /resume|cv/i.test(document.body.innerText.slice(0, 6000))) return true;
    return false;
  },

  isJobPosting() {
    const text = document.body.innerText.slice(0, 8000).toLowerCase();
    const signals = ["responsibilities", "qualifications", "what you'll do", "requirements",
                     "about the role", "who you are", "apply for this job", "job description"];
    return signals.filter((s) => text.includes(s)).length >= 2;
  },

  /* Pull the posting out of the page: title, company, location, JD text. */
  extractJob() {
    const meta = (name) => document.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.content || "";
    let title = "", company = "", location = "", description = "";

    for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const parsed = JSON.parse(node.textContent);
        const list = Array.isArray(parsed) ? parsed : [parsed, ...(parsed["@graph"] || [])];
        const posting = list.find((x) => x && x["@type"] === "JobPosting");
        if (posting) {
          title = posting.title || title;
          company = posting.hiringOrganization?.name || company;
          const address = posting.jobLocation?.address || posting.jobLocation?.[0]?.address;
          location = [address?.addressLocality, address?.addressRegion, address?.addressCountry]
            .filter(Boolean).join(", ") || location;
          description = (posting.description || "").replace(/<[^>]+>/g, " ") || description;
        }
      } catch { /* malformed ld+json is common */ }
    }

    title = title || JW.util.clean(document.querySelector("h1")?.innerText || meta("og:title") || document.title);
    company = company || JW.util.clean(meta("og:site_name"))
      || JW.util.clean(location.hostname?.replace(/^www\./, "").split(".")[0] || "")
      || JW.util.clean(window.location.hostname.replace(/^www\./, "").split(".")[0]);
    if (!description) {
      const candidates = [...document.querySelectorAll(
        "[class*='description'], [class*='job-details'], [data-testid*='description'], article, main, #content")]
        .map((n) => n.innerText || "")
        .filter((t) => t.length > 400)
        .sort((a, b) => b.length - a.length);
      description = candidates[0] || document.body.innerText;
    }
    const locationNode = [...document.querySelectorAll("[class*='location'], [data-testid*='location']")]
      .map((n) => JW.util.clean(n.innerText)).find((t) => t && t.length < 80);

    return {
      title: title.slice(0, 200),
      company: company.slice(0, 120),
      location: (location || locationNode || "").slice(0, 120),
      description: JW.util.clean(description).slice(0, 30000),
      url: window.location.href,
    };
  },

  async extractFields() {
    if (!window.__jobwrapperExtract) {
      const source = await JW.util.resource("extract_fields.js");
      // the shared extractor defines window.__jobwrapperExtract when evaluated
      const script = document.createElement("script");
      script.textContent = source;
      document.documentElement.appendChild(script);
      script.remove();
    }
    if (window.__jobwrapperExtract) return window.__jobwrapperExtract();
    return JW.detect.extractFieldsFallback();
  },

  /* MV3 pages with a strict CSP block injected <script>; do it in the isolated world instead. */
  extractFieldsFallback() {
    const out = [];
    const seenRadios = new Set();
    document.querySelectorAll("input, select, textarea").forEach((el) => {
      const type = (el.type || el.tagName).toLowerCase();
      if (["submit", "button", "image", "reset", "hidden"].includes(type)) return;
      const label = JW.util.clean(
        (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.textContent)
        || el.closest("label")?.textContent || el.getAttribute("aria-label")
        || el.placeholder || el.name || "");
      if (!label) return;
      if (type === "radio") {
        if (!el.name || seenRadios.has(el.name)) return;
        seenRadios.add(el.name);
      }
      const descriptor = {
        selector: el.id ? `#${CSS.escape(el.id)}`
          : el.name ? `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]` : "",
        tag: el.tagName.toLowerCase(), input_type: type, name: el.name || "",
        element_id: el.id || "", label, aria_label: el.getAttribute("aria-label") || "",
        placeholder: el.placeholder || "", required: !!el.required,
        options: el.tagName === "SELECT" ? [...el.options].map((o) => JW.util.clean(o.textContent)) : [],
        option_values: el.tagName === "SELECT" ? [...el.options].map((o) => o.value) : [],
        maxlength: el.maxLength > 0 ? el.maxLength : null, group: el.name || "", section: "",
        autocomplete: el.getAttribute("autocomplete") || "", current_value: el.value || "",
        visible: type === "file" || !!el.offsetParent,
      };
      if (type === "radio") {
        const group = document.querySelectorAll(`input[type=radio][name="${CSS.escape(el.name)}"]`);
        descriptor.options = [...group].map((r) => JW.util.clean(r.closest("label")?.textContent || r.value));
        descriptor.option_values = [...group].map((r) => r.value);
        descriptor.selector = `input[type="radio"][name="${CSS.escape(el.name)}"]`;
        const legend = el.closest("fieldset")?.querySelector("legend");
        if (legend) descriptor.label = JW.util.clean(legend.textContent) || descriptor.label;
      }
      if (descriptor.selector) out.push(descriptor);
    });
    return out;
  },
};
