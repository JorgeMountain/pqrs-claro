export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (
      value === null ||
      value === undefined ||
      (value === false && !key.startsWith("aria-"))
    )
      continue;
    if (key.startsWith("on"))
      node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "className") node.className = value;
    else if (["disabled", "hidden", "open", "checked"].includes(key))
      node[key] = value;
    else if (key === "value") node.value = value;
    else node.setAttribute(key, String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child !== null && child !== undefined && child !== false)
      node.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  }
  return node;
}

export const button = (label, action, type = "secondary", attrs = {}) =>
  el(
    "button",
    {
      type: "button",
      className: `button button-${type}`,
      onClick: action,
      ...attrs,
    },
    label,
  );
export const running = (status) =>
  ["reading", "identifying", "confirming"].includes(status);
export const statusLabel = (status) =>
  ({
    uploaded: "Por analizar",
    reading: "Leyendo documento",
    identifying: "Identificando solicitudes",
    confirming: "Guardando confirmación",
    needs_review: "Por revisar",
    confirmed: "Identificación confirmada",
    error: "Requiere atención",
  })[status] || "Preparando";
export function textLines(text) {
  if (!text) return [];
  const lines = text.split(/\r\n|[\n\r\v\f\u001c-\u001e\u0085\u2028\u2029]/);
  if (lines.at(-1) === "") lines.pop();
  return lines;
}
export function dateLabel(value, withTime = false) {
  if (!value) return "Sin registrar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("es-CO", {
    dateStyle: "medium",
    ...(withTime ? { timeStyle: "short" } : {}),
  }).format(date);
}

export function welcome(config, actions) {
  const drop = el(
    "div",
    { className: "dropzone" },
    el("span", { className: "document-icon", "aria-hidden": "true" }, "PDF"),
    el(
      "p",
      { className: "dropzone-title" },
      "Empieza con el documento original",
    ),
    button("Seleccionar un PDF", actions.pickFile, "primary", {
      disabled: actions.busy,
    }),
    el(
      "p",
      { className: "upload-help" },
      `O arrástralo aquí · Hasta ${config?.max_upload_mb || 20} MB y ${config?.max_pages || 40} páginas`,
    ),
  );
  let dragCount = 0;
  drop.addEventListener("dragenter", (event) => {
    event.preventDefault();
    dragCount++;
    drop.classList.add("dragover");
  });
  drop.addEventListener("dragover", (event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  drop.addEventListener("dragleave", () => {
    dragCount--;
    if (!dragCount) drop.classList.remove("dragover");
  });
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    dragCount = 0;
    drop.classList.remove("dragover");
    if (!actions.busy && event.dataTransfer.files[0])
      actions.upload(event.dataTransfer.files[0]);
  });
  return el(
    "div",
    { className: "intro-grid" },
    el(
      "section",
      { className: "upload-panel", "aria-labelledby": "upload-heading" },
      el("p", { className: "section-kicker" }, "UN EXPEDIENTE A LA VEZ"),
      el("h2", { id: "upload-heading" }, "Primero, entender bien."),
      el(
        "p",
        { className: "muted" },
        "Carga la petición. Encontraremos sus solicitudes y el fragmento exacto de donde sale cada una.",
      ),
      drop,
      el(
        "div",
        { className: "demo-entry" },
        button("Practicar con un ejemplo ↗", actions.demo, "quiet", {
          disabled: actions.busy || !config?.ready,
        }),
        el(
          "p",
          {},
          "Documento ficticio de tres solicitudes. El análisis con IA es real.",
        ),
      ),
    ),
    el(
      "aside",
      { className: "intro-aside", "aria-labelledby": "expect-heading" },
      el("h2", { id: "expect-heading" }, "Qué vas a poder comprobar"),
      el(
        "ol",
        { className: "explain-list" },
        explain(
          "01",
          "Qué pide la persona",
          "Una lista de solicitudes y apartados, conservando su relación con el original.",
        ),
        explain(
          "02",
          "De dónde salió cada solicitud",
          "La página, las líneas y la cita que te permiten verificar la interpretación.",
        ),
        explain(
          "03",
          "Qué necesitas corregir",
          "Puedes ajustar el texto, agregar lo que falte y confirmar cuando esté completo.",
        ),
      ),
      el(
        "p",
        { className: "intro-boundary" },
        el("strong", {}, "Tú confirmas la identificación."),
        " El sistema conserva el original y guarda cada versión de tu revisión.",
      ),
    ),
  );
}

