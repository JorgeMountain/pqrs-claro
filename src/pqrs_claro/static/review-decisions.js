import { el, button, dateLabel } from "./ui.js";
import { field, detail } from "./review-fields.js";
import { effectiveResolution } from "./review-pending.js";

const passedCheckLabels = {
  response_present: "Presencia de texto en la respuesta",
  paragraph_cited: "Citas de respaldo del párrafo",
  current_references: "Referencias vigentes del párrafo",
  pending_closed: "Decisión registrada sobre el pendiente",
  current_resolution_references: "Referencias vigentes de la decisión",
  document_resolution_has_file: "Respaldo documental de la resolución",
};

export function assessmentView(row, local, state) {
  const result = row.assessment;
  const description = local.dirty
    ? "La comprobación guardada corresponde al texto anterior. Guarda y vuelve a comprobar."
    : row.status === "checking"
      ? "Comprobando cobertura, citas y decisiones sobre los pendientes. Puedes consultar las fuentes mientras termina."
      : !result
        ? "Esta versión todavía no tiene una comprobación vigente."
        : result.status === "passed"
          ? "Comprobación superada para esta versión. La aprobación sigue siendo una decisión humana."
          : "Hay puntos que deben ajustarse antes de aprobar esta versión.";
  return el(
    "section",
    {
      className: "review-assessment",
      "aria-label": "Comprobación de la revisión",
    },
    el("h4", {}, "3. Comprobar la respuesta"),
    el(
      "p",
      { id: "review-assessment-state", role: "status", "aria-live": "polite" },
      description,
    ),
    row.error
      ? el("p", { className: "warning-box", role: "alert" }, row.error)
      : null,
    result?.issues?.length
      ? el(
          "ul",
          { className: "review-issue-list" },
          result.issues.map((issue) =>
            el(
              "li",
              {},
              issue.paragraph_index != null
                ? el(
                    "a",
                    {
                      href: `#review-paragraph-${issue.paragraph_index}`,
                      onClick: () =>
                        document
                          .getElementById(
                            `review-paragraph-${issue.paragraph_index}`,
                          )
                          ?.focus(),
                    },
                    `Párrafo ${issue.paragraph_index + 1}: `,
                  )
                : null,
              issue.description,
            ),
          ),
        )
      : null,
    result
      ? detail(
          "Ver comprobaciones y fecha",
          el(
            "div",
            {},
            el(
              "p",
              { className: "small muted" },
              `Comprobado: ${dateLabel(result.assessed_at, true)}`,
            ),
            el(
              "ul",
              { className: "response-checks" },
              (result.local_checks || []).map((check) =>
                el(
                  "li",
                  {},
                  check.passed
                    ? `✓ ${passedCheckLabels[check.code] || "Control estructural superado"}`
                    : `Requiere atención: ${check.description}`,
                ),
              ),
            ),
          ),
          `${row.request_id}-checks`,
          state,
        )
      : null,
  );
}

