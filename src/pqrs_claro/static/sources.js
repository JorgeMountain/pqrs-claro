import { el, button, dateLabel, textLines } from "./ui.js";

const categories = {
  national_norm: "Normativa nacional",
  institutional_norm: "Normativa institucional",
  case_evidence: "Soporte del expediente",
  previous_response: "Oficio anterior · Referencia de estilo",
};
const validityLabels = {
  unknown: "Vigencia por comprobar",
  current: "Vigencia revisada",
  superseded: "Reemplazada o sin vigencia",
  not_applicable: "No requiere vigencia normativa",
};
const statusLabels = {
  references_found: "Referencias encontradas",
  needs_evidence: "Necesita evidencia",
  no_matches: "Sin coincidencias",
  error: "Requiere atención",
};
const textOf = (value) =>
  typeof value === "string"
    ? value
    : value?.description || value?.message || "";
const field = (label, control, hint) =>
  el(
    "label",
    { className: "field" },
    el("span", {}, label),
    control,
    hint ? el("p", { className: "field-hint" }, hint) : null,
  );
const smallButton = (label, action, type = "secondary", attrs = {}) =>
  button(label, action, type, {
    className: `button button-${type} button-small`,
    ...attrs,
  });
const location = (item) =>
  `${item.location_kind === "section" ? "Sección" : "Página"} ${item.page ?? item.number}`;