function explain(number, title, description) {
  return el(
    "li",
    {},
    el("span", { className: "explain-number", "aria-hidden": "true" }, number),
    el("div", {}, el("h3", {}, title), el("p", {}, description)),
  );
}

export function progress(current, actions) {
  if (current.status === "confirming")
    return el(
      "section",
      {
        className: "panel progress-panel",
        "aria-live": "polite",
        "aria-busy": "true",
      },
      el("h2", {}, "Guardando tu confirmación"),
      el(
        "p",
        {},
        "La versión revisada está cerrando la etapa de identificación.",
      ),
    );
  if (current.status === "uploaded")
    return el(
      "section",
      { className: "panel file-ready" },
      el("p", { className: "section-kicker" }, "DOCUMENTO GUARDADO"),
      el("h2", {}, "Listo para leer tu petición"),
      el(
        "p",
        {},
        "Leeremos el PDF y usaremos IA para proponer las solicitudes. Después podrás revisar cada una junto a su fuente.",
      ),
      button("Analizar petición", actions.analyze, "primary", {
        disabled: actions.busy || !actions.ready,
      }),
    );
  if (current.status === "error")
    return el(
      "section",
      { className: "panel file-ready error-panel", role: "alert" },
      el("div", { className: "error-label" }, "EL PROCESO SE DETUVO"),
      el("h2", {}, "Necesitamos revisar este documento"),
      el(
        "p",
        {},
        current.error ||
          "No fue posible completar el análisis. Tu archivo original sigue guardado.",
      ),
      button("Reintentar análisis", actions.analyze, "primary", {
        disabled: actions.busy || !actions.ready,
      }),
    );
  const reading = current.status === "reading";
  return el(
    "section",
    {
      className: "panel progress-panel",
      "aria-busy": "true",
      "aria-live": "polite",
    },
    el("p", { className: "section-kicker" }, "ANÁLISIS EN CURSO"),
    el(
      "h2",
      {},
      reading ? "Leyendo el documento" : "Encontrando las solicitudes",
    ),
    el(
      "p",
      {},
      reading
        ? "Se está extrayendo el texto de cada página y comprobando su calidad."
        : "La IA está relacionando cada solicitud con su fragmento de origen.",
    ),
    el(
      "div",
      { className: "progress-track" },
      progressRow("✓", "Original conservado", "complete"),
      progressRow(
        reading ? "2" : "✓",
        "Lectura por página",
        reading ? "current" : "complete",
      ),
      progressRow("3", "Identificación con IA", reading ? "" : "current"),
      progressRow("4", "Tu revisión", ""),
    ),
    el(
      "div",
      { className: "loading-bars", "aria-hidden": "true" },
      el("span"),
      el("span"),
      el("span"),
    ),
    el(
      "p",
      {},
      "El avance se guarda. Puedes volver a este expediente después.",
    ),
  );
}

function progressRow(number, label, className) {
  return el(
    "div",
    { className: `progress-row ${className}` },
    el("span", { className: "progress-mark", "aria-hidden": "true" }, number),
    label,
  );
}

