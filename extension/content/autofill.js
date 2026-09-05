/* Applies a fill plan to the live DOM, using real events so React/Vue controls register it. */
globalThis.JW = globalThis.JW || {};
JW.autofill = {
  find(selector) { try { return document.querySelector(selector); } catch { return null; } },

  setNativeValue(el, value) {
    const prototype = el instanceof HTMLTextAreaElement
      ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (setter) setter.call(el, value); else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  },

  highlight(el, ok) {
    if (!el || !el.style) return;
    el.style.transition = "box-shadow .2s";
    el.style.boxShadow = ok ? "0 0 0 3px rgba(63,185,132,.5)" : "0 0 0 3px rgba(224,95,95,.5)";
    setTimeout(() => { el.style.boxShadow = ""; }, 2200);
  },

  async applyOne(item) {
    const el = this.find(item.selector);
    if (!el) return { ok: false, error: "element not found" };
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    await JW.util.sleep(120);
    try {
      if (item.action === "upload") return { ok: false, error: "file uploads must be picked by you" };
      if (item.action === "check") {
        const want = ["yes", "true", "1", "on", "checked"].includes(String(item.value).toLowerCase());
        if (el.checked !== want) el.click();
        this.highlight(el, true);
        return { ok: true };
      }
      if (item.action === "select") {
        if (el.tagName === "SELECT") {
          const options = [...el.options];
          const match = options.find((o) => JW.util.clean(o.textContent).toLowerCase() === String(item.value).toLowerCase())
            || options.find((o) => JW.util.clean(o.textContent).toLowerCase().includes(String(item.value).toLowerCase()));
          if (!match) return { ok: false, error: `no option '${item.value}'` };
          el.value = match.value;
          el.dispatchEvent(new Event("change", { bubbles: true }));
          this.highlight(el, true);
          return { ok: true };
        }
        if (item.selector.includes("radio")) {
          const group = document.querySelectorAll(item.selector);
          for (const radio of group) {
            const label = JW.util.clean(radio.closest("label")?.textContent
              || (radio.id && document.querySelector(`label[for="${CSS.escape(radio.id)}"]`)?.textContent)
              || radio.value);
            if (label.toLowerCase() === String(item.value).toLowerCase()
                || label.toLowerCase().includes(String(item.value).toLowerCase())) {
              radio.click();
              this.highlight(radio, true);
              return { ok: true };
            }
          }
          return { ok: false, error: `no radio matched '${item.value}'` };
        }
        el.click();
        await JW.util.sleep(320);
        const option = [...document.querySelectorAll("[role=option]")]
          .find((o) => JW.util.clean(o.textContent).toLowerCase().includes(String(item.value).toLowerCase()));
        if (option) { option.click(); return { ok: true }; }
        return { ok: false, error: "listbox option not found" };
      }
      el.focus();
      this.setNativeValue(el, item.value);
      el.blur();
      this.highlight(el, true);
      return { ok: true };
    } catch (error) {
      this.highlight(el, false);
      return { ok: false, error: String(error.message).slice(0, 140) };
    }
  },

  async apply(plan, onProgress) {
    const results = [];
    for (const [index, item] of plan.fields.entries()) {
      if (item.skip) { results.push({ item, ok: false, error: "skipped by you" }); continue; }
      const result = await this.applyOne(item);
      results.push({ item, ...result });
      onProgress?.(index + 1, plan.fields.length, item, result);
      await JW.util.sleep(90);
    }
    return results;
  },
};
