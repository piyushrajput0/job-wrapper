/* Schema-driven form renderer: every profile field in the UI comes from /api/schema. */
const Form = (() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function get(obj, path) {
    return path.split(".").reduce((node, part) => (node == null ? undefined : node[part]), obj);
  }
  function set(obj, path, value) {
    const parts = path.split(".");
    const last = parts.pop();
    let node = obj;
    parts.forEach((part) => {
      if (node[part] == null || typeof node[part] !== "object") node[part] = {};
      node = node[part];
    });
    node[last] = value;
  }

  const label = (f) =>
    `<label for="${esc(f._id)}">${esc(f.label)}${f.required ? '<span class="req">*</span>' : ""}</label>`;
  const help = (f) => (f.help ? `<div class="help">${esc(f.help)}</div>` : "");

  function control(f, value) {
    const id = f._id;
    const common = `id="${id}" data-path="${esc(f.path)}" data-kind="${f.kind}"`;
    const ph = f.placeholder ? ` placeholder="${esc(f.placeholder)}"` : "";
    switch (f.kind) {
      case "bool":
        return `<label class="switch"><input type="checkbox" ${common} ${value ? "checked" : ""}>
                <span class="track"></span><span class="muted">${value ? "Yes" : "No"}</span></label>`;
      case "select": {
        const options = (f.options || []).slice();
        if (f.free && value && !options.includes(value)) options.unshift(value);
        const blank = f.required ? "" : `<option value=""></option>`;
        return `<select ${common}>${blank}${options
          .map((o) => `<option value="${esc(o)}"${o === value ? " selected" : ""}>${esc(
            String(o).replace(/_/g, " "))}</option>`).join("")}</select>`;
      }
      case "multi": {
        const chosen = Array.isArray(value) ? value : [];
        return `<div class="multi" ${common}>${(f.options || []).map((o) =>
          `<span class="chip${chosen.includes(o) ? " on" : ""}" data-v="${esc(o)}">${esc(
            String(o).replace(/_/g, " "))}</span>`).join("")}</div>`;
      }
      case "tags": {
        const items = Array.isArray(value) ? value : [];
        return `<div class="tags" ${common}>${items.map((t) =>
          `<span class="tag">${esc(t)}<button type="button" data-rm="${esc(t)}">×</button></span>`).join("")}
          <input type="text" placeholder="Type and press Enter"></div>`;
      }
      case "lines":
        return `<textarea ${common} rows="5"${ph}>${esc(
          (Array.isArray(value) ? value : []).join("\n"))}</textarea>`;
      case "textarea":
        return `<textarea ${common}${ph}>${esc(value ?? "")}</textarea>`;
      case "number":
        return `<input type="number" ${common} value="${esc(value ?? "")}"${
          f.step ? ` step="${f.step}"` : ""}${ph}>`;
      case "file_path":
        return `<input type="text" ${common} value="${esc(value ?? "")}" placeholder="${
          esc(f.placeholder || "/path/to/file")}">`;
      case "date": case "month": case "email": case "tel": case "url":
        return `<input type="${f.kind}" ${common} value="${esc(value ?? "")}"${ph}>`;
      default:
        return `<input type="text" ${common} value="${esc(value ?? "")}"${ph}>`;
    }
  }

  let counter = 0;
  function renderField(f, value, prefix = "") {
    f._id = `f${counter++}`;
    const path = prefix ? `${prefix}.${f.path}` : f.path;
    const spec = { ...f, path };
    return `<div class="field" style="grid-column: span ${f.col || 12}">
      ${label(spec)}${control(spec, value)}${help(spec)}</div>`;
  }

  function renderFields(fields, source, prefix = "") {
    return `<div class="form-grid">${fields
      .map((f) => renderField(f, get(source || {}, f.path), prefix)).join("")}</div>`;
  }

  /* repeatable list, e.g. experience[] */
  function renderList(repeat, entries, prefix) {
    const title = (entry, index) =>
      esc(entry?.[repeat.title_field] || `Entry ${index + 1}`) || `Entry ${index + 1}`;
    const rows = (entries || []).map((entry, index) => `
      <div class="entry${index === 0 ? "" : " collapsed"}" data-index="${index}">
        <header><svg class="chev" width="12" height="12" viewBox="0 0 12 12"><path d="M2 4l4 4 4-4" stroke="currentColor" fill="none" stroke-width="1.6"/></svg>
          <strong>${title(entry, index)}</strong><span class="spacer"></span>
          <button class="btn sm danger" data-remove="${index}" type="button">Remove</button></header>
        <div class="body">${renderFields(repeat.fields, entry, `${prefix}.${index}`)}</div>
      </div>`).join("");
    return `<div class="repeat" data-repeat="${esc(repeat.path)}">${rows ||
      '<div class="empty"><h3>Nothing here yet</h3><p>Add your first entry.</p></div>'}
      <button class="btn" data-add="${esc(repeat.path)}" type="button">+ Add</button></div>`;
  }

  /* keyed map, e.g. work_authorization.by_country */
  function renderMap(repeat, mapping, prefix) {
    const rows = Object.entries(mapping || {}).map(([key, entry]) => `
      <div class="entry" data-key="${esc(key)}">
        <header><svg class="chev" width="12" height="12" viewBox="0 0 12 12"><path d="M2 4l4 4 4-4" stroke="currentColor" fill="none" stroke-width="1.6"/></svg>
          <strong>${esc(key)}</strong><span class="spacer"></span>
          <button class="btn sm danger" data-remove-key="${esc(key)}" type="button">Remove</button></header>
        <div class="body">${renderFields(repeat.fields, entry, `${prefix}.${key}`)}</div>
      </div>`).join("");
    return `<div class="repeat" data-repeat-map="${esc(repeat.path)}">${rows}
      <div class="toolbar"><input type="text" id="new-country" placeholder="${
        esc(repeat.key_placeholder || "Country code")}" style="width:160px">
      <button class="btn" data-add-key="${esc(repeat.path)}" type="button">+ Add country</button></div></div>`;
  }

  function renderSection(section, profile) {
    let body = "";
    if (section.fields) body += renderFields(section.fields, profile);
    if (section.repeat) {
      const value = get(profile, section.repeat.path);
      body += section.repeat.kind === "map"
        ? renderMap(section.repeat, value, section.repeat.path)
        : renderList(section.repeat, value, section.repeat.path);
    }
    (section.extra_repeats || []).forEach((repeat) => {
      body += `<h4 style="margin:18px 0 8px">${esc(repeat.title || repeat.path)}</h4>`;
      body += renderList(repeat, get(profile, repeat.path), repeat.path);
    });
    return `<div class="card"><h3>${esc(section.title)}</h3>
      ${section.blurb ? `<div class="blurb">${esc(section.blurb)}</div>` : ""}${body}</div>`;
  }

  /* read one control back into the profile object */
  function readControl(el, profile) {
    const path = el.dataset.path;
    const kind = el.dataset.kind;
    if (!path) return;
    if (kind === "bool") set(profile, path, el.checked);
    else if (kind === "number") set(profile, path, el.value === "" ? null : Number(el.value));
    else if (kind === "date") set(profile, path, el.value || null);
    else if (kind === "lines")
      set(profile, path, el.value.split("\n").map((s) => s.trim()).filter(Boolean));
    else if (kind === "tags")
      set(profile, path, [...el.querySelectorAll(".tag")].map((t) => t.firstChild.textContent));
    else if (kind === "multi")
      set(profile, path, [...el.querySelectorAll(".chip.on")].map((c) => c.dataset.v));
    else set(profile, path, el.value);
  }

  return { renderSection, renderFields, readControl, get, set, esc };
})();
