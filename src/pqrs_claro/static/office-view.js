import { el, button, dateLabel } from "./ui.js";
import { field, detail } from "./review-fields.js";
import {
  textPreview,
  generatedView,
  sizeLabel,
  officeStatus,
  letterheadView,
} from "./office-preview.js";

const fields = [
  ["institution", "Institución", 200, true],
  ["department", "Dependencia (opcional)", 200, false],
  ["city", "Ciudad", 120, true],
  ["issue_date", "Fecha del oficio", null, true, "date"],
  [
    "received_date",
    "Fecha de recepción confirmada (opcional)",
    null,
    false,
    "date",
  ],
  ["office_number", "Número de oficio (opcional)", 100, false],
  ["petition_number", "Radicado de la petición (opcional)", 100, false],
  ["recipient", "Destinatario", 300, true],
  [
    "recipient_contact",
    "Correo o dirección del destinatario (opcional)",
    300,
    false,
  ],
  ["subject", "Asunto", 500, true],
];
function metadataForm(state, actions) {
  const form = state.form;
  const eligible = state.data?.eligible && !actions.hasReviewChanges();
  const disabled = state.busy;
  const fixedField = (name) =>
    Boolean(state.data?.letterhead) &&
    ["institution", "department"].includes(name) &&
    typeof state.data.defaults?.[name] === "string";
  return el(
    "section",
    {
      className: "office-form-section",
      "aria-labelledby": "office-form-heading",
    },
    el(
      "h3",
      { id: "office-form-heading" },
      "1. Completar los datos del oficio",
    ),
    el(
      "p",
      { className: "small muted" },
      state.data?.letterhead
        ? "La institución y la dependencia vienen del membrete activo. Revisa el destinatario, el asunto y la fecha, y escribe quién figurará al cierre."
        : "El destinatario y el asunto se sugieren a partir de la petición. Revisa la fecha y escribe los datos institucionales y la persona que figurará al cierre.",
    ),
    el(
      "form",
      {
        className: "office-form",
        onSubmit: (event) => {
          event.preventDefault();
          actions.preview();
        },
      },
      el(
        "div",
        { className: "office-fields" },
        fields.map(([name, label, maxLength, required, type]) =>
          field(
            name === "department" && fixedField(name) ? "Dependencia" : label,
            `office-${name}`,
            form.metadata[name],
            (value) => {
              form.metadata[name] = value;
              actions.change();
            },
            {
              required,
              disabled,
              ...(fixedField(name)
                ? { readonly: true, hint: "Dato del membrete activo." }
                : {}),
              ...(maxLength ? { maxLength } : {}),
              ...(type ? { type } : {}),
              ...(name === "received_date"
                ? {
                    hint: "Completa esta fecha solo si está confirmada. Se incluirá en la introducción; puedes dejarla vacía.",
                  }
                : {}),
              ...(name === "subject" ? { multiline: true, rows: 2 } : {}),
            },
          ),
        ),
      ),
      el(
        "fieldset",
        { className: "office-signer" },
        el("legend", {}, "Nombre y cargo al cierre"),
        el(
          "p",
          { className: "small muted" },
          "Estos datos aparecen escritos al final del oficio. La aplicación no incorpora una firma ni toma el nombre de quien aprobó las respuestas.",
        ),
        el(
          "div",
          { className: "office-fields" },
          field(
            "Nombre de quien suscribe",
            "office-signer_name",
            form.metadata.signer_name,
            (value) => {
              form.metadata.signer_name = value;
              actions.change();
            },
            { required: true, disabled, maxLength: 200 },
          ),
          field(
            "Cargo de quien suscribe",
            "office-signer_role",
            form.metadata.signer_role,
            (value) => {
              form.metadata.signer_role = value;
              actions.change();
            },
            { required: true, disabled, maxLength: 200 },
          ),
        ),
      ),
      field(
        "Persona que prepara el documento",
        "office-prepared_by",
        form.prepared_by,
        (value) => {
          form.prepared_by = value;
          actions.change();
        },
        {
          required: true,
          disabled,
          maxLength: 240,
          hint: "Queda en el registro de generación. No reemplaza el nombre que aparece al cierre del oficio.",
        },
      ),
      detail(
        `Anexos del paquete · ${form.attachment_source_ids.length} seleccionados`,
        el(
          "div",
          {},
          el(
            "p",
            { className: "small muted" },
            "Puedes incluir documentos citados por las respuestas aprobadas. El paquete contiene el Word, su PDF y únicamente los archivos que selecciones aquí. Hasta 20 archivos y 200 MB de anexos.",
          ),
          (state.data.attachment_options || []).map((item) =>
            el(
              "label",
              { className: "review-choice" },
              el("input", {
                type: "checkbox",
                id: `office-attachment-${item.source_id}`,
                checked: form.attachment_source_ids.includes(item.source_id),
                disabled:
                  disabled ||
                  (!form.attachment_source_ids.includes(item.source_id) &&
                    form.attachment_source_ids.length >= 20),
                onChange: (event) => {
                  if (event.target.checked)
                    form.attachment_source_ids.push(item.source_id);
                  else
                    form.attachment_source_ids =
                      form.attachment_source_ids.filter(
                        (id) => id !== item.source_id,
                      );
                  actions.change(true);
                },
              }),
              el(
                "span",
                {},
                el("strong", {}, item.title),
                el("small", {}, `${item.filename} · ${sizeLabel(item.size)}`),
              ),
            ),
          ),
          form.attachment_source_ids
            .filter(
              (id) =>
                !(state.data.attachment_options || []).some(
                  (item) => item.source_id === id,
                ),
            )
            .map((id) =>
              el(
                "label",
                { className: "review-choice" },
                el("input", {
                  type: "checkbox",
                  checked: true,
                  disabled,
                  onChange: () => {
                    form.attachment_source_ids =
                      form.attachment_source_ids.filter(
                        (value) => value !== id,
                      );
                    actions.change(true);
                  },
                }),
                el(
                  "span",
                  {},
                  "Archivo antes seleccionado que ya no está disponible. Desmárcalo y revisa los anexos vigentes.",
                ),
              ),
            ),
          !state.data.attachment_options?.length
            ? el(
                "p",
                { className: "muted" },
                "No hay documentos citados disponibles para adjuntar en este momento.",
              )
            : null,
        ),
        "office-attachments",
        state,
      ),
      el(
        "p",
        { id: "office-form-state", className: "small muted", role: "status" },
        "Los datos del formulario se conservan en esta pestaña al cambiar de etapa o recargar. El registro definitivo del oficio se crea al generar los archivos.",
      ),
      el(
        "button",
        {
          type: "submit",
          className: "button button-primary",
          id: "office-preview",
          disabled: disabled || state.loading || !eligible,
        },
        "Preparar vista previa",
      ),
    ),
  );
}

