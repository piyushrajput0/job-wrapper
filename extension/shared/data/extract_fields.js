/**
 * Shared form-field extraction.
 *
 * This exact file is evaluated by Playwright in V1 and injected by the content script in V2, so
 * both editions see forms identically. It returns FieldDescriptor-shaped objects (see
 * models/application.py).
 *
 * Exposes: window.__jobwrapperExtract(rootSelector?) -> FieldDescriptor[]
 */
(function () {
  const MAX_LABEL = 300;

  function visible(el) {
    if (!el) return false;
    if (el.type === "hidden") return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (parseFloat(style.opacity || "1") < 0.05) return false;
    const rect = el.getBoundingClientRect();
    // file inputs are routinely 0x0 behind a styled button - they still count
    if (el.type === "file") return true;
    return rect.width > 1 && rect.height > 1;
  }

  function clean(text) {
    return (text || "").replace(/\s+/g, " ").replace(/[​-‍﻿]/g, "").trim().slice(0, MAX_LABEL);
  }

  function cssPath(el) {
    if (el.id && !/^[0-9]/.test(el.id) && document.querySelectorAll(`#${CSS.escape(el.id)}`).length === 1) {
      return `#${CSS.escape(el.id)}`;
    }
    if (el.name) {
      const same = document.querySelectorAll(`${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`);
      if (same.length === 1) return `${el.tagName.toLowerCase()}[name="${CSS.escape(el.name)}"]`;
    }
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 6) {
      let part = node.tagName.toLowerCase();
      if (node.id && !/^[0-9]/.test(node.id)) {
        parts.unshift(`#${CSS.escape(node.id)}`);
        break;
      }
      const parent = node.parentElement;
      if (parent) {
        const siblings = Array.from(parent.children).filter((c) => c.tagName === node.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ");
  }

  function labelFor(el) {
    const bits = [];
    if (el.id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (explicit) bits.push(explicit.textContent);
    }
    const wrapping = el.closest("label");
    if (wrapping) {
      const clone = wrapping.cloneNode(true);
      clone.querySelectorAll("input,select,textarea,button").forEach((n) => n.remove());
      bits.push(clone.textContent);
    }
    if (el.getAttribute("aria-labelledby")) {
      el.getAttribute("aria-labelledby").split(/\s+/).forEach((id) => {
        const node = document.getElementById(id);
        if (node) bits.push(node.textContent);
      });
    }
    if (!bits.filter((b) => clean(b)).length) {
      // climb to a container and take the nearest preceding text node
      let node = el.parentElement;
      for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
        const candidates = node.querySelectorAll(
          "label, legend, .label, [class*='label'], [class*='question'], [class*='Label'], h1,h2,h3,h4,h5,p,span,div"
        );
        for (const candidate of candidates) {
          if (candidate.contains(el)) continue;
          const text = clean(candidate.textContent);
          if (text && text.length > 1 && text.length < MAX_LABEL) {
            bits.push(text);
            break;
          }
        }
        if (bits.filter((b) => clean(b)).length) break;
      }
    }
    const joined = bits.map(clean).filter(Boolean);
    return joined.length ? joined[0] : "";
  }

  function sectionFor(el) {
    let node = el.parentElement;
    for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
      const heading = node.querySelector("h1,h2,h3,legend,[role='heading']");
      if (heading && !heading.contains(el)) {
        const text = clean(heading.textContent);
        if (text) return text;
      }
    }
    return "";
  }

  function requiredFlag(el) {
    if (el.required || el.getAttribute("aria-required") === "true") return true;
    const label = labelFor(el);
    if (/\*|\(required\)|\brequired\b/i.test(label)) return true;
    const container = el.closest("div,fieldset,li,section");
    if (container && /\*|\brequired\b/i.test(clean(container.querySelector("label,legend")?.textContent || ""))) {
      return true;
    }
    return false;
  }

  function describeCustomSelect(el) {
    // React/Workday listboxes: a button or div that opens a popup of [role=option]
    const controls = el.getAttribute("aria-controls");
    let list = controls ? document.getElementById(controls) : null;
    if (!list) list = el.parentElement && el.parentElement.querySelector("[role='listbox']");
    if (!list) return [];
    return Array.from(list.querySelectorAll("[role='option']"))
      .map((o) => clean(o.textContent))
      .filter(Boolean)
      .slice(0, 200);
  }

  function extract(rootSelector) {
    const root = rootSelector ? document.querySelector(rootSelector) : document;
    if (!root) return [];
    const out = [];
    const seenRadioGroups = new Set();

    const controls = root.querySelectorAll(
      "input, select, textarea, [contenteditable='true'], [role='combobox'], [role='listbox'], [role='radiogroup']"
    );

    controls.forEach((el) => {
      const tag = el.tagName.toLowerCase();
      const type = (el.type || el.getAttribute("role") || tag || "text").toLowerCase();
      if (tag === "input" && ["submit", "button", "image", "reset"].includes(type)) return;
      if (!visible(el) && type !== "file") return;

      const descriptor = {
        selector: cssPath(el),
        frame: "",
        tag: tag,
        input_type: type,
        name: el.name || el.getAttribute("data-automation-id") || el.getAttribute("data-ui") || "",
        element_id: el.id || "",
        label: labelFor(el),
        aria_label: clean(el.getAttribute("aria-label") || ""),
        placeholder: clean(el.placeholder || el.getAttribute("data-placeholder") || ""),
        required: requiredFlag(el),
        options: [],
        option_values: [],
        maxlength: el.maxLength && el.maxLength > 0 ? el.maxLength : null,
        group: el.name || "",
        section: sectionFor(el),
        autocomplete: el.getAttribute("autocomplete") || "",
        current_value: type === "checkbox" || type === "radio" ? (el.checked ? "checked" : "") : clean(el.value || ""),
        visible: visible(el),
      };

      if (tag === "select") {
        const options = Array.from(el.options).filter((o) => o.value !== "" || clean(o.textContent));
        descriptor.options = options.map((o) => clean(o.textContent)).filter(Boolean);
        descriptor.option_values = options.map((o) => o.value);
      } else if (type === "radio") {
        const groupName = el.name;
        if (!groupName || seenRadioGroups.has(groupName)) return;
        seenRadioGroups.add(groupName);
        const group = root.querySelectorAll(`input[type="radio"][name="${CSS.escape(groupName)}"]`);
        descriptor.options = Array.from(group).map((r) => labelFor(r) || r.value).filter(Boolean);
        descriptor.option_values = Array.from(group).map((r) => r.value);
        descriptor.selector = `input[type="radio"][name="${CSS.escape(groupName)}"]`;
        const fieldset = el.closest("fieldset, [role='radiogroup'], div");
        if (fieldset) {
          const legend = fieldset.querySelector("legend, label, .label, [class*='question']");
          if (legend && !legend.contains(el)) {
            const text = clean(legend.textContent);
            if (text.length > descriptor.label.length) descriptor.label = text;
          }
        }
      } else if (type === "combobox" || type === "listbox") {
        descriptor.options = describeCustomSelect(el);
      }

      if (!descriptor.label && !descriptor.aria_label && !descriptor.placeholder && !descriptor.name) return;
      out.push(descriptor);
    });

    return out;
  }

  window.__jobwrapperExtract = extract;
  return extract(arguments && arguments.length ? arguments[0] : undefined);
})();
