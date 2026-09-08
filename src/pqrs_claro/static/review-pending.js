import { el, button, dateLabel } from "./ui.js";
import { field, detail, references, observedDate } from "./review-fields.js";

export function effectiveResolution(item, local) {
  return (
    local.resolutions[item.id] ||
    (item.resolution
      ? { ...item.resolution, pending_id: item.id }
      : {
          pending_id: item.id,
          action: "open",
          note: "",
          cited_chunk_ids: [],
          cited_fact_ids: [],
        })
  );
}
export function pendingView(row, local, state, actions, disabled) {
  const pending = row.pending || [];
  const open = pending.filter(
    (item) => effectiveResolution(item, local).action === "open",
  ).length;
  return el(
    "section",
    { className: "review-pending", "aria-label": "Qué falta resolver" },
    el(
      "div",
      { className: "response-section-heading" },
      el("h4", {}, "1. Qué falta resolver"),
      el(
        "span",
        { className: "source-tag pending" },
        `${open} pendientes abiertos`,
      ),
    ),
    el(
      "p",
      { className: "small muted" },
      pending.length
        ? "Cada decisión queda justificada y se comprueba junto con la respuesta. Una declaración no sustituye una copia o certificación solicitada."
        : "No hay pendientes registrados. Revisa igualmente la cobertura y el sustento de la respuesta.",
    ),
    pending.map((item, index) => {
      const resolution = structuredClone(effectiveResolution(item, local));
      const update = (rerender = false) => {
        local.resolutions[item.id] = resolution;
        actions.changed(row, local, rerender);
      };
      const select = el(
        "select",
        {
          id: `pending-action-${item.id}`,
          disabled,
          onChange: (event) => {
            resolution.action = event.target.value;
            if (resolution.action === "open") {
              resolution.cited_chunk_ids = [];
              resolution.cited_fact_ids = [];
            }
            update(true);
          },
        },
        el("option", { value: "open" }, "Mantener pendiente"),
        el("option", { value: "resolved" }, "Resuelto con respaldo"),
        el("option", { value: "not_applicable" }, "No aplica a esta respuesta"),
      );
      select.value = resolution.action;
      return detail(
        `${index + 1}. ${item.description}`,
        el(
          "div",
          { className: "review-pending-body" },
          el(
            "p",
            { className: "small" },
            `Decisión: ${{ open: "pendiente", resolved: "resuelto con respaldo", not_applicable: "no aplica, con justificación" }[resolution.action]}`,
          ),
          el(
            "label",
            { className: "field", for: `pending-action-${item.id}` },
            el("span", {}, "Cómo queda este punto"),
            select,
          ),
          resolution.action !== "open"
            ? field(
                "Justificación de la decisión",
                `pending-note-${item.id}`,
                resolution.note,
                (value) => {
                  resolution.note = value;
                  update();
                },
                {
                  multiline: true,
                  rows: 3,
                  maxLength: 3000,
                  disabled,
                  hint:
                    resolution.action === "not_applicable"
                      ? "Explica el alcance o la duplicidad de forma concreta. La comprobación puede pedir un ajuste."
                      : "Explica qué fragmento o aporte resuelve el punto y por qué.",
                },
              )
            : null,
          resolution.action !== "open"
            ? references(
                row,
                resolution,
                `pending-${item.id}`,
                actions,
                () => update(true),
                disabled,
              )
            : null,
          item.resolution?.by
            ? el(
                "p",
                { className: "small muted" },
                `Última decisión guardada por ${item.resolution.by} · ${dateLabel(item.resolution.at, true)}`,
              )
            : null,
        ),
        `${row.request_id}-pending-${item.id}`,
        state,
      );
    }),
    el(
      "div",
      { className: "button-group" },
      button(
        "Agregar un archivo a la biblioteca",
        actions.openLibrary,
        "quiet",
      ),
      button("Consultar o actualizar fuentes", actions.openSources, "quiet"),
    ),
  );
}

export function factsView(row, local, state, actions, disabled) {
  const set = (name) => (value) => {
    local.fact[name] = value;
    actions.formChanged(row, local);
  };
  return detail(
    `Aportes escritos (${row.facts?.length || 0}) · Registrar un hecho`,
    el(
      "div",
      {},
      el(
        "p",
        { className: "small muted" },
        "Registra una información que una persona conoce o comprobó, indicando cómo la obtuvo. Se conserva como declaración atribuida; no autentica documentos.",
      ),
      (row.facts || []).map((fact) =>
        el(
          "article",
          { className: "review-fact" },
          el(
            "strong",
            {},
            `${fact.author} · ${observedDate(fact.observed_at)}`,
          ),
          el("p", {}, fact.text),
          el("p", { className: "small muted" }, `Fundamento: ${fact.basis}`),
          button(
            "Retirar aporte",
            () => actions.removeFact(row, fact),
            "quiet",
            { disabled, className: "button button-quiet button-small" },
          ),
        ),
      ),
      el(
        "form",
        {
          className: "review-fact-form",
          onSubmit: (event) => {
            event.preventDefault();
            actions.addFact(row);
          },
        },
        field(
          "Hecho que se aporta",
          "review-fact-text",
          local.fact.text,
          set("text"),
          {
            multiline: true,
            rows: 3,
            maxLength: 6000,
            required: true,
            disabled,
          },
        ),
        field(
          "Persona que conoce o verificó el hecho",
          "review-fact-author",
          local.fact.author,
          set("author"),
          { required: true, maxLength: 200, disabled },
        ),
        field(
          "Cómo conoce o verificó esta información",
          "review-fact-basis",
          local.fact.basis,
          set("basis"),
          {
            multiline: true,
            rows: 2,
            required: true,
            maxLength: 3000,
            disabled,
          },
        ),
        field(
          "Fecha en que comprobó el hecho",
          "review-fact-date",
          local.fact.observed_at,
          set("observed_at"),
          { type: "date", required: true, disabled },
        ),
        local.dirty
          ? el(
              "p",
              { className: "small muted" },
              "Al registrar el aporte se guardarán primero los cambios de esta respuesta con el responsable de edición indicado.",
            )
          : null,
        el(
          "button",
          {
            type: "submit",
            className: "button button-secondary",
            disabled: disabled || row.facts?.length >= 30,
          },
          "Registrar aporte",
        ),
      ),
    ),
    `${row.request_id}-facts`,
    state,
  );
}
