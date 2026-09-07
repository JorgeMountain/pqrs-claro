import { el, button, textLines } from "./ui.js";

function field(label, control, hint) {
  return el(
    "label",
    { className: "field" },
    el("span", {}, label),
    control,
    hint ? el("p", { className: "field-hint" }, hint) : null,
  );
}

export function quoteFor(pages, ref) {
  const page = pages.find((item) => item.number === Number(ref.page));
  if (
    !page ||
    !Number.isInteger(Number(ref.line_start)) ||
    !Number.isInteger(Number(ref.line_end))
  )
    return "";
  const lines = textLines(page.text);
  if (
    ref.line_start < 1 ||
    ref.line_end < ref.line_start ||
    ref.line_end > lines.length
  )
    return "";
  return lines.slice(ref.line_start - 1, ref.line_end).join("\n");
}

export function requestsView(state, actions) {
  const current = state.current;
  const identification = state.draft || current.identification;
  const editable = current.status === "needs_review";
  const requests = identification.requests || [];
  const wrapper = el("section", { "aria-label": "Solicitudes identificadas" });
  if (current.status === "confirmed")
    wrapper.append(
      el(
        "div",
        { className: "confirmed-panel", role: "status" },
        el("div", { className: "confirmed-mark" }, "✓ PARTE 3 COMPLETADA"),
        el("h2", {}, "Ya sabemos qué se solicita."),
        el(
          "p",
          {},
          `Confirmaste la identificación de ${requests.length} ${requests.length === 1 ? "solicitud o apartado" : "solicitudes y apartados"}. Esta versión queda guardada para la siguiente etapa: buscar fuentes.`,
        ),
      ),
    );
  if (state.draft) wrapper.append(draftBar(state, actions));
  if (identification.requester)
    wrapper.append(
      el(
        "p",
        { className: "identity-note" },
        "Solicitante: ",
        el("strong", {}, identification.requester),
      ),
    );
  if (editable) wrapper.append(identityEditor(state, actions));
  const warnings = identification.warnings || [];
  if (warnings.length)
    wrapper.append(
      el(
        "div",
        { className: "warning-box" },
        warnings.map((item) =>
          el(
            "p",
            {},
            typeof item === "string"
              ? item
              : item.message || JSON.stringify(item),
          ),
        ),
      ),
    );
  wrapper.append(
    el(
      "div",
      { className: "requests-heading" },
      el(
        "div",
        {},
        el(
          "h2",
          {},
          `${requests.length} ${requests.length === 1 ? "solicitud identificada" : "solicitudes y apartados"}`,
        ),
        el(
          "p",
          {},
          "Selecciona una solicitud para revisar su contenido y su fuente.",
        ),
      ),
      editable
        ? button("＋ Agregar", () => actions.add(), "quiet", {
            className: "button button-quiet button-small",
            disabled: state.busy,
          })
        : null,
    ),
  );
  const list = el("div", { className: "request-list" });
  requests.forEach((request) =>
    list.append(requestCard(request, state, actions, editable)),
  );
  if (!requests.length)
    list.append(
      el(
        "div",
        { className: "empty-requests" },
        "No hay solicitudes identificadas. Revisa el original y agrega las que correspondan antes de confirmar.",
      ),
    );
  wrapper.append(list);
  if (editable)
    wrapper.append(
      el(
        "div",
        { className: "confirm-area" },
        el(
          "p",
          {},
          state.dirty
            ? "Guarda tus cambios antes de confirmar esta identificación."
            : "Al confirmar, indicas que la lista refleja lo pedido en el documento. Esta acción cierra la identificación; todavía no genera una respuesta oficial.",
        ),
        button("Confirmar identificación", actions.confirm, "primary", {
          id: "confirm-identification",
          disabled: state.busy || state.dirty || !requests.length,
        }),
      ),
    );
  return wrapper;
}

