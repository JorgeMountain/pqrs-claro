import { el, button } from "./ui.js";
import { field, detail, references } from "./review-fields.js";
import {
  pendingView,
  factsView,
  effectiveResolution,
} from "./review-pending.js";
import {
  assessmentView,
  approvalView,
  historyView,
} from "./review-decisions.js";

const statusLabel = (status) =>
  ({
    editing: "Por comprobar",
    checking: "Comprobando…",
    ready: "Lista para aprobar",
    needs_changes: "Requiere ajustes",
    needs_evidence: "Falta respaldo",
    approved: "Aprobada",
    error: "Requiere atención",
    stale: "Actualizar fuentes",
  })[status] || "Por revisar";

function paragraphEditor(row, local, state, actions, disabled) {
  return el(
    "section",
    { className: "review-editor", "aria-label": "Texto de la respuesta" },
    el("h4", {}, "2. Editar la respuesta y sus citas"),
    el(
      "p",
      { className: "small muted" },
      "Cada párrafo conserva su propio respaldo. Selecciona fragmentos exactos o aportes atribuidos y revisa qué afirman realmente.",
    ),
    local.paragraphs.map((paragraph, index) =>
      el(
        "div",
        { className: "review-paragraph" },
        field(
          `Párrafo ${index + 1}`,
          `review-paragraph-${index}`,
          paragraph.text,
          (value) => {
            paragraph.text = value;
            actions.changed(row, local);
          },
          {
            multiline: true,
            rows: Math.min(
              12,
              Math.max(4, Math.ceil(paragraph.text.length / 100)),
            ),
            maxLength: 6000,
            disabled,
          },
        ),
        detail(
          `Respaldo del párrafo ${index + 1} · ${paragraph.cited_chunk_ids?.length || 0} fragmentos y ${paragraph.cited_fact_ids?.length || 0} aportes`,
          references(
            row,
            paragraph,
            `paragraph-${index}`,
            actions,
            () => actions.changed(row, local, true),
            disabled,
          ),
          `${row.request_id}-paragraph-${index}`,
          state,
        ),
        button(
          `Quitar párrafo ${index + 1}`,
          () => {
            local.paragraphs.splice(index, 1);
            actions.changed(row, local, true);
          },
          "quiet",
          { disabled, className: "button button-quiet button-small" },
        ),
      ),
    ),
    !local.paragraphs.length
      ? el(
          "p",
          { className: "response-placeholder" },
          "Agrega el primer párrafo. Una respuesta vacía se puede guardar como trabajo pendiente, pero no aprobar.",
        )
      : null,
    button(
      "Agregar párrafo",
      () => {
        local.paragraphs.push({
          text: "",
          cited_chunk_ids: [],
          cited_fact_ids: [],
        });
        actions.changed(row, local, true);
        document
          .getElementById(`review-paragraph-${local.paragraphs.length - 1}`)
          ?.focus();
      },
      "secondary",
      { disabled: disabled || local.paragraphs.length >= 30 },
    ),
  );
}