export function original(current, pageNumber, highlight, onPage) {
  const pages = current.pages || [];
  const page = pages.find((item) => item.number === pageNumber) || pages[0];
  const panel = el(
    "aside",
    {
      className: "original-panel",
      "aria-label": "Documento original",
      id: "original-panel",
    },
    el(
      "div",
      { className: "panel-head" },
      el("h2", {}, "Documento original"),
      el(
        "a",
        {
          href: `/api/cases/${encodeURIComponent(current.id)}/original`,
          target: "_blank",
          rel: "noopener",
          className: "small-link",
        },
        "Abrir PDF ↗",
      ),
    ),
  );
  if (!page) {
    panel.append(
      el(
        "div",
        { className: "empty-original" },
        "La vista por página estará disponible cuando termine la lectura. Puedes abrir el PDF original desde el enlace superior.",
      ),
    );
    return panel;
  }
  const select = el(
    "select",
    {
      id: "original-page",
      "aria-label": "Página del documento",
      onChange: (event) => onPage(Number(event.target.value)),
    },
    pages.map((item) =>
      el("option", { value: item.number }, `Página ${item.number}`),
    ),
  );
  select.value = String(page.number);
  panel.append(
    el(
      "div",
      { className: "original-toolbar" },
      select,
      el("span", { className: "muted" }, `de ${pages.length}`),
    ),
  );
  const img = el("img", {
    className: "page-image",
    src: `/api/cases/${encodeURIComponent(current.id)}/pages/${page.number}.png`,
    alt: `Página ${page.number} del documento ${current.filename}`,
    loading: "lazy",
  });
  img.addEventListener("error", () =>
    img.replaceWith(
      el(
        "div",
        { className: "image-error" },
        "La imagen no está disponible. Puedes consultar el PDF y el texto de esta página.",
      ),
    ),
  );
  panel.append(
    img,
    el(
      "p",
      { className: "page-caption" },
      page.method === "ocr"
        ? "Lectura mediante OCR · Comprueba nombres, fechas y números."
        : "Original conservado · La numeración de líneas corresponde al texto extraído.",
    ),
  );
  if (page.needs_review)
    panel.append(
      el(
        "p",
        { className: "warning-box" },
        "Esta página necesita revisión de lectura. Compara el texto con la imagen.",
      ),
    );
  const active = highlight?.page === page.number;
  const lines = textLines(page.text);
  const listing = el(
    "ol",
    {
      className: "line-list",
      "aria-label": `Texto de la página ${page.number} con líneas numeradas`,
    },
    lines.map((text, index) =>
      el(
        "li",
        {
          className:
            active &&
            index + 1 >= highlight.line_start &&
            index + 1 <= highlight.line_end
              ? "highlight"
              : "",
          id: `source-line-${index + 1}`,
        },
        text || " ",
      ),
    ),
  );
  panel.append(
    el(
      "details",
      { className: "source-text", open: Boolean(active) },
      el("summary", {}, "Ver texto y líneas de esta página"),
      listing,
    ),
  );
  return panel;
}

export function processView(current) {
  return el(
    "details",
    { className: "process", id: "process-details" },
    el("summary", {}, "Ver cómo funciona este proceso"),
    el(
      "div",
      { className: "process-body" },
      el(
        "p",
        {},
        el("strong", {}, "Python lee y comprueba. "),
        "Conserva el PDF, extrae el texto por página y verifica que las citas correspondan a líneas del documento.",
      ),
      el(
        "p",
        {},
        el("strong", {}, "La IA interpreta. "),
        "Propone el asunto y las solicitudes a partir del texto. Su resultado necesita tu revisión.",
      ),
      el(
        "p",
        {},
        el("strong", {}, "LangGraph coordina. "),
        "Organiza las etapas, guarda el avance y espera tu confirmación antes de cerrar la identificación.",
      ),
      el(
        "p",
        {},
        el("strong", {}, "Tú decides. "),
        "Puedes corregir las solicitudes y confirmar una versión concreta. En esta etapa todavía no se redactan respuestas.",
      ),
      el(
        "ol",
        { className: "event-list" },
        (current.events || []).map((event) =>
          el(
            "li",
            {},
            el(
              "span",
              { className: "event-time" },
              dateLabel(event.created_at, true),
            ),
            event.message,
          ),
        ),
      ),
    ),
  );
}

export function metadata(current, identification) {
  const row = (label, value) =>
    el("div", {}, el("dt", {}, label), el("dd", {}, value));
  return el(
    "dl",
    { className: "metadata" },
    row(
      "Fecha escrita en la petición",
      identification?.document_date || "No identificada",
    ),
    row(
      "Recepción institucional",
      current.received_at
        ? dateLabel(current.received_at, true)
        : "Sin registrar",
    ),
    row("Carga en este sistema", dateLabel(current.created_at, true)),
  );
}