export function officeView({ state, actions }) {
  const data = state?.data;
  const localChanges = actions.hasReviewChanges();
  return el(
    "section",
    {
      className: "panel response-workspace office-workspace",
      "aria-labelledby": "office-heading",
    },
    el(
      "div",
      { className: "sources-heading" },
      el(
        "div",
        {},
        el(
          "p",
          { className: "section-kicker" },
          "GENERACIÓN DEL OFICIO",
        ),
        el("h2", { id: "office-heading" }, "Preparar el documento final"),
        el(
          "p",
          { className: "muted" },
          "Completa los datos y comprueba el oficio: introducción, antecedentes compartidos, respuestas por numeral y conclusión, según lo aprobado en la revisión. Después genera Word y PDF.",
        ),
      ),
      button("Actualizar estado", () => actions.load(), "quiet", {
        id: "office-refresh",
        disabled: state.loading || state.busy,
      }),
    ),
    el(
      "p",
      { className: "response-boundary" },
      "La generación conserva el texto aprobado sin volver a redactarlo con IA. Preparar estos archivos no registra su firma, envío ni entrega.",
    ),
    data?.letterhead ? letterheadView(data.letterhead) : null,
    localChanges
      ? el(
          "div",
          { className: "warning-box", role: "status" },
          el(
            "p",
            {},
            "Este expediente tiene cambios locales de revisión sin guardar. Resuélvelos en Revisar y aprobar antes de generar o descargar el oficio.",
          ),
          button("Volver a la revisión", actions.back, "secondary"),
        )
      : null,
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
          "El navegador no pudo conservar una copia temporal de los datos. Mantén esta página abierta hasta terminar la generación.",
        )
      : null,
    !data
      ? el(
          "p",
          {
            className: "source-loading",
            role: "status",
            "aria-busy": state.loading,
          },
          "Consultando las respuestas aprobadas y las versiones del oficio…",
        )
      : null,
    data && !data.eligible
      ? el(
          "section",
          {
            className: "office-blockers",
            "aria-label": "Respuestas pendientes de aprobación",
          },
          el("h3", {}, "Qué falta para generar el oficio"),
          el(
            "p",
            {},
            `${data.approved_count} de ${data.total_count} respuestas aprobadas. Completa la revisión de las solicitudes pendientes.`,
          ),
          el(
            "ul",
            {},
            (data.blockers || []).map((item) =>
              el(
                "li",
                {},
                `${item.label}. ${item.title} · ${{ editing: "por comprobar", needs_changes: "requiere ajustes", needs_evidence: "comprobaciones pendientes", checking: "en comprobación", stale: "actualizar fuentes", ready: "falta aprobación", error: "requiere atención" }[item.status] || "revisión pendiente"}`,
              ),
            ),
          ),
          button("Continuar en revisión humana", actions.back, "secondary"),
        )
      : null,
    data?.eligible && !data.capabilities?.pdf_available
      ? el(
          "p",
          { className: "warning-box", role: "status" },
          data.capabilities?.error ||
            "La conversión a PDF no está disponible en este equipo. Puedes preparar los datos y la vista previa; para generar los archivos se necesita el conversor configurado.",
        )
      : null,
    data && state.form ? metadataForm(state, actions) : null,
    data ? textPreview(state, actions) : null,
    data ? generatedView(state, actions) : null,
    data?.history?.length
      ? detail(
          "Historial de oficios generados",
          el(
            "div",
            { className: "office-history" },
            el(
              "p",
              { className: "small muted" },
              "Cada generación conserva sus propios datos. Las versiones anteriores siguen disponibles mientras sus aprobaciones y archivos permanezcan vigentes.",
            ),
            data.history.map((run) =>
              button(
                [
                  el(
                    "strong",
                    {},
                    `${dateLabel(run.created_at, true)} · ${officeStatus(run)}`,
                  ),
                  el(
                    "span",
                    { className: "small muted" },
                    run.metadata?.office_number ||
                      run.metadata?.subject ||
                      "Consultar datos de esta versión",
                  ),
                ],
                () => actions.selectRun(run.id),
                "quiet",
                {
                  className: "response-list-item",
                  disabled: state.busy,
                  "aria-current": state.run?.id === run.id ? "true" : null,
                },
              ),
            ),
          ),
          "office-history",
          state,
        )
      : null,
  );
}
