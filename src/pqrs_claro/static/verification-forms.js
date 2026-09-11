import { el, button, dateLabel } from "./ui.js";

const inputField = (label, key, draft, { multiline = false, required = true, hint, maxLength = 3000 } = {}) => {
  const control = el(multiline ? "textarea" : "input", {
    id: `verification-${key}`, value: draft[key] || "", required, maxLength,
    ...(multiline ? { rows: 3 } : { type: "text" }),
    onInput: (event) => { draft[key] = event.target.value; },
  });
  return el("label", { className: "field", for: control.id }, el("span", {}, label), control,
    hint ? el("span", { className: "field-hint" }, hint) : null);
};

export function verificationRecord(record, caseId, showSource) {
  const location = record.passage;
  return el("div", { className: "source-review-form" },
    el("p", {}, el("strong", {}, record.fact)),
    el("p", { className: "small" }, record.kind === "human_review"
      ? `Comprobación registrada por ${record.recorded_by}.`
      : `Comprobación declarada por un antecedente${record.attributed_to ? `: ${record.attributed_to}` : "; autor de la comprobación no identificado"}.`),
    el("p", { className: "small muted" }, record.basis),
    el("p", { className: "small muted" }, [record.scope?.person, record.scope?.period, record.scope?.subject].filter(Boolean).join(" · ")),
    location ? el("details", { className: "source-text" },
      el("summary", {}, `Ver pasaje · página o sección ${location.page}, líneas ${location.line_start}–${location.line_end}`),
      el("blockquote", {}, location.quote),
      showSource ? button("Ver fuente", () => showSource(record.source_id, location), "quiet") : null,
      el("a", { className: "small-link", target: "_blank", rel: "noopener noreferrer",
        href: `/api/sources/${encodeURIComponent(record.source_id)}/original?case_id=${encodeURIComponent(caseId)}` }, "Abrir original ↗"),
    ) : el("p", { className: "small muted" }, "Confirmación escrita atribuida; no tiene archivo adjunto."),
    el("p", { className: "small muted" }, `Registrada el ${dateLabel(record.recorded_at, true)}. `,
      record.active === false ? "Necesita revisión antes de reutilizarse." : "Su aplicación se confirma para cada pregunta."),
  );
}

export function verificationEditor({ editor, records, busy, changed, submit, close, caseId, showSource }) {
  const existing = records.filter((record) => record.active &&
    !(record.kind === "antecedent_declared" && ["source_identity", "provenance", "issued_version", "validity", "transcription"].includes(editor.check.reason_code)) &&
    (record.source_id ? editor.check.linked_source_ids?.includes(record.source_id)
      : record.case_id === caseId && editor.allowWritten));
  const selected = existing.find((record) => record.id === editor.recordId);
  const select = el("select", { id: "verification-record-choice", value: editor.recordId || "new",
    onChange: (event) => { editor.recordId = event.target.value; changed(); } },
    el("option", { value: "new" }, "Registrar una comprobación humana"),
    existing.map((record) => el("option", { value: record.id },
      `${record.kind === "human_review" ? "Revisión humana" : "Declaración del antecedente"} · ${record.fact.slice(0, 130)}`)));
  select.value = editor.recordId || "new";
  const newRecord = !selected;
  const sourceSelect = el("select", { id: "verification-passage", value: editor.passageId || "",
    required: !editor.allowWritten,
    onChange: (event) => { editor.passageId = event.target.value; changed(); } },
    el("option", { value: "" }, editor.allowWritten ? "Confirmación escrita sin archivo adjunto" : "Seleccionar el pasaje comprobado"),
    editor.supports.map((support) => el("option", { value: support.chunk_id },
      `${support.title || support.filename} · ${support.location_kind === "section" ? "sección" : "página"} ${support.page} · líneas ${support.line_start}–${support.line_end}`)));
  sourceSelect.value = editor.passageId || "";
  const passage = editor.supports.find((support) => support.chunk_id === editor.passageId);
  const form = el("form", { className: "source-review-form", onSubmit: (event) => {
    event.preventDefault(); if (form.reportValidity()) submit();
  } },
    el("h3", { id: "verification-editor-heading", tabIndex: -1 }, "Registrar o reutilizar una comprobación"),
    el("p", {}, editor.check.description),
    el("fieldset", {}, el("legend", {}, "Preguntas a las que aplica"),
      editor.requestIds.map((id) => el("label", { className: "small" },
        el("input", { type: "checkbox", checked: editor.selectedIds.includes(id),
          onChange: (event) => {
            editor.selectedIds = event.target.checked ? [...editor.selectedIds, id] : editor.selectedIds.filter((value) => value !== id);
          } }), ` ${id} `))),
    el("label", { className: "field", for: "verification-record-choice" }, el("span", {}, "Comprobación"), select),
    selected ? verificationRecord(selected, caseId, showSource) : null,
    newRecord ? [
      inputField("Hecho o control que comprobaste", "fact", editor.draft, { multiline: true }),
      el("label", { className: "field", for: "verification-passage" }, el("span", {}, "Pasaje que revisaste"), sourceSelect),
      passage ? el("details", { className: "source-text", open: true }, el("summary", {}, "Pasaje seleccionado"), el("blockquote", {}, passage.quote)) : null,
      inputField("Cómo lo sabes y con qué lo comprobaste", "basis", editor.draft, {
        multiline: true, maxLength: 6000, hint: "Describe la revisión concreta o tu conocimiento directo del hecho." }),
      inputField("Persona a la que se refiere", "person", editor.draft, { required: false, maxLength: 1000 }),
      inputField("Periodo al que corresponde", "period", editor.draft, { required: false, maxLength: 1000 }),
      inputField("Asunto o asignatura", "subject", editor.draft, { required: false, maxLength: 1000 }),
    ] : null,
    inputField("Por qué esta comprobación resuelve estas preguntas", "applicationBasis", editor.draft, {
      multiline: true, maxLength: 6000,
      hint: "Confirma su aplicación al periodo, persona y alcance de la solicitud actual; explica cualquier diferencia." }),
    inputField("Tu nombre y responsabilidad", "recordedBy", editor.draft, { maxLength: 200 }),
    editor.error ? el("p", { className: "warning-box", role: "alert" }, editor.error) : null,
    el("div", { className: "toolbar-actions" },
      button(busy ? "Guardando…" : newRecord ? "Guardar y aplicar a estas preguntas" : "Aplicar comprobación a estas preguntas", null, "primary", { type: "submit", disabled: busy }),
      button("Cerrar", close, "quiet", { disabled: busy })),
  );
  return form;
}

export function verificationRevokeForm({ target, busy, submit, close }) {
  const form = el("form", { className: "source-review-form", onSubmit: (event) => {
    event.preventDefault(); if (form.reportValidity()) submit();
  } },
    el("h4", {}, "Retirar esta aplicación"),
    el("p", { className: "small muted" }, "El registro se conserva en el historial y el pendiente vuelve a revisarse."),
    inputField("Motivo concreto", "reason", target, { multiline: true }),
    inputField("Tu nombre y responsabilidad", "recordedBy", target, { maxLength: 200 }),
    el("div", { className: "toolbar-actions" },
      button("Registrar retiro", null, "primary", { type: "submit", disabled: busy }),
      button("Cerrar", close, "quiet", { disabled: busy })),
  );
  return form;
}
