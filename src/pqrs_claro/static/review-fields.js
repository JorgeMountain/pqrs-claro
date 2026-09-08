import { el, button, dateLabel } from "./ui.js";

export function field(label, id, value, update, options = {}) {
  const { multiline = false, hint = null, ...attrs } = options;
  return el(
    "label",
    { className: "field", for: id },
    el("span", {}, label),
    el(multiline ? "textarea" : "input", {
      id,
      value: value || "",
      ...attrs,
      onInput: (event) => update(event.target.value),
    }),
    hint ? el("small", { className: "field-hint" }, hint) : null,
  );
}
export function detail(title, body, key, state, initial = false) {
  const id = `review-detail-${state.caseId}-${key}`;
  const remember = (open) =>
    open ? state.expanded.add(key) : state.expanded.delete(key);
  const previous = document.getElementById(id);
  // Native toggle events may still be queued when a form change renders again.
  if (previous?.isConnected) remember(previous.open);
  return el(
    "details",
    {
      id,
      className: "response-detail",
      open: state.expanded.has(key) || initial,
      onToggle: (event) => {
        if (event.currentTarget.isConnected) remember(event.currentTarget.open);
      },
    },
    el(
      "summary",
      {
        onClick: (event) => {
          if (!event.defaultPrevented)
            remember(!event.currentTarget.parentElement.open);
        },
      },
      title,
    ),
    body,
  );
}
export const location = (source) =>
  `${source.location_kind === "section" ? "Sección" : "Página"} ${source.page} · Líneas ${source.line_start}–${source.line_end}`;
export const observedDate = (value) =>
  /^\d{4}-\d{2}-\d{2}$/.test(value || "")
    ? value.split("-").reverse().join("/")
    : dateLabel(value);

export function references(
  row,
  selection,
  key,
  actions,
  onChange,
  disabled = false,
) {
  const supports = row.available_supports || [];
  const facts = row.facts || [];
  const groups = new Map();
  for (const source of supports) {
    const id = source.document_id || source.source_id;
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id).push(source);
  }
  const toggle = (name, id, checked) => {
    const ids = new Set(selection[name] || []);
    if (checked) ids.add(id);
    else ids.delete(id);
    selection[name] = [...ids];
    onChange();
  };
  const check = (name, id, content) => {
    const selected = selection[name]?.includes(id);
    return el(
      "label",
      { className: "review-choice" },
      el("input", {
        id: `${key}-${name}-${id}`,
        type: "checkbox",
        checked: Boolean(selected),
        disabled: disabled || (!selected && selection[name]?.length >= 8),
        onChange: (event) => toggle(name, id, event.target.checked),
      }),
      el("span", {}, content),
    );
  };
  const body = el(
    "div",
    { className: "review-reference-options" },
    el(
      "p",
      { className: "small muted" },
      "Selecciona los fragmentos que respaldan este punto. Elegir un archivo encontrado para cotejo exige comprobar su pertinencia con la respuesta. Hasta ocho fragmentos y ocho aportes por punto.",
    ),
    [...groups.entries()].map(([id, fragments]) =>
      el(
        "fieldset",
        { className: "review-source-group" },
        el(
          "legend",
          {},
          fragments[0].title || fragments[0].filename || "Documento",
        ),
        fragments.map((source) =>
          el(
            "div",
            { className: "review-reference" },
            check("cited_chunk_ids", source.chunk_id, [
              el("strong", {}, location(source)),
              source.origin_selection === "candidate"
                ? el("small", {}, "Archivo encontrado para cotejo")
                : null,
              source.verification_status === "reported_by_user"
                ? el(
                    "small",
                    {},
                    "Verificación previa informada por el usuario",
                  )
                : null,
              el("span", { className: "review-quote" }, source.quote),
            ]),
            button(
              "Abrir fuente original ↗",
              () => actions.showSource(source.source_id, source),
              "quiet",
              {
                className: "button button-quiet button-small",
                id: `${key}-source-${id}-${source.chunk_id}`,
              },
            ),
          ),
        ),
      ),
    ),
    facts.length
      ? el(
          "fieldset",
          { className: "review-source-group" },
          el("legend", {}, "Aportes escritos de esta solicitud"),
          facts.map((fact) =>
            check("cited_fact_ids", fact.id, [
              el(
                "strong",
                {},
                `${fact.author} · ${observedDate(fact.observed_at)}`,
              ),
              el("span", {}, fact.text),
              el("small", {}, `Cómo lo conoce: ${fact.basis}`),
            ]),
          ),
        )
      : null,
  );
  for (const id of selection.cited_chunk_ids || []) {
    if (!supports.some((source) => source.chunk_id === id))
      body.append(
        check(
          "cited_chunk_ids",
          id,
          "Fragmento anterior no disponible. Desmarca esta referencia y selecciona un soporte vigente.",
        ),
      );
  }
  for (const id of selection.cited_fact_ids || []) {
    if (!facts.some((fact) => fact.id === id))
      body.append(
        check(
          "cited_fact_ids",
          id,
          "Aporte retirado. Desmarca esta referencia y revisa el texto.",
        ),
      );
  }
  if (!supports.length && !facts.length)
    body.append(
      el(
        "p",
        { className: "muted" },
        "Todavía no hay soportes ni aportes disponibles para esta solicitud.",
      ),
    );
  return body;
}
