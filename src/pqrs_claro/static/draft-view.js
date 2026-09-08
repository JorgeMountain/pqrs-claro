import { el, button } from "./ui.js";

const detail = (title, body, key, state) =>
  el(
    "details",
    {
      className: "response-detail",
      open: state.expanded.has(key),
      onToggle: (event) =>
        event.target.open
          ? state.expanded.add(key)
          : state.expanded.delete(key),
    },
    el("summary", {}, title),
    body,
  );

function citations(ids, supports, showSource) {
  return el(
    "div",
    {
      className: "response-citations",
      "aria-label": "Fuentes de este párrafo",
    },
    (ids || []).map((id) => {
      const source = supports.find((item) => item.chunk_id === id);
      if (!source)
        return el(
          "span",
          { className: "warning-box" },
          "Referencia por comprobar",
        );
      const index = supports.findIndex((item) => item.chunk_id === id) + 1;
      const location = `${source.location_kind === "section" ? "Sección" : "Página"} ${source.page}`;
      return button(
        `Fuente ${index} · ${location} ↗`,
        () => showSource(source.source_id, source),
        "quiet",
        {
          className: "button button-quiet button-small",
          title: source.title,
          "aria-label": `Fuente ${index}: ${source.title}, ${location}, líneas ${source.line_start} a ${source.line_end}`,
        },
      );
    }),
  );
}

function pendingView(items, key, state) {
  if (!items.length) return null;
  const list = (rows) =>
    el(
      "ul",
      {},
      rows.map((item) => el("li", {}, item.description || item)),
    );
  return el(
    "section",
    {
      className: "response-pending",
      "aria-label": "Pendientes de esta respuesta",
    },
    el("h4", {}, "Qué falta resolver"),
    list(items.slice(0, 3)),
    items.length > 3
      ? detail(
          `Ver los ${items.length - 3} pendientes restantes`,
          list(items.slice(3)),
          `${key}-pending`,
          state,
        )
      : null,
  );
}

export function responseCard(request, result, state, showSource) {
  const key = request.id;
  const supports = result?.supports || [];
  const draft = result?.draft;
  const checks = result?.checks;
  const pending = draft?.pending || [];
  const hasIssues = checks?.status === "needs_changes";
  const card = el(
    "article",
    { className: "response-card", "aria-labelledby": `response-title-${key}` },
    el("p", { className: "section-kicker" }, `SOLICITUD ${request.label}`),
    el("h3", { id: `response-title-${key}` }, request.title),
    el("p", { className: "response-request" }, request.description),
  );
  if (!result) {
    card.append(
      el(
        "p",
        { className: "response-placeholder" },
        state.run?.status === "running"
          ? "Esta solicitud está en la cola. Su avance aparecerá aquí."
          : "El plan, el borrador y sus comprobaciones aparecerán aquí al preparar las respuestas.",
      ),
    );
    return card;
  }
  if (result.error)
    card.append(
      el("p", { className: "warning-box", role: "alert" }, result.error),
    );
  if (pending.length) card.append(pendingView(pending, key, state));
  if (hasIssues)
    card.append(
      el(
        "section",
        {
          className: "response-issues",
          "aria-label": "Comprobaciones pendientes",
        },
        el("h4", {}, "Ajustes detectados en el borrador"),
        el(
          "ul",
          {},
          (checks.issues || []).map((issue) =>
            el(
              "li",
              {},
              issue.paragraph_index != null
                ? `Párrafo ${issue.paragraph_index + 1}: `
                : "",
              issue.description,
            ),
          ),
        ),
      ),
    );
  if (result.plan)
    card.append(
      detail(
        "1. Plan de respuesta",
        el(
          "div",
          {},
          el("p", {}, result.plan.objective),
          el(
            "ol",
            {},
            (result.plan.points || []).map((point) =>
              el(
                "li",
                {},
                el("p", {}, point.description),
                citations(point.cited_chunk_ids, supports, showSource),
              ),
            ),
          ),
        ),
        `${key}-plan`,
        state,
      ),
    );
  if (draft)
    card.append(
      el(
        "section",
        { className: "response-text", "aria-label": "Texto propuesto" },
        el(
          "div",
          { className: "response-section-heading" },
          el("h4", {}, "2. Borrador de respuesta"),
          el(
            "span",
            { className: "source-tag pending" },
            hasIssues
              ? "Requiere ajustes"
              : draft.status === "needs_evidence"
                ? "Con pendientes"
                : "Para revisión humana",
          ),
        ),
        (draft.paragraphs || []).map((paragraph) =>
          el(
            "div",
            { className: "response-paragraph" },
            el("p", {}, paragraph.text),
            citations(paragraph.cited_chunk_ids, supports, showSource),
          ),
        ),
        !draft.paragraphs?.length
          ? el(
              "p",
              { className: "muted" },
              "Todavía no hay contenido respaldado suficiente para proponer una respuesta. Revisa los pendientes indicados.",
            )
          : null,
      ),
    );
  if (checks)
    card.append(
      detail(
        "3. Comprobaciones del borrador",
        el(
          "div",
          {},
          el(
            "p",
            {},
            hasIssues
              ? "Se encontraron puntos que deben corregirse antes de la revisión final."
              : "Las comprobaciones automáticas terminaron. La pertinencia y la respuesta necesitan revisión humana.",
          ),
          el(
            "ul",
            { className: "response-checks" },
            (checks.local_checks || []).map((check) =>
              el(
                "li",
                {},
                el(
                  "span",
                  {
                    "aria-label": check.passed
                      ? "Comprobación superada"
                      : "Requiere atención",
                  },
                  check.passed ? "✓ " : "! ",
                ),
                check.description,
              ),
            ),
          ),
        ),
        `${key}-checks`,
        state,
      ),
    );
  return card;
}