/** Fuentes mantiene su carga y búsqueda independientes de la identificación. */
export function createSources({
  api,
  notify,
  getCase,
  render,
  openLibrary,
  closeLibrary,
}) {
  const state = {
    caseId: null,
    sources: [],
    mapping: null,
    loaded: false,
    loading: false,
    error: null,
    busy: false,
    poll: null,
    selected: null,
    loadToken: 0,
  };
  const context = () =>
    state.caseId ? `?case_id=${encodeURIComponent(state.caseId)}` : "";
  const sourceUrl = (id, suffix = "") =>
    `/api/sources/${encodeURIComponent(id)}${suffix}${context()}`;

  async function load({ quiet = false } = {}) {
    const token = ++state.loadToken;
    const current = getCase();
    state.caseId = current?.id || null;
    state.loading = !quiet;
    state.error = null;
    if (!quiet) render();
    const results = await Promise.allSettled([
      api(`/api/sources${context()}`),
      current?.status === "confirmed"
        ? api(`/api/cases/${encodeURIComponent(current.id)}/sources`)
        : Promise.resolve(null),
    ]);
    if (token !== state.loadToken || state.caseId !== (getCase()?.id || null))
      return;
    state.loading = false;
    state.loaded = true;
    if (results[0].status === "fulfilled")
      state.sources = (results[0].value.sources || []).filter(
        (source) => source.is_latest !== false,
      );
    else state.error = results[0].reason.message;
    if (results[1].status === "fulfilled") state.mapping = results[1].value;
    else state.error = results[1].reason.message;
    render();
    schedule();
  }

  function setCase(current) {
    if (state.caseId !== (current?.id || null)) {
      clearTimeout(state.poll);
      state.loadToken++;
      state.caseId = current?.id || null;
      state.sources = [];
      state.mapping = null;
      state.loaded = false;
      state.selected = null;
      state.error = null;
    }
  }
  function schedule() {
    clearTimeout(state.poll);
    if (state.mapping?.status !== "running") return;
    state.poll = setTimeout(async () => {
      const caseId = state.caseId;
      try {
        const mapping = await api(
          `/api/cases/${encodeURIComponent(caseId)}/sources`,
        );
        if (caseId !== state.caseId) return;
        state.mapping = mapping;
        state.error = null;
        render();
      } catch (error) {
        if (caseId !== state.caseId) return;
        state.error = `${error.message} El último resultado sigue guardado.`;
        render();
      }
      schedule();
    }, 1800);
  }
  async function action(task) {
    if (state.busy) return;
    state.busy = true;
    render();
    try {
      await task();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      state.busy = false;
      render();
    }
  }

  async function search() {
    await action(async () => {
      const current = getCase();
      const result = await api(
        `/api/cases/${encodeURIComponent(current.id)}/sources/search`,
        {
          method: "POST",
          body: JSON.stringify({ version: current.version }),
        },
      );
      if (current.id !== state.caseId) return;
      state.mapping = result.mapping || result;
      if (!state.mapping.status) await load({ quiet: true });
      schedule();
    });
  }
  async function example() {
    await action(async () => {
      await api(
        `/api/cases/${encodeURIComponent(getCase().id)}/sources/example`,
        { method: "POST", body: "{}" },
      );
      await load({ quiet: true });
      notify(
        "Fuentes ficticias cargadas para practicar. El ejemplo deja pendiente el acta solicitada para que puedas reconocer ese faltante.",
      );
    });
  }

  function storageNote() {
    return el(
      "div",
      { className: "storage-note" },
      el("span", { className: "connection-dot", "aria-hidden": "true" }),
      el(
        "p",
        {},
        el("strong", {}, "Biblioteca local"),
        " · Originales y versiones en este equipo. Drive no está conectado.",
      ),
    );
  }
  function libraryView() {
    const current = getCase();
    const common = state.sources.filter((source) => !source.case_id);
    const scoped = state.sources.filter(
      (source) => source.case_id === current?.id,
    );
    const view = el(
      "section",
      { className: "library-view", "aria-labelledby": "library-heading" },
      el(
        "div",
        { className: "library-heading" },
        el(
          "div",
          {},
          el(
            "h2",
            { id: "library-heading" },
            "Documentos que ayudan a responder",
          ),
          el(
            "p",
            { className: "muted" },
            "Conserva el original, registra de dónde viene y revisa su estado antes de usarlo.",
          ),
        ),
        button(
          current ? "Volver al expediente" : "Volver a nueva petición",
          closeLibrary,
          "secondary",
        ),
      ),
      storageNote(),
      current
        ? el(
            "p",
            { className: "library-context" },
            "Expediente seleccionado: ",
            el(
              "strong",
              {},
              current.identification?.subject || current.filename,
            ),
          )
        : null,
      el(
        "div",
        { className: "library-actions" },
        button("＋ Agregar fuente", () => uploadDialog(), "primary", {
          disabled: state.busy || state.loading,
        }),
        smallButton("Actualizar lista", () => load(), "quiet", {
          disabled: state.loading,
        }),
      ),
      state.error
        ? el("p", { className: "warning-box", role: "alert" }, state.error)
        : null,
    );
    if (state.loading) {
      view.append(
        el(
          "div",
          { className: "source-loading", role: "status", "aria-busy": "true" },
          "Cargando la biblioteca…",
        ),
      );
      return view;
    }
    if (!state.sources.length)
      view.append(
        el(
          "div",
          { className: "panel source-empty" },
          el("h3", {}, "Tu biblioteca está lista para comenzar"),
          el(
            "p",
            {},
            "Agrega un PDF, DOCX o TXT. Las normas y los oficios anteriores pueden ser compartidos; los soportes del caso quedan dentro de su expediente.",
          ),
        ),
      );
    if (common.length)
      view.append(
        sourceGroup(
          "Fuentes compartidas",
          "Normas y referencias disponibles para todos los expedientes.",
          common,
        ),
      );
    if (current)
      view.append(
        sourceGroup(
          "Fuentes de este expediente",
          "Disponibles solamente cuando trabajas en este caso.",
          scoped,
        ),
      );
    if (!current)
      view.append(
        el(
          "p",
          { className: "muted small" },
          "Selecciona un expediente para consultar o cargar sus soportes particulares.",
        ),
      );
    return view;
  }
  function sourceGroup(title, description, sources) {
    return el(
      "section",
      { className: "library-group" },
      el("h3", {}, title),
      el("p", { className: "muted small" }, description),
      sources.length
        ? el("div", { className: "library-list" }, sources.map(sourceRow))
        : el(
            "p",
            { className: "source-empty-small" },
            "Todavía no hay documentos en este grupo.",
          ),
    );
  }
  function sourceRow(source) {
    return el(
      "article",
      { className: "library-row" },
      el(
        "div",
        { className: "library-source-info" },
        el("h4", {}, source.title),
        el(
          "p",
          { className: "small muted" },
          `${categories[source.category] || source.category} · Versión ${source.version} · ${source.filename}`,
        ),
        el("p", { className: "source-origin" }, "Procedencia: ", source.origin),
        reviewBadges(source),
      ),
      el(
        "div",
        { className: "button-group" },
        smallButton("Ver documento", () => showSource(source.id)),
        smallButton("Nueva versión", () => uploadDialog(source), "quiet", {
          disabled: state.busy,
        }),
      ),
    );
  }
  function reviewBadges(source) {
    return el(
      "div",
      { className: "source-badges" },
      el(
        "span",
        {
          className: `source-tag ${source.review_status === "reviewed" ? "reviewed" : "pending"}`,
        },
        source.review_status === "reviewed"
          ? "Procedencia revisada"
          : "Pendiente de revisión",
      ),
      el(
        "span",
        {
          className: `source-tag ${source.validity === "current" || source.validity === "not_applicable" ? "" : "pending"}`,
        },
        validityLabels[source.validity] || "Estado por comprobar",
      ),
    );
  }

  function caseView() {
    const current = getCase();
    if (current?.status !== "confirmed") return null;
    const mapping = state.mapping;
    const searchableCount =
      mapping?.source_count ??
      state.sources.filter(
        (source) =>
          source.category !== "previous_response" &&
          source.validity !== "superseded",
      ).length;
    const isRunning = mapping?.status === "running";
    const stale = mapping?.stale || mapping?.status === "stale";
    const requests = current.identification?.requests || [];
    const results = mapping?.results || [];
    const selected =
      requests.find((item) => item.id === state.selected) || requests[0];
    const isDemo = /ejemplo ficticio/i.test(current.filename || "");
    const panel = el(
      "section",
      {
        className: "sources-workspace panel",
        id: "sources-workspace",
        "aria-labelledby": "sources-heading",
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
            "PARTE 4 · FUENTES Y EVIDENCIA",
          ),
          el("h2", { id: "sources-heading" }, "Qué tenemos para responder"),
          el(
            "p",
            { className: "muted" },
            "Relaciona cada solicitud con sus posibles soportes y comprueba qué información falta.",
          ),
        ),
        smallButton("Abrir biblioteca", openLibrary),
      ),
      el(
        "div",
        { className: "sources-next" },
        el(
          "p",
          {},
          el(
            "strong",
            {},
            `${searchableCount} ${searchableCount === 1 ? "fuente para consultar" : "fuentes para consultar"}`,
          ),
          " en este expediente. Los oficios de estilo y las fuentes reemplazadas se conservan en la biblioteca, pero no se usan como evidencia en esta búsqueda.",
        ),
        el(
          "div",
          { className: "button-group" },
          button(
            isRunning
              ? "Buscando fuentes…"
              : stale
                ? "Actualizar búsqueda"
                : results.length
                  ? "Volver a buscar"
                  : "Buscar fuentes",
            search,
            "primary",
            {
              disabled:
                state.busy || state.loading || isRunning || !searchableCount,
            },
          ),
          smallButton("Agregar fuente", () => uploadDialog(), "secondary", {
            disabled: state.busy || isRunning,
          }),
        ),
      ),
      storageNote(),
    );
    if (!state.loaded || state.loading)
      panel.append(
        el(
          "p",
          { className: "source-loading", role: "status" },
          "Cargando fuentes del expediente…",
        ),
      );
    if (state.error)
      panel.append(
        el(
          "div",
          { className: "warning-box", role: "alert" },
          el("p", {}, state.error),
          smallButton("Reintentar carga", () => load(), "quiet"),
        ),
      );
    if (stale)
      panel.append(
        el(
          "p",
          { className: "warning-box", role: "status" },
          "La biblioteca o la identificación cambiaron. Estos resultados corresponden a la búsqueda anterior; actualiza la búsqueda antes de utilizarlos.",
        ),
      );
    if (isRunning)
      panel.append(
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
            `Buscando por solicitud · ${mapping.completed_count || 0} de ${mapping.total_count || requests.length}`,
          ),
          el(
            "p",
            {},
            "Se consultan los documentos disponibles y se conservan las citas encontradas. Puedes volver a este expediente después.",
          ),
          el(
            "div",
            { className: "loading-bars", "aria-hidden": "true" },
            el("span"),
            el("span"),
            el("span"),
          ),
        ),
      );
    if (mapping?.status === "error")
      panel.append(
        el(
          "p",
          { className: "warning-box", role: "alert" },
          mapping.error ||
            "La búsqueda se interrumpió. Puedes volver a intentarlo.",
        ),
      );
    if (!results.length && !isRunning) {
      panel.append(
        el(
          "div",
          { className: "source-empty" },
          el(
            "h3",
            {},
            searchableCount
              ? "El siguiente paso es buscar"
              : "Primero, agrega los documentos de consulta",
          ),
          el(
            "p",
            {},
            searchableCount
              ? "La búsqueda recorrerá cada solicitud confirmada. Aquí verás las referencias y los faltantes que debes comprobar."
              : "Carga normas o soportes del expediente y revisa su procedencia. Necesitas al menos una fuente de consulta que no esté marcada como reemplazada.",
          ),
          isDemo
            ? smallButton("Cargar fuentes del ejemplo", example, "secondary", {
                disabled: state.busy,
              })
            : null,
        ),
      );
      return panel;
    }
    if (results.length) {
      const missingCount = results.filter(
        (item) =>
          item.missing?.length ||
          ["needs_evidence", "no_matches", "error"].includes(item.status),
      ).length;
      panel.append(
        el(
          "div",
          { className: "search-summary", role: "status" },
          el(
            "p",
            {},
            el("strong", {}, `${results.length} solicitudes consultadas`),
            ` · ${missingCount} con faltantes o revisión pendiente`,
          ),
          el(
            "p",
            { className: "small muted" },
            `Última búsqueda: ${dateLabel(mapping.searched_at, true)}${stale ? " · Por actualizar" : ""}`,
          ),
        ),
      );
      const selector = el(
        "select",
        {
          id: "source-request-select",
          onChange: (event) => {
            state.selected = event.target.value;
            render();
            document
              .getElementById("source-request-select")
              ?.focus({ preventScroll: true });
          },
        },
        requests.map((request) => {
          const result = results.find((item) => item.request_id === request.id);
          return el(
            "option",
            { value: request.id },
            `${request.label}. ${request.title} — ${statusLabels[result?.status] || "Por consultar"}`,
          );
        }),
      );
      selector.value = selected?.id || "";
      panel.append(field("Solicitud que quieres comprobar", selector));
      const result = results.find((item) => item.request_id === selected?.id);
      if (selected)
        panel.append(
          el(
            "div",
            { className: "request-evidence" },
            el("h3", {}, `${selected.label}. ${selected.title}`),
            el(
              "p",
              { className: "evidence-request-description" },
              selected.description,
            ),
            result
              ? resultView(result)
              : el(
                  "p",
                  { className: "muted" },
                  "Esta solicitud todavía no tiene resultado. La búsqueda sigue en curso.",
                ),
          ),
        );
    }
    panel.append(
      el(
        "details",
        { className: "process source-process" },
        el("summary", {}, "Ver cómo se buscan las fuentes"),
        el(
          "div",
          { className: "process-body" },
          el(
            "p",
            {},
            el("strong", {}, "Python conserva y busca. "),
            "Lee los documentos, guarda sus versiones y recupera fragmentos relacionados con la solicitud.",
          ),
          el(
            "p",
            {},
            el("strong", {}, "La IA relaciona. "),
            "Propone qué fragmentos son pertinentes y qué evidencia puede faltar. Las citas se comprueban contra el texto conservado.",
          ),
          el(
            "p",
            {},
            el("strong", {}, "LangGraph coordina. "),
            "Organiza la búsqueda por solicitud y conserva los resultados para continuar la revisión.",
          ),
          el(
            "p",
            {},
            el("strong", {}, "Tú compruebas. "),
            "Una referencia puede aportar una regla o contexto sin acreditar los hechos del expediente. Los oficios anteriores orientan el estilo.",
          ),
        ),
      ),
    );
    return panel;
  }

  function resultView(result) {
    const supports = result.supports || [];
    const missing = result.missing || [];
    const body = el(
      "div",
      { className: "evidence-result" },
      el(
        "span",
        {
          className: `source-tag ${missing.length || result.status !== "references_found" ? "pending" : "reviewed"}`,
        },
        statusLabels[result.status] || "Por revisar",
      ),
    );
    if (missing.length)
      body.append(
        el(
          "div",
          { className: "evidence-missing" },
          el("h4", {}, "Qué hace falta comprobar o aportar"),
          el(
            "ul",
            {},
            missing.map((item) => el("li", {}, textOf(item))),
          ),
        ),
      );
    body.append(
      el(
        "p",
        { className: "evidence-summary" },
        result.summary ||
          "Revisa los documentos relacionados con esta solicitud.",
      ),
    );
    const warnings = (result.warnings || []).map(textOf).filter(Boolean);
    if (warnings.length)
      body.append(
        el(
          "div",
          { className: "warning-box small" },
          warnings.map((warning) => el("p", {}, warning)),
        ),
      );
    if (!supports.length)
      body.append(
        el(
          "p",
          { className: "source-empty-small" },
          "No encontramos fragmentos pertinentes en los documentos consultados. Esto no demuestra que el documento o la información no existan.",
        ),
      );
    const groups = new Map();
    supports.forEach((support) => {
      const key = `${support.source_id}:${support.version}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(support);
    });
    for (const group of groups.values()) {
      const source = group[0];
      body.append(
        el(
          "details",
          { className: "evidence-document", open: groups.size === 1 },
          el(
            "summary",
            {},
            el(
              "span",
              {},
              el("strong", {}, source.title),
              el(
                "span",
                { className: "small muted" },
                `Versión ${source.version} · ${group.length} ${group.length === 1 ? "fragmento" : "fragmentos"}`,
              ),
            ),
          ),
          el(
            "div",
            { className: "evidence-document-body" },
            el(
              "p",
              { className: "small muted" },
              categories[source.category] || source.category,
            ),
            reviewBadges(source),
            group.map((support) =>
              el(
                "article",
                { className: "evidence-fragment" },
                el(
                  "p",
                  { className: "evidence-reason" },
                  el("strong", {}, "Relación con lo pedido: "),
                  support.reason,
                ),
                el("blockquote", { className: "source-quote" }, support.quote),
                smallButton(
                  `${location(support)} · Líneas ${support.line_start}–${support.line_end} ↗`,
                  () => showSource(support.source_id, support),
                  "quiet",
                ),
              ),
            ),
          ),
        ),
      );
    }
    return body;
  }

  function dialog(title) {
    const previousFocus = document.activeElement;
    const modal = el("dialog", {
      className: "source-dialog",
      "aria-labelledby": "source-dialog-title",
    });
    const close = () => modal.close();
    modal.append(
      el(
        "div",
        { className: "source-dialog-head" },
        el("h2", { id: "source-dialog-title" }, title),
        smallButton("Cerrar", close, "quiet", {
          "aria-label": "Cerrar ventana de fuentes",
        }),
      ),
    );
    modal.addEventListener("close", () => {
      modal.remove();
      previousFocus?.isConnected &&
        previousFocus.focus({ preventScroll: true });
    });
    document.body.append(modal);
    modal.showModal();
    return { modal, close };
  }

  function uploadDialog(previous = null) {
    const { modal, close } = dialog(
      previous ? "Agregar una nueva versión" : "Agregar una fuente",
    );
    const current = getCase();
    const title = el("input", {
      name: "title",
      required: true,
      maxLength: 300,
      value: previous?.title || "",
    });
    const origin = el("input", {
      name: "origin",
      required: true,
      maxLength: 2000,
      value: previous?.origin || "",
      placeholder: "Entidad, responsable o enlace de procedencia",
    });
    const category = el(
      "select",
      { name: "category", disabled: Boolean(previous) },
      Object.entries(categories)
        .filter(([value]) => current || value !== "case_evidence")
        .map(([value, label]) => el("option", { value }, label)),
    );
    category.value =
      previous?.category || (current ? "case_evidence" : "institutional_norm");
    const file = el("input", {
      type: "file",
      name: "file",
      accept: ".pdf,.docx,.txt",
      required: true,
    });
    const scope = el("p", { className: "upload-scope" });
    const updateScope = () => {
      scope.textContent =
        previous?.case_id || category.value === "case_evidence"
          ? "Se conservará dentro del expediente seleccionado."
          : "Esta fuente estará disponible para todos los expedientes.";
    };
    category.addEventListener("change", updateScope);
    updateScope();
    const status = el("p", {
      className: "form-status",
      role: "status",
      "aria-live": "polite",
    });
    const submit = el(
      "button",
      { type: "submit", className: "button button-primary" },
      previous ? "Guardar nueva versión" : "Guardar fuente",
    );
    const form = el(
      "form",
      { className: "source-form" },
      previous
        ? el(
            "p",
            { className: "muted" },
            `El original de la versión ${previous.version} se conserva. La nueva carga tendrá su propia revisión.`,
          )
        : el(
            "p",
            { className: "muted" },
            "Carga el archivo y registra su procedencia. Después podrás comprobar la lectura y registrar la revisión.",
          ),
      field(
        "Archivo PDF, DOCX o TXT",
        file,
        "Hasta 20 MB. PDF: hasta 300 páginas. En DOCX se lee el cuerpo del documento; si necesitas encabezados, pies o anotaciones, carga una copia en PDF.",
      ),
      field("Nombre para reconocer la fuente", title),
      field("Función del documento", category),
      scope,
      field(
        "De dónde proviene",
        origin,
        "Un enlace se conserva como referencia; no conecta ni descarga contenido de otro servicio.",
      ),
      status,
      submit,
    );
    let saving = false;
    modal.addEventListener("cancel", (event) => {
      if (saving) event.preventDefault();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (saving || !form.reportValidity()) return;
      const body = new FormData();
      body.append("file", file.files[0]);
      body.append("title", title.value.trim());
      body.append("origin", origin.value.trim());
      body.append("category", category.value);
      if (previous) body.append("document_id", previous.document_id);
      const caseId =
        previous?.case_id ||
        (category.value === "case_evidence" ? current?.id : null);
      if (caseId) body.append("case_id", caseId);
      saving = true;
      modal.querySelectorAll("button,input,select").forEach((node) => {
        node.disabled = true;
      });
      status.className = "form-status";
      status.textContent =
        "Guardando y leyendo el documento… Los archivos escaneados pueden tardar más porque requieren OCR.";
      status.setAttribute("aria-busy", "true");
      try {
        const result = await api("/api/sources", { method: "POST", body });
        close();
        await load({ quiet: true });
        notify(
          result.deduplicated
            ? "Este archivo ya estaba conservado. Se mantiene su versión existente."
            : "Fuente guardada. Comprueba el texto, la procedencia y la vigencia en «Ver documento».",
        );
      } catch (error) {
        status.textContent = error.message;
        status.className = "form-status error";
        status.setAttribute("role", "alert");
        modal.querySelectorAll("button,input,select").forEach((node) => {
          node.disabled = false;
        });
        category.disabled = Boolean(previous);
      } finally {
        saving = false;
        status.removeAttribute("aria-busy");
      }
    });
    modal.append(form);
    file.focus();
  }

  async function showSource(id, ref = null) {
    const { modal } = dialog("Comprobar la fuente");
    const body = el(
      "div",
      { className: "source-detail-content" },
      el("p", { role: "status" }, "Cargando el documento…"),
    );
    modal.append(body);
    try {
      const [detail, history] = await Promise.allSettled([
        api(sourceUrl(id)),
        api(sourceUrl(id, "/versions")),
      ]);
      if (!modal.isConnected) return;
      if (detail.status === "rejected") throw detail.reason;
      const source = detail.value.source || detail.value;
      const pages = detail.value.pages || source.pages || [];
      const versions =
        history.status === "fulfilled"
          ? Array.isArray(history.value)
            ? history.value
            : history.value.versions || []
          : [];
      body.replaceChildren(
        el("h3", {}, source.title),
        el(
          "p",
          { className: "muted small" },
          `${categories[source.category] || source.category} · Versión ${source.version} · ${source.filename}`,
        ),
        el(
          "p",
          { className: "source-origin" },
          el("strong", {}, "Procedencia: "),
          source.origin,
        ),
        reviewBadges(source),
        el(
          "p",
          { className: "muted small" },
          `Conservado: ${dateLabel(source.created_at, true)}`,
        ),
        el(
          "a",
          {
            href: sourceUrl(id, "/original"),
            target: "_blank",
            rel: "noopener",
            className: "small-link",
          },
          "Abrir archivo original ↗",
        ),
      );
      if (source.is_latest === false)
        body.append(
          el(
            "p",
            { className: "warning-box" },
            "Estás consultando una versión anterior. Se conserva para verificar las búsquedas realizadas con ella.",
          ),
        );
      if (ref)
        body.append(
          el(
            "div",
            { className: "reference-preview" },
            el("h4", {}, "Fragmento citado en la búsqueda"),
            el("blockquote", { className: "source-quote" }, ref.quote),
          ),
        );
      const pageView = el("div", { className: "source-page-view" });
      const pageSelect = el(
        "select",
        {
          "aria-label":
            source.location_kind === "section"
              ? "Sección de la fuente"
              : "Página de la fuente",
        },
        pages.map((page) =>
          el(
            "option",
            { value: page.number },
            `${source.location_kind === "section" ? "Sección" : "Página"} ${page.number}`,
          ),
        ),
      );
      const renderPage = (number) => {
        const page =
          pages.find((item) => item.number === Number(number)) || pages[0];
        if (!page) {
          pageView.replaceChildren(
            el(
              "p",
              { className: "warning-box" },
              "No hay texto disponible. Consulta el archivo original.",
            ),
          );
          return;
        }
        pageView.replaceChildren();
        if (
          source.location_kind !== "section" &&
          source.filename?.toLowerCase().endsWith(".pdf")
        ) {
          const img = el("img", {
            src: sourceUrl(id, `/pages/${page.number}.png`),
            className: "source-page-image",
            alt: `Página ${page.number} de ${source.title}`,
            loading: "lazy",
          });
          img.addEventListener("error", () =>
            img.replaceWith(
              el(
                "p",
                { className: "muted small" },
                "La imagen no está disponible. Puedes abrir el archivo original.",
              ),
            ),
          );
          pageView.append(
            el(
              "details",
              { className: "source-page-original" },
              el("summary", {}, "Ver imagen de la página"),
              img,
            ),
          );
        }
        if (page.needs_review)
          pageView.append(
            el(
              "p",
              { className: "warning-box" },
              "Esta lectura requiere revisión. Comprueba nombres, números y fechas contra el original.",
            ),
          );
        pageView.append(
          el(
            "p",
            { className: "muted small" },
            source.location_kind === "section"
              ? "Las secciones agrupan texto extraído; no representan páginas del documento original."
              : "Líneas del texto extraído de la página.",
          ),
          el(
            "ol",
            {
              className: "line-list source-full-text",
              "aria-label": "Texto de la fuente con líneas numeradas",
            },
            textLines(page.text).map((line, index) =>
              el(
                "li",
                {
                  className:
                    ref?.page === page.number &&
                    index + 1 >= ref.line_start &&
                    index + 1 <= ref.line_end
                      ? "highlight"
                      : "",
                },
                line || " ",
              ),
            ),
          ),
        );
      };
      pageSelect.value = String(ref?.page || pages[0]?.number || 1);
      pageSelect.addEventListener("change", (event) =>
        renderPage(event.target.value),
      );
      renderPage(pageSelect.value);
      body.append(
        el(
          "div",
          { className: "source-page-toolbar" },
          field(
            source.location_kind === "section"
              ? "Texto por sección"
              : "Texto por página",
            pageSelect,
          ),
        ),
        pageView,
      );
      if (source.is_latest !== false) body.append(reviewForm(source));
      else
        body.append(
          el(
            "p",
            { className: "muted small" },
            "La revisión se registra sobre la versión vigente de la biblioteca.",
          ),
        );
      if (versions.length)
        body.append(
          el(
            "details",
            { className: "source-versions" },
            el(
              "summary",
              {},
              `Historial · ${versions.length} ${versions.length === 1 ? "versión" : "versiones"}`,
            ),
            el(
              "ol",
              {},
              versions.map((version) =>
                el(
                  "li",
                  {},
                  el(
                    "span",
                    {},
                    `Versión ${version.version} · ${dateLabel(version.created_at, true)} · ${version.filename}`,
                  ),
                  version.id !== id
                    ? smallButton(
                        "Consultar",
                        () => {
                          modal.close();
                          showSource(version.id);
                        },
                        "quiet",
                      )
                    : el("span", { className: "muted small" }, "Consultando"),
                ),
              ),
            ),
          ),
        );
      if (history.status === "rejected")
        body.append(
          el(
            "p",
            { className: "muted small" },
            "No se pudo cargar el historial de versiones. Vuelve a abrir el documento para intentarlo.",
          ),
        );
    } catch (error) {
      if (modal.isConnected)
        body.replaceChildren(
          el("p", { className: "warning-box", role: "alert" }, error.message),
        );
    }
  }

  function reviewForm(source) {
    const name = el("input", {
      required: true,
      maxLength: 200,
      value: source.reviewed_by || "",
    });
    const validity = el(
      "select",
      {},
      el("option", { value: "unknown" }, "Aún no pude comprobarla"),
      el("option", { value: "current" }, "Comprobé que está vigente"),
      el("option", { value: "superseded" }, "Está reemplazada o sin vigencia"),
      el(
        "option",
        { value: "not_applicable" },
        "No aplica: es un soporte o referencia",
      ),
    );
    validity.value = source.validity || "unknown";
    const note = el("textarea", {
      rows: 3,
      required: true,
      maxLength: 3000,
      value: source.review_note || "",
    });
    const status = el("p", {
      className: "form-status",
      role: "status",
      "aria-live": "polite",
    });
    const form = el(
      "form",
      { className: "source-review-form" },
      el("h4", {}, "Registrar la revisión de esta versión"),
      el(
        "p",
        { className: "muted small" },
        "Registra quién comprobó la procedencia y qué pudo verificar sobre la vigencia. Esta revisión no declara suficiente la fuente para responder una solicitud.",
      ),
      field("Nombre del responsable de la revisión", name),
      field("Vigencia", validity),
      field("Qué comprobaste y con qué referencia", note),
      status,
      el(
        "button",
        { type: "submit", className: "button button-primary" },
        "Guardar revisión",
      ),
    );
    let busy = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy || !form.reportValidity()) return;
      busy = true;
      const body = JSON.stringify({
        reviewed_by: name.value.trim(),
        review_note: note.value.trim() || null,
        validity: validity.value,
      });
      form.querySelectorAll("input,select,textarea,button").forEach((node) => {
        node.disabled = true;
      });
      status.textContent = "Guardando la revisión…";
      status.className = "form-status";
      try {
        await api(sourceUrl(source.id, "/review"), { method: "PUT", body });
        await load({ quiet: true });
        status.textContent =
          "Revisión guardada. Si había resultados de búsqueda, actualízalos para incluir este cambio.";
        const reviewSummary = form.parentElement?.querySelector("summary");
        if (reviewSummary)
          reviewSummary.textContent = `Revisión registrada por ${name.value.trim()} · Ver o actualizar`;
        const updated = state.sources.find((item) => item.id === source.id);
        const badges = form
          .closest(".source-detail-content")
          ?.querySelector(".source-badges");
        if (updated && badges) badges.replaceWith(reviewBadges(updated));
      } catch (error) {
        status.textContent = error.message;
        status.className = "form-status error";
      } finally {
        busy = false;
        form
          .querySelectorAll("input,select,textarea,button")
          .forEach((node) => {
            node.disabled = false;
          });
      }
    });
    return el(
      "details",
      { className: "source-review", open: source.review_status !== "reviewed" },
      el(
        "summary",
        {},
        source.review_status === "reviewed"
          ? `Revisión registrada por ${source.reviewed_by || "responsable"} · Ver o actualizar`
          : "Revisar procedencia y vigencia",
      ),
      form,
    );
  }
  return { load, setCase, caseView, libraryView, upload: uploadDialog, state };
}
