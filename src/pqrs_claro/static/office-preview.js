import { el, button, dateLabel } from "./ui.js";
import { detail, observedDate } from "./review-fields.js";

export const sizeLabel = (bytes) =>
  bytes >= 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
export const officeStatus = (run) =>
  run?.stale
    ? "Versión desactualizada"
    : {
        generating: "Generando archivos…",
        ready: "Archivos preparados",
        failed: "No se completó la generación",
        stale: "Versión desactualizada",
      }[run?.status] || "Por preparar";

export function textPreview(state, actions) {
  const preview = state.preview;
  const changed = actions.changedPreview();
  const document = preview?.document;
  const meta = document?.metadata;
  return el(
    "section",
    {
      className: "office-preview",
      "aria-labelledby": "office-preview-heading",
    },
    el("h3", { id: "office-preview-heading" }, "2. Comprobar la vista previa"),
    el(
      "p",
      { id: "office-preview-state", role: "status", className: "small muted" },
      !preview
        ? "Completa los datos y prepara la vista previa. Aquí aparecerán el texto aprobado, sus referencias y los anexos elegidos."
        : changed
          ? "Los datos o las aprobaciones cambiaron. Prepara de nuevo la vista previa para generar esta versión."
          : "Vista previa de los datos y del contenido aprobado. La presentación final se podrá comprobar en el PDF generado.",
    ),
    document
      ? detail(
          "Leer el oficio y sus referencias",
          el(
            "article",
            { className: "office-paper" },
            el("p", { className: "office-institution" }, meta.institution),
            meta.department ? el("p", {}, meta.department) : null,
            el("p", {}, `${meta.city}, ${observedDate(meta.issue_date)}`),
            meta.office_number
              ? el("p", {}, `Oficio: ${meta.office_number}`)
              : null,
            el("p", {}, meta.recipient),
            meta.recipient_contact ? el("p", {}, meta.recipient_contact) : null,
            meta.petition_number
              ? el("p", {}, `Petición: ${meta.petition_number}`)
              : null,
            el("p", {}, el("strong", {}, `Asunto: ${meta.subject}`)),
            (document.requests || []).map((request) =>
              el(
                "section",
                { className: "office-preview-request" },
                el("h4", {}, `${request.label}. ${request.title}`),
                el(
                  "p",
                  { className: "office-request-description" },
                  request.description,
                ),
                (request.paragraphs || []).map((paragraph) =>
                  el(
                    "div",
                    {},
                    el("p", { className: "office-exact-text" }, paragraph.text),
                    paragraph.reference_numbers?.length
                      ? el(
                          "p",
                          { className: "small muted" },
                          `Referencias: ${paragraph.reference_numbers.map((number) => `[${number}]`).join(", ")}`,
                        )
                      : null,
                  ),
                ),
              ),
            ),
            el("p", {}, "Atentamente,"),
            el(
              "p",
              {},
              el("strong", {}, meta.signer_name),
              el("br"),
              meta.signer_role,
            ),
            document.references?.length
              ? el(
                  "section",
                  {},
                  el("h4", {}, "Referencias"),
                  el(
                    "ol",
                    { className: "office-reference-list" },
                    document.references.map((ref) =>
                      el("li", { value: ref.number }, ref.text),
                    ),
                  ),
                )
              : null,
            el(
              "section",
              {},
              el("h4", {}, "Archivos que incluirá el paquete"),
              document.attachments?.length
                ? el(
                    "ul",
                    {},
                    document.attachments.map((item) =>
                      el(
                        "li",
                        {},
                        `${item.filename} · ${sizeLabel(item.size)}`,
                      ),
                    ),
                  )
                : el(
                    "p",
                    {},
                    "El paquete incluirá el oficio en Word y PDF, sin anexos seleccionados.",
                  ),
            ),
          ),
          "office-text-preview",
          state,
        )
      : null,
    el(
      "div",
      { className: "response-actions" },
      button(
        state.run?.status === "generating"
          ? "Generando Word y PDF…"
          : "Generar Word y PDF",
        actions.generate,
        "primary",
        {
          id: "office-generate",
          disabled:
            state.busy ||
            state.loading ||
            changed ||
            !state.data?.eligible ||
            actions.hasReviewChanges() ||
            !state.data?.capabilities?.pdf_available ||
            state.run?.status === "generating",
        },
      ),
    ),
  );
}