export function draftsView({
  state,
  current,
  mapping,
  generate,
  load,
  back,
  review,
  showSource,
  select,
}) {
  const requests = current.identification?.requests || [];
  const run = state.run;
  const inProgress = run?.status === "running";
  const sourceReady = mapping?.status === "ready" && !mapping.stale;
  const selected =
    requests.find((item) => item.id === state.selected) || requests[0];
  const currentResult = run?.results?.find(
    (item) => item.request_id === selected?.id,
  );
  const retryable =
    run?.status === "failed" ||
    run?.results?.some((item) => item.status === "error");
  const prepared = ["ready", "partial"].includes(run?.status) && !retryable;
  const completed = run?.completed_count || 0;
  const stages = {
    planificar: "Preparando el plan",
    redactar: "Redactando el borrador",
    comprobar: "Comprobando sus soportes",
  };
  const active = requests.find((item) => item.id === run?.current_request_id);
  const view = el(
    "section",
    {
      className: "panel response-workspace",
      "aria-labelledby": "responses-heading",
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
          "FASE 5 · RESPUESTAS CON SOPORTE",
        ),
        el(
          "h2",
          { id: "responses-heading" },
          "Una respuesta para cada solicitud",
        ),
        el(
          "p",
          { className: "muted" },
          "Consulta el plan, lee el borrador y abre las fuentes de cada párrafo.",
        ),
      ),
      button("Consultar fuentes", back, "secondary", { id: "responses-back" }),
    ),
    el(
      "p",
      { className: "response-boundary" },
      "Borradores de trabajo · La revisión y aprobación institucional siguen pendientes.",
    ),
    !sourceReady
      ? el(
          "p",
          { className: "warning-box", role: "status" },
          "Completa o actualiza la búsqueda de fuentes antes de preparar los borradores.",
        )
      : null,
    run?.stale
      ? el(
          "p",
          { className: "warning-box", role: "status" },
          "Las solicitudes o sus fuentes cambiaron. Estos borradores corresponden a una versión anterior; actualízalos antes de continuar.",
        )
      : null,
    el(
      "div",
      { className: "response-actions" },
      button(
        inProgress
          ? "Preparando respuestas…"
          : run?.stale
            ? "Actualizar borradores"
            : retryable
              ? "Reintentar solicitudes pendientes"
              : run?.status === "partial"
                ? "Borradores con pendientes"
                : run?.status === "ready"
                  ? "Borradores preparados"
                  : "Preparar borradores",
        generate,
        "primary",
        {
          id: "generate-responses",
          disabled:
            state.busy ||
            state.loading ||
            inProgress ||
            !sourceReady ||
            prepared,
        },
      ),
      button("Actualizar estado", () => load(), "quiet", {
        id: "refresh-responses",
        disabled: state.loading || state.busy,
      }),
      prepared && !run?.stale
        ? button("Continuar a revisión humana", review, "secondary", {
            id: "continue-review",
          })
        : null,
    ),
    state.error || run?.error
      ? el(
          "p",
          { className: "warning-box", role: "alert" },
          state.error || run.error,
        )
      : null,
  );
  if (state.loading && !run)
    view.append(
      el(
        "div",
        { className: "source-loading", role: "status", "aria-busy": "true" },
        "Cargando borradores guardados…",
      ),
    );
  if (inProgress)
    view.append(
      el(
        "div",
        {
          className: "search-progress",
          role: "status",
          "aria-live": "polite",
          "aria-busy": "true",
        },
        el(
          "strong",
          {},
          `${stages[run.current_step] || "Preparando respuestas"}${active ? ` · Solicitud ${active.label}` : ""}`,
        ),
        el(
          "p",
          {},
          `${completed} de ${requests.length} solicitudes procesadas. El avance se guarda por etapas.`,
        ),
        el("progress", {
          max: Math.max(1, requests.length),
          value: completed,
          "aria-label": "Solicitudes procesadas",
        }),
      ),
    );
  if (requests.length)
    view.append(
      el(
        "div",
        { className: "response-layout" },
        el(
          "nav",
          {
            className: "response-list",
            "aria-label": "Borradores por solicitud",
          },
          requests.map((request) => {
            const result = run?.results?.find(
              (item) => item.request_id === request.id,
            );
            const label = result?.error
              ? "Requiere atención"
              : result?.checks?.status === "needs_changes"
                ? "Requiere ajustes"
                : result?.draft
                  ? result.draft.status === "needs_evidence"
                    ? "Con pendientes"
                    : "Para revisión"
                  : run?.current_request_id === request.id && inProgress
                    ? "En preparación"
                    : "Por preparar";
            return button(
              [
                el(
                  "span",
                  { className: "response-list-title" },
                  `${request.label}. ${request.title}`,
                ),
                el("span", { className: "small muted" }, label),
              ],
              () => select(request.id),
              "quiet",
              {
                id: `response-select-${request.id}`,
                className: `response-list-item ${selected?.id === request.id ? "active" : ""}`,
                "aria-current": selected?.id === request.id ? "true" : null,
              },
            );
          }),
        ),
        selected
          ? responseCard(selected, currentResult, state, showSource)
          : null,
      ),
    );
  return view;
}