function draftBar(state, actions) {
  return el(
    "div",
    { className: "draft-actions", id: "draft-actions" },
    el(
      "p",
      { id: "draft-label" },
      state.dirty
        ? "Tienes cambios sin guardar."
        : "Modo edición · Los cambios se guardan como una nueva versión.",
    ),
    button("Guardar cambios", actions.save, "primary", {
      className: "button button-primary button-small",
      id: "save-draft",
      disabled: state.busy || !state.dirty,
    }),
    button("Cancelar edición", actions.cancelEdit, "quiet", {
      className: "button button-quiet button-small",
      disabled: state.busy,
    }),
  );
}

function identityEditor(state, actions) {
  const identity = state.draft || state.current.identification;
  const detail = el(
    "details",
    { className: "metadata-edit", id: "identity-details" },
    el("summary", {}, "Revisar asunto, solicitante y fecha"),
  );
  if (!state.draft) {
    detail.append(
      el(
        "p",
        { className: "small muted" },
        "Estos datos se leen de la petición. La fecha del documento se conserva tal como aparece.",
      ),
      button("Editar datos de la petición", actions.editIdentity, "quiet", {
        className: "button button-quiet button-small",
        disabled: state.busy,
      }),
    );
    return detail;
  }
  detail.append(
    field(
      "Asunto",
      el("input", {
        value: identity.subject || "",
        maxLength: 500,
        onInput: (event) => {
          identity.subject = event.target.value;
          actions.dirty();
        },
      }),
    ),
    field(
      "Solicitante",
      el("input", {
        value: identity.requester || "",
        maxLength: 500,
        onInput: (event) => {
          identity.requester = event.target.value || null;
          actions.dirty();
        },
      }),
      "Deja vacío si no está identificado en el documento.",
    ),
    field(
      "Fecha escrita en el documento",
      el("input", {
        value: identity.document_date || "",
        maxLength: 200,
        onInput: (event) => {
          identity.document_date = event.target.value || null;
          actions.dirty();
        },
      }),
      "Transcribe el texto literal. No corresponde a la fecha de carga ni a la recepción institucional.",
    ),
  );
  return detail;
}

function requestCard(request, state, actions, editable) {
  const selected = state.selectedId === request.id;
  const editing = state.editingId === request.id;
  const card = el("article", {
    className: `request-card ${selected ? "selected" : ""} ${request.parent_id ? "is-child" : ""}`,
    id: `request-${request.id}`,
  });
  card.append(
    el(
      "button",
      {
        className: "request-select",
        type: "button",
        "aria-expanded": selected,
        "aria-controls": `request-body-${request.id}`,
        onClick: () => actions.select(request.id),
      },
      el("span", { className: "request-label" }, request.label || "—"),
      el(
        "span",
        { className: "request-title" },
        request.title || "Solicitud sin título",
      ),
      el(
        "span",
        { className: "request-chevron", "aria-hidden": "true" },
        selected ? "−" : "+",
      ),
    ),
  );
  if (!selected) return card;
  const body = el("div", {
    className: "request-body",
    id: `request-body-${request.id}`,
  });
  if (editing) body.append(requestEditor(request, state, actions));
  else {
    body.append(
      el("p", { className: "request-description" }, request.description),
    );
    const refs = request.source_refs || [];
    if (refs.length)
      body.append(
        el(
          "details",
          { className: "source-detail", open: true },
          el(
            "summary",
            {},
            `Ver ${refs.length === 1 ? "fragmento de origen" : `${refs.length} fragmentos de origen`}`,
          ),
          refs.map((ref) =>
            el(
              "div",
              {},
              el(
                "button",
                {
                  className: "source-reference",
                  type: "button",
                  onClick: () => actions.source(ref),
                },
                `Página ${ref.page} · ${ref.line_start === ref.line_end ? `línea ${ref.line_start}` : `líneas ${ref.line_start}–${ref.line_end}`} ↗`,
              ),
              el("blockquote", { className: "source-quote" }, ref.quote),
            ),
          ),
        ),
      );
    else
      body.append(
        el(
          "p",
          { className: "warning-box" },
          "Falta vincular esta solicitud con el texto original.",
        ),
      );
    if (editable)
      body.append(
        el(
          "div",
          { className: "request-actions" },
          button(
            "Editar solicitud",
            () => actions.edit(request.id),
            "secondary",
            {
              className: "button button-secondary button-small",
              disabled: state.busy,
            },
          ),
          !request.parent_id
            ? button(
                "Agregar apartado",
                () => actions.add(request.id),
                "quiet",
                {
                  className: "button button-quiet button-small",
                  disabled: state.busy,
                },
              )
            : null,
        ),
      );
  }
  card.append(body);
  return card;
}