export function generatedView(state, actions) {
  const run = state.run;
  if (!run) return null;
  const ready = run.status === "ready" && !run.stale;
  const canDownload =
    ready && state.data.eligible && !actions.hasReviewChanges();
  const page = Math.min(state.page, Math.max(1, run.page_count || 1));
  return el(
    "section",
    {
      className: "office-generated",
      "aria-labelledby": "office-generated-heading",
    },
    el(
      "div",
      { className: "response-section-heading" },
      el("h3", { id: "office-generated-heading" }, "3. Archivos y PDF final"),
      el("span", { className: "source-tag" }, officeStatus(run)),
    ),
    el(
      "p",
      { className: "small muted" },
      `Preparado por ${run.prepared_by} · ${dateLabel(run.created_at, true)}`,
    ),
    el(
      "p",
      { id: "office-file-context", className: "small" },
      run.status !== "ready"
        ? "Consulta los datos registrados para este intento de generación en el detalle de trazabilidad."
        : actions.selectedMatchesForm()
          ? "Estos archivos corresponden a la vista previa y los datos actuales del formulario."
          : "Esta es una versión guardada. Comprueba sus datos antes de descargarla o prepara una nueva versión con el formulario actual.",
    ),
    run.status === "generating"
      ? el(
          "div",
          {
            className: "source-loading",
            role: "status",
            "aria-live": "polite",
            "aria-busy": "true",
          },
          "Se está creando el Word, convirtiendo ese mismo archivo a PDF y comprobando que el contenido se conserve. El avance queda registrado.",
        )
      : null,
    run.error
      ? el("p", { className: "warning-box", role: "alert" }, run.error)
      : null,
    run.stale
      ? el(
          "p",
          { className: "warning-box", role: "status" },
          "Las respuestas aprobadas o los archivos cambiaron. Esta versión permanece en el historial; actualiza la revisión y genera un oficio vigente para descargar.",
        )
      : null,
    ready
      ? el(
          "div",
          { className: "office-downloads" },
          (run.files || [])
            .filter((file) => ["docx", "pdf", "zip"].includes(file.kind))
            .map((file) =>
              button(
                `${{ docx: "Descargar Word", pdf: "Descargar PDF", zip: run.attachment_count ? `Paquete con ${run.attachment_count} anexos` : "Paquete Word y PDF" }[file.kind]} · ${sizeLabel(file.size)}`,
                () => actions.download(file.kind),
                "secondary",
                {
                  disabled: state.busy || !canDownload,
                  id: `office-download-${file.kind}`,
                },
              ),
            ),
        )
      : null,
    ready && run.page_count
      ? el(
          "section",
          {
            className: "office-pdf-preview",
            "aria-label": "Vista del PDF generado",
          },
          el(
            "div",
            { className: "office-page-controls" },
            button("← Anterior", () => actions.page(page - 1), "quiet", {
              disabled: page <= 1,
              "aria-label": "Página anterior del PDF",
            }),
            el(
              "span",
              {
                id: "office-pdf-page",
                tabindex: "-1",
                role: "status",
                "aria-live": "polite",
              },
              `Página ${page} de ${run.page_count}`,
            ),
            button("Siguiente →", () => actions.page(page + 1), "quiet", {
              disabled: page >= run.page_count,
              "aria-label": "Página siguiente del PDF",
            }),
          ),
          el("img", {
            className: "office-pdf-image",
            src: `/api/cases/${encodeURIComponent(state.caseId)}/office/runs/${encodeURIComponent(run.id)}/pages/${page}`,
            alt: `Página ${page} del PDF generado: ${run.metadata.subject}`,
            onError: (event) =>
              event.currentTarget.replaceWith(
                el(
                  "p",
                  { className: "warning-box", role: "status" },
                  "No se pudo mostrar esta página. Actualiza el estado para comprobar que el oficio continúe vigente.",
                ),
              ),
          }),
          el(
            "p",
            { className: "small muted" },
            "Imagen de una página del PDF generado a partir del Word. Usa las flechas para comprobar todas las páginas.",
          ),
        )
      : null,
    detail(
      "Datos y trazabilidad de esta versión",
      el(
        "div",
        {},
        el(
          "dl",
          { className: "office-run-metadata" },
          Object.entries(run.metadata || {}).map(([key, value]) =>
            value
              ? el(
                  "div",
                  {},
                  el(
                    "dt",
                    {},
                    {
                      institution: "Institución",
                      department: "Dependencia",
                      city: "Ciudad",
                      issue_date: "Fecha",
                      office_number: "Número de oficio",
                      petition_number: "Radicado de la petición",
                      recipient: "Destinatario",
                      recipient_contact: "Contacto",
                      subject: "Asunto",
                      signer_name: "Nombre al cierre",
                      signer_role: "Cargo al cierre",
                    }[key] || key,
                  ),
                  el(
                    "dd",
                    {},
                    key === "issue_date" ? observedDate(value) : value,
                  ),
                )
              : null,
          ),
        ),
        run.verification
          ? el(
              "p",
              { className: "small" },
              `Fidelidad del Word: ${run.verification.docx_exact ? "comprobada" : "por comprobar"}. Fidelidad del PDF: ${run.verification.pdf_text_match ? "comprobada" : "por comprobar"}. ${run.verification.request_count} solicitudes y ${run.verification.paragraph_count} párrafos.`,
            )
          : null,
        el(
          "p",
          { className: "small muted" },
          `Huella de vista previa: ${run.preview_hash?.slice(0, 12) || "sin registrar"} · ${run.converter || "Conversión pendiente"}`,
        ),
      ),
      "office-run-details",
      state,
    ),
  );
}