export function approvalView(row, local, state, actions, disabled) {
  if (row.approval && !local.dirty && !row.stale)
    return el(
      "section",
      { className: "review-approved", id: "review-approval" },
      el("h4", {}, "Versión aprobada"),
      el(
        "p",
        {},
        `${row.approval.approved_by} · ${dateLabel(row.approval.approved_at, true)}`,
      ),
      row.approval.note ? el("p", {}, row.approval.note) : null,
      el(
        "p",
        { className: "small" },
        "Esta aprobación conserva una copia inmutable de la respuesta y sus referencias. Una nueva edición exigirá volver a comprobar y aprobar.",
      ),
    );
  const ready =
    row.status === "ready" &&
    row.assessment?.status === "passed" &&
    !row.stale &&
    !local.dirty &&
    !(row.pending || []).some(
      (item) => effectiveResolution(item, local).action === "open",
    );
  if (!ready)
    return el(
      "p",
      { className: "review-approval-help" },
      "La aprobación se habilita cuando la versión guardada supera la comprobación y todos los pendientes tienen una decisión respaldada.",
    );
  const set = (name) => (value) => {
    local.approval[name] = value;
    actions.formChanged(row, local);
  };
  return el(
    "section",
    { className: "review-approval", id: "review-approval" },
    el("h4", {}, "4. Aprobar esta versión"),
    el(
      "p",
      { className: "small muted" },
      "La comprobación no aprueba por ti. Quedará registrada la persona que declara esta decisión en la aplicación local.",
    ),
    el(
      "form",
      {
        onSubmit: (event) => {
          event.preventDefault();
          actions.approve(row);
        },
      },
      field(
        "Persona que aprueba",
        "review-approver",
        local.approval.approved_by,
        set("approved_by"),
        { required: true, maxLength: 240, disabled },
      ),
      field(
        "Nota de aprobación (opcional)",
        "review-approval-note",
        local.approval.note,
        set("note"),
        { multiline: true, rows: 2, maxLength: 3000, disabled },
      ),
      el(
        "label",
        { className: "review-choice" },
        el("input", {
          type: "checkbox",
          required: true,
          checked: local.approval.confirmed,
          disabled,
          onChange: (event) => {
            local.approval.confirmed = event.target.checked;
            actions.formChanged(row, local);
          },
        }),
        el(
          "span",
          {},
          `Revisé el texto, sus fuentes y las decisiones sobre los pendientes. Apruebo expresamente la revisión ${row.revision} de esta solicitud.`,
        ),
      ),
      el(
        "button",
        { type: "submit", className: "button button-primary", disabled },
        "Aprobar esta versión",
      ),
    ),
  );
}

const eventLabel = (event) =>
  ({
    started: "Inicio de revisión",
    initialized: "Inicio de revisión",
    edited: "Edición guardada",
    saved: "Edición guardada",
    fact_added: "Aporte registrado",
    fact_removed: "Aporte retirado",
    assessed: "Comprobación terminada",
    checking: "Comprobación iniciada",
    assessment_started: "Comprobación iniciada",
    assessment_failed: "Comprobación interrumpida",
    inputs_changed: "Fuentes o solicitudes modificadas",
    revision_changed: "Versión de revisión modificada",
    approved: "Versión aprobada",
    synchronized: "Fuentes actualizadas",
    stale: "Entradas modificadas",
    error: "Proceso interrumpido",
  })[event] || "Cambio registrado";
export function historyView(row, state, actions) {
  const history = state.history.get(row.request_id);
  return detail(
    "Historial de esta respuesta",
    el(
      "div",
      {},
      button(
        history ? "Actualizar historial" : "Cargar historial",
        () => actions.history(row),
        "quiet",
        { disabled: state.busy },
      ),
      history
        ? el(
            "p",
            { className: "small muted" },
            `Se muestran hasta ${history.limit || 100} movimientos, del más reciente al más antiguo.`,
          )
        : null,
      (history?.revisions || []).map((item, index) =>
        detail(
          `Revisión ${item.revision} · ${eventLabel(item.event)} · ${dateLabel(item.created_at, true)}`,
          el(
            "div",
            {},
            el(
              "p",
              { className: "small muted" },
              item.actor
                ? `Responsable: ${item.actor}`
                : "Registro automático del proceso",
            ),
            (item.body?.paragraphs || item.body?.review?.paragraphs || []).map(
              (paragraph, n) =>
                el(
                  "div",
                  {},
                  el(
                    "p",
                    { className: "review-history-text" },
                    `${n + 1}. ${paragraph.text}`,
                  ),
                  el(
                    "p",
                    { className: "small muted" },
                    `${paragraph.cited_chunk_ids?.length || 0} fragmentos y ${paragraph.cited_fact_ids?.length || 0} aportes citados.`,
                  ),
                ),
            ),
            el(
              "p",
              { className: "small muted" },
              `${item.body?.facts?.length || 0} aportes registrados en esta revisión.`,
            ),
            (item.body?.pending || [])
              .filter((pending) => pending.resolution)
              .map((pending) =>
                el(
                  "p",
                  { className: "small" },
                  el("strong", {}, `${pending.description}: `),
                  pending.resolution.note,
                  pending.resolution.by ? ` · ${pending.resolution.by}` : "",
                ),
              ),
          ),
          `${row.request_id}-history-${index}`,
          state,
        ),
      ),
    ),
    `${row.request_id}-history`,
    state,
  );
}