function requestView(row, state, actions) {
  const local = actions.localFor(row);
  const disabled = state.busy || row.status === "checking";
  const conflict = local.dirty && local.revision !== row.revision;
  const stale = state.data.stale || row.stale;
  return el(
    "article",
    {
      className: "response-card review-card",
      "aria-labelledby": "review-request-title",
    },
    el("p", { className: "section-kicker" }, `SOLICITUD ${row.label}`),
    el("h3", { id: "review-request-title" }, row.title),
    el("p", { className: "response-request" }, row.description),
    el(
      "p",
      { id: "review-current-status", className: "source-tag" },
      local.dirty
        ? "Edición sin guardar"
        : statusLabel(stale ? "stale" : row.status),
    ),
    conflict
      ? el(
          "div",
          { className: "warning-box", role: "alert" },
          el(
            "p",
            {},
            `Tu edición parte de la revisión ${local.revision}; existe la revisión ${row.revision}. Tu texto permanece en el editor. Compara antes de decidir qué conservar.`,
          ),
          detail(
            "Comparar con el texto guardado",
            el(
              "div",
              {},
              (row.paragraphs || []).map((paragraph, index) =>
                el(
                  "p",
                  { className: "review-history-text" },
                  `${index + 1}. ${paragraph.text}`,
                ),
              ),
            ),
            `${row.request_id}-conflict`,
            state,
          ),
          button(
            "Conservar mi texto sobre la revisión actual",
            () => actions.rebase(row),
            "secondary",
            { disabled },
          ),
        )
      : null,
    field(
      "Responsable de la edición",
      "review-editor-name",
      local.edited_by,
      (value) => {
        local.edited_by = value;
        actions.formChanged(row, local);
      },
      {
        maxLength: 240,
        disabled,
        hint: "Se registrará al guardar cambios o retirar un aporte. Escribe el nombre de quien realiza la acción.",
      },
    ),
    pendingView(row, local, state, actions, disabled),
    factsView(row, local, state, actions, disabled),
    paragraphEditor(row, local, state, actions, disabled),
    el(
      "div",
      { className: "review-save-bar" },
      el(
        "p",
        {
          id: "review-save-state",
          role: "status",
          "aria-live": "polite",
          className: "small",
        },
        local.dirty
          ? "Cambios sin guardar · Tu edición se conserva en esta pestaña."
          : `Revisión ${row.revision} guardada.`,
      ),
      el(
        "div",
        { className: "button-group" },
        button("Guardar cambios", () => actions.save(row), "primary", {
          id: "review-save",
          disabled: disabled || !local.dirty || conflict,
        }),
        button(
          row.status === "checking" ? "Comprobando…" : "Comprobar esta versión",
          () => actions.assess(row),
          "secondary",
          { id: "review-assess", disabled: disabled || local.dirty || stale },
        ),
      ),
      el(
        "div",
        { className: "button-group" },
        button("Descargar mi edición", () => actions.download(row), "quiet", {
          className: "button button-quiet button-small",
        }),
        local.dirty
          ? button(
              "Volver a la versión guardada",
              () => actions.reset(row),
              "quiet",
              { disabled, className: "button button-quiet button-small" },
            )
          : null,
      ),
    ),
    assessmentView(row, local, state),
    approvalView(row, local, state, actions, disabled),
    historyView(row, state, actions),
  );
}