function requestEditor(request, state, actions) {
  const all = state.draft.requests;
  const editor = el("div", { className: "editor" });
  const input = (label, property, options = {}) =>
    field(
      label,
      el(options.area ? "textarea" : "input", {
        value: request[property] || "",
        maxLength: property === "label" ? 80 : options.area ? 8000 : 240,
        onInput: (event) => {
          request[property] = event.target.value;
          actions.dirty();
        },
      }),
    );
  editor.append(
    input("Número o apartado", "label"),
    input("Título de la solicitud", "title"),
    input("Qué se solicita", "description", { area: true }),
  );
  const hasChildren = all.some((item) => item.parent_id === request.id);
  const parent = el(
    "select",
    {
      onChange: (event) => {
        request.parent_id = event.target.value || null;
        actions.dirty();
      },
    },
    el("option", { value: "" }, "Solicitud principal"),
    all
      .filter((item) => item.id !== request.id && !item.parent_id)
      .map((item) =>
        el(
          "option",
          { value: item.id },
          `Apartado de ${item.label}: ${item.title}`,
        ),
      ),
  );
  parent.value = request.parent_id || "";
  parent.disabled = hasChildren;
  editor.append(
    field(
      "Relación con otras solicitudes",
      parent,
      hasChildren
        ? "Esta solicitud contiene apartados y se mantiene como principal."
        : null,
    ),
    el(
      "p",
      { className: "source-edit-title" },
      "Ubicación en el texto original",
    ),
  );
  const sourceList = el("div");
  const rebuildSources = () => {
    sourceList.replaceChildren(
      ...request.source_refs.map((ref, index) =>
        sourceEditor(ref, index, request, state, actions, rebuildSources),
      ),
    );
  };
  rebuildSources();
  editor.append(
    sourceList,
    button(
      "＋ Vincular otro fragmento",
      () => {
        const page = state.current.pages?.[0];
        const ref = {
          page: page?.number || 1,
          line_start: 1,
          line_end: 1,
          quote: textLines(page?.text)[0] || "",
        };
        request.source_refs.push(ref);
        actions.dirty();
        rebuildSources();
      },
      "quiet",
      { className: "button button-quiet button-small" },
    ),
    el(
      "div",
      { className: "request-actions" },
      button("Terminar edición", actions.finishEdit, "secondary", {
        className: "button button-secondary button-small",
      }),
      button("Quitar solicitud", () => actions.remove(request.id), "danger", {
        className: "button button-danger button-small",
      }),
    ),
  );
  return editor;
}

function sourceEditor(ref, index, request, state, actions, rebuildSources) {
  const preview = el("p", { className: "quote-preview" });
  const updatePreview = () => {
    ref.quote = quoteFor(state.current.pages || [], ref);
    preview.textContent =
      ref.quote || "Selecciona una página y un rango de líneas válido.";
  };
  updatePreview();
  const controls = ["page", "line_start", "line_end"].map((key, i) =>
    field(
      ["Página", "Línea inicial", "Línea final"][i],
      el("input", {
        type: "number",
        min: 1,
        step: 1,
        value: ref[key],
        "aria-label": `${["Página", "Línea inicial", "Línea final"][i]} del fragmento ${index + 1}`,
        onInput: (event) => {
          ref[key] = Number(event.target.value);
          updatePreview();
          actions.dirty();
        },
      }),
    ),
  );
  return el(
    "div",
    { className: "source-edit" },
    el("div", { className: "source-fields" }, controls),
    preview,
    el(
      "div",
      { className: "source-edit-actions" },
      button("Ver líneas", () => actions.source(ref), "quiet", {
        className: "button button-quiet button-small",
      }),
      button(
        "Quitar fragmento",
        () => {
          request.source_refs.splice(index, 1);
          actions.dirty();
          rebuildSources();
        },
        "quiet",
        { className: "button button-quiet button-small" },
      ),
    ),
  );
}