export function reviewView({ state, drafts, mapping, actions }) {
  const data = state?.data;
  const rows = data?.requests || [];
  const sourceReady = mapping?.status === "ready" && !mapping.stale;
  const canStart = rows.length
    ? sourceReady
    : sourceReady &&
      ["ready", "partial"].includes(drafts?.status) &&
      !drafts.stale &&
      !drafts.results?.some((row) => row.error);
  const selected =
    rows.find((row) => row.request_id === state.selected) || rows[0];
  const dirtyCount = rows.filter((row) => actions.localFor(row).dirty).length;
  const approvedCount = rows.filter(
    (row) => row.approval && !row.stale && !actions.localFor(row).dirty,
  ).length;
  const orphaned = [...state.locals.entries()].filter(
    ([id, local]) => local.dirty && !rows.some((row) => row.request_id === id),
  );
  return el(
    "section",
    {
      className: "panel response-workspace review-workspace",
      "aria-labelledby": "reviews-heading",
    },
    el(
      "div",
      { className: "sources-heading" },
      el(
        "div",
        {},
        el("p", { className: "section-kicker" }, "FASE 6 · REVISIÓN HUMANA"),
        el("h2", { id: "reviews-heading" }, "Revisar, comprobar y decidir"),
        el(
          "p",
          { className: "muted" },
          "Resuelve los faltantes, ajusta la respuesta y aprueba una versión concreta.",
        ),
      ),
      button("Actualizar estado", () => actions.load(), "quiet", {
        disabled: state.loading || state.busy,
        id: "review-refresh",
      }),
    ),
    el(
      "p",
      { className: "response-boundary" },
      "La revisión conserva el texto y las decisiones de cada persona. Cuando todas las respuestas estén aprobadas, podrás generar el oficio en la fase 7.",
    ),
    state.error || data?.error
      ? el(
          "p",
          { className: "warning-box", role: "alert" },
          state.error || data.error,
        )
      : null,
    state.storageWarning
      ? el(
          "p",
          { className: "warning-box", role: "alert" },
          "El navegador no pudo conservar una copia temporal. Guarda los cambios o descarga tu edición antes de cerrar la página.",
        )
      : null,
    state.loaded && orphaned.length
      ? el(
          "section",
          {
            className: "warning-box",
            "aria-label": "Ediciones de solicitudes retiradas",
          },
          el("h3", {}, "Hay ediciones locales de solicitudes retiradas"),
          el(
            "p",
            { className: "small" },
            "Estas solicitudes ya no forman parte de la identificación vigente. Puedes recuperar tu texto; el historial guardado se conserva.",
          ),
          orphaned.map(([id, local]) =>
            el(
              "div",
              {},
              el("p", {}, local.title || `Solicitud ${local.label || id}`),
              button(
                "Descargar esta edición",
                () => actions.download({ request_id: id, label: local.label }),
                "quiet",
              ),
              button(
                "Descartar copia local",
                () => actions.discardOrphan(id),
                "quiet",
              ),
            ),
          ),
        )
      : null,
    data?.stale
      ? el(
          "p",
          { className: "warning-box", role: "status" },
          "Las solicitudes o las fuentes cambiaron. Actualiza la búsqueda de fuentes y sincroniza esta revisión; el texto humano se conserva. Será necesario volver a comprobar y aprobar.",
        )
      : null,
    rows.length && !sourceReady
      ? el(
          "p",
          { className: "small muted" },
          "Para incorporar documentos nuevos, actualiza primero la búsqueda en 4. Fuentes. Después usa Actualizar fuentes de la revisión.",
        )
      : null,
    el(
      "div",
      { className: "response-actions" },
      button(
        rows.length
          ? "Actualizar fuentes de la revisión"
          : "Empezar revisión humana",
        actions.start,
        "primary",
        {
          id: "review-start",
          disabled:
            state.busy ||
            state.loading ||
            !canStart ||
            dirtyCount > 0 ||
            rows.some((row) => row.status === "checking"),
        },
      ),
      rows.length
        ? el(
            "p",
            { className: "small muted", id: "review-totals" },
            `${approvedCount} de ${rows.length} respuestas aprobadas${dirtyCount ? ` · ${dirtyCount} con cambios sin guardar` : ""}`,
          )
        : null,
    ),
    !rows.length
      ? el(
          "p",
          { className: "response-placeholder", role: "status" },
          state.loading
            ? "Cargando revisiones guardadas…"
            : canStart
              ? "Los borradores están disponibles. Empieza la revisión para trabajar cada respuesta y conservar su historial."
              : "Completa las fuentes y prepara los borradores en la fase 5 para comenzar la revisión.",
        )
      : null,
    rows.length
      ? el(
          "div",
          { className: "response-layout" },
          el(
            "nav",
            {
              className: "response-list",
              "aria-label": "Respuestas por revisar",
            },
            rows.map((row) => {
              const local = actions.localFor(row);
              const pending = (row.pending || []).filter(
                (item) => effectiveResolution(item, local).action === "open",
              ).length;
              return button(
                [
                  el(
                    "span",
                    { className: "response-list-title" },
                    `${row.label}. ${row.title}`,
                  ),
                  el(
                    "span",
                    { className: "small muted" },
                    local.dirty
                      ? "Cambios sin guardar"
                      : statusLabel(row.stale ? "stale" : row.status),
                  ),
                  el(
                    "span",
                    { className: "small" },
                    `${pending} pendientes abiertos`,
                  ),
                ],
                () => actions.select(row.request_id),
                "quiet",
                {
                  id: `review-select-${row.request_id}`,
                  className: `response-list-item ${row.request_id === selected?.request_id ? "active" : ""}`,
                  "aria-current":
                    row.request_id === selected?.request_id ? "true" : null,
                },
              );
            }),
          ),
          selected ? requestView(selected, state, actions) : null,
        )
      : null,
    rows.length
      ? el(
          "div",
          { className: "response-entry" },
          el(
            "div",
            {},
            el("strong", {}, "Siguiente paso: generar el oficio"),
            el(
              "p",
              { className: "small muted" },
              "Prepara Word y PDF conservando el texto de las respuestas aprobadas.",
            ),
          ),
          button("Continuar a generar oficio", actions.openOffice, "primary", {
            id: "continue-office",
            disabled:
              state.busy ||
              approvedCount !== rows.length ||
              data?.stale ||
              actions.hasLocalChanges(),
          }),
        )
      : null,
  );
}
