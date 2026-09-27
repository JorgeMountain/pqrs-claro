const MAX_CHARS = 3000;
const TYPE_LABELS = {
  information: "Solicitud de información",
  documents: "Solicitud de documentos",
  individual: "Solicitud de acción individual",
  general: "Solicitud de acción general",
  consultation: "Consulta",
  complaint: "Queja",
  claim: "Reclamo",
  suggestion: "Sugerencia",
  denunciation: "Denuncia",
  congratulation: "Felicitación",
  undetermined: "No determinada"
};
const MODEL_LABELS = {
  english: "English",
  multilingual: "Multilingüe",
  "typed-decisions": "Typed decisions"
};
const NEUTRAL_SAMPLE = [
  "Cordial saludo.",
  "",
  "Estoy interesado en el examen de admisión presencial de pregrado de la Universidad de Antioquia para el período 2027-1.",
  "",
  "Para comenzar, ¿qué competencias evalúa el examen y qué porcentaje tiene cada una en la calificación?",
  "",
  "También quisiera saber cuánto tiempo dura como máximo la prueba de admisión.",
  "",
  "En cuanto al calendario de esta convocatoria, ¿en qué fechas está prevista la presentación del examen?",
  "",
  "Para organizar la documentación, ¿entre qué fechas se puede imprimir la credencial y cuál es la ruta para consultarla en el portal de la Universidad?",
  "",
  "¿En qué documento se informa el campus, el bloque y el aula asignados para presentar el examen presencial?",
  "",
  "El día de la prueba presencial, ¿con cuánta anticipación recomienda la Universidad estar en el aula?",
  "",
  "Sobre los elementos necesarios, ¿qué materiales y documentos está permitido utilizar durante el examen presencial?",
  "",
  "¿Está permitido utilizar el teléfono celular o una calculadora durante la prueba presencial?",
  "",
  "Después del examen, ¿cuándo se publican los resultados y hasta qué fecha estarán disponibles para consulta en el portal?",
  "",
  "Finalmente, ¿qué recurso web ofrece la Universidad para conocer la metodología del examen y prepararse para presentarlo?",
  "",
  "Gracias por la orientación.",
  "",
  "Atentamente,",
  "Aspirante de demostración"
].join("\n");
const RUDE_SAMPLE = "Estoy cansado de que ignoren mis mensajes. Son unos incompetentes y espero una respuesta clara sobre el estado de mi solicitud.";
const $ = (selector) => document.querySelector(selector);
const textArea = $("#requestText");
const runButton = $("#classifyBtn");
let modelReady = false;
let jevReady = false;
const isCloud = () => $("#provider").value === "jev";
let busy = false;
let availableModels = new Set();
let lastResult = null;

function setMode(mode) {
  const textMode = mode === "text";
  $("#textSource").hidden = !textMode;
  $("#pdfSource").hidden = textMode;
  if (textMode) {
    $("#requestFile").value = "";
    $("#fileInfo").textContent = "Se extraerá el texto seleccionable. Este banco no hace OCR.";
  } else {
    textArea.value = "";
    updateCount();
  }
  clearResult();
}

function updateCount() {
  $("#charCount").textContent = textArea.value.length.toLocaleString("es-CO") + " / " + MAX_CHARS.toLocaleString("es-CO");
}

function clearResult() {
  lastResult = null;
  $("#emptyState").hidden = false;
  $("#resultBox").hidden = true;
  $("#errorBox").hidden = true;
  $("#resultBox").replaceChildren();
  $("#resultBadge").textContent = "SIN PRUEBA";
  $("#resultBadge").classList.remove("done");
}

function updateButton() {
  const source = document.querySelector('input[name="source"]:checked').value;
  const hasText = textArea.value.trim().length > 0;
  const hasFile = $("#requestFile").files.length > 0;
  const typeModelReady = availableModels.has($("#typeModel").value);
  const rudeModelReady = availableModels.has($("#rudeModel").value);
  runButton.disabled = busy || !(isCloud() ? jevReady : modelReady && typeModelReady && rudeModelReady) || (source === "text" ? !hasText : !hasFile);
}

function updateModelNote() {
  $("#modelNote").textContent = "Tipo: " + MODEL_LABELS[$("#typeModel").value]
    + " · Lenguaje: " + MODEL_LABELS[$("#rudeModel").value]
    + " · ambos análisis se hacen por separado en Laya local.";
}

async function checkStatus() {
  const chip = $("#modelStatus");
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    const status = await response.json();
    modelReady = Boolean(status.connected);
    jevReady = Boolean(status.jev_configured);
    availableModels = new Set(Object.entries(status.models || {})
      .filter(([, state]) => state === "ready")
      .map(([name]) => name));
    chip.classList.toggle("ready", isCloud() ? jevReady : modelReady);
    chip.classList.toggle("down", !(isCloud() ? jevReady : modelReady));
    chip.querySelector("span:last-child").textContent = isCloud() ? (jevReady ? "JEV · clave configurada" : "JEV · falta configurar clave") : status.message;
    chip.title = status.version ? "Laya " + status.version + " · " + status.device : status.message;
  } catch {
    modelReady = false;
    jevReady = false;
    chip.classList.add("down");
    chip.querySelector("span:last-child").textContent = "No se pudo comprobar Laya local.";
  }
  updateButton();
}

function showError(message) {
  $("#emptyState").hidden = true;
  $("#resultBox").hidden = true;
  $("#errorBox").hidden = false;
  $("#errorBox").textContent = message;
  $("#resultBadge").textContent = "REVISAR";
  $("#resultBadge").classList.remove("done");
}

function percent(value) {
  const safe = Number.isFinite(Number(value)) ? Math.max(0, Math.min(1, Number(value))) : 0;
  return Math.round(safe * 100) + "%";
}

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  return element;
}

function renderType(container, answer) {
  const section = document.createElement("section");
  section.className = "result-section";
  section.append(textElement("h3", "", "Tipo de solicitud sugerido"));
  const top = document.createElement("div");
  top.className = "answer-line";
  const category = answer && TYPE_LABELS[answer.choice] ? TYPE_LABELS[answer.choice] : "No determinado";
  top.append(textElement("strong", "answer-value", category));
  const confidence = answer?.confidence == null ? NaN : Number(answer.confidence);
  if (Number.isFinite(confidence)) {
    const pill = document.createElement("span");
    pill.className = "answer-confidence";
    pill.title = "Confianza interna del modelo; no equivale a certeza calibrada.";
    pill.append("conf. ", textElement("b", "", percent(confidence)));
    top.append(pill);
  }
  section.append(top);
  section.append(textElement("p", "prob-note", "Distribución que estima el modelo (no calibrada):"));
  const list = document.createElement("div");
  list.className = "prob-list";
  const probs = answer && answer.probabilities && typeof answer.probabilities === "object"
    ? Object.entries(answer.probabilities).sort((a, b) => b[1] - a[1]) : [];
  for (const [key, value] of probs) {
    const row = document.createElement("div");
    row.className = "prob-row" + (key === answer.choice ? " top" : "");
    row.append(textElement("span", "prob-label", TYPE_LABELS[key] || key));
    const track = document.createElement("span");
    track.className = "prob-track";
    const fill = document.createElement("span");
    fill.className = "prob-fill";
    fill.style.width = percent(value);
    track.append(fill);
    row.append(track, textElement("span", "prob-value", percent(value)));
    list.append(row);
  }
  section.append(list);
  container.append(section);
}

function renderRude(container, answer) {
  const section = document.createElement("section");
  section.className = "result-section";
  section.append(textElement("h3", "", "¿El solicitante dirige insultos o expresiones degradantes?"));
  const isRude = Number(answer && answer.noul) >= 0.5;
  const row = document.createElement("div");
  row.className = "rude-result";
  const icon = textElement("span", "rude-icon" + (isRude ? " yes" : ""), isRude ? "!" : "✓");
  icon.setAttribute("aria-hidden", "true");
  const copy = document.createElement("div");
  copy.className = "rude-copy";
  copy.append(
    textElement("strong", "", isRude ? "Sí, según el modelo" : "No, según el modelo"),
    textElement("span", "", "Puntuación de “sí”: " + percent(answer && answer.noul))
  );
  row.append(icon, copy);
  section.append(row);
  section.append(textElement("p", "prob-note", "Una expresión ofensiva citada para relatar hechos no se atribuye automáticamente al solicitante. Este resultado requiere revisión del contexto; no determina la admisión de la petición."));
  const confidence = answer?.confidence == null ? NaN : Number(answer.confidence);
  if (Number.isFinite(confidence)) {
    section.append(textElement("p", "prob-note", "Confianza interna del modelo: " + percent(confidence) + " (no calibrada)."));
  }
  container.append(section);
}

function renderResult(data) {
  lastResult = data;
  const result = data.result;
  const answers = result.answers;
  const container = $("#resultBox");
  container.replaceChildren();
  renderType(container, answers.petition_type);
  renderRude(container, answers.rude_language);

  const metadata = document.createElement("div");
  metadata.className = "meta-line";
  const routing = result.routing || {};
  const routedModels = routing.models || {};
  metadata.append(
    textElement("span", "meta-pill", "Tipo: " + (MODEL_LABELS[routedModels.petition_type] || routedModels.petition_type || "Laya")),
    textElement("span", "meta-pill", "Lenguaje: " + (MODEL_LABELS[routedModels.rude_language] || routedModels.rude_language || "Laya")),
    textElement("span", "meta-pill", (result.latency_ms || 0) + " ms"),
    textElement("span", "meta-pill", (result.usage && result.usage.input_tokens || "?") + " tokens de entrada"),
    textElement("span", "meta-pill", data.source === "PDF" ? "PDF · " + data.page_count + " páginas" : "Texto pegado")
  );
  container.append(metadata);

  const warnings = [...(data.warnings || [])];
  const tokens = Number(result.usage && (result.usage.max_input_tokens ?? result.usage.input_tokens));
  if (data.provider !== "jev" && Number.isFinite(tokens) && tokens >= 900) {
    warnings.push("La entrada quedó cerca del límite de contexto de Laya (1.024 tokens). Comprueba que el modelo haya considerado todo el contenido.");
  }
  for (const message of warnings) container.append(textElement("p", "warning", message));

  const details = document.createElement("details");
  details.className = "raw-details";
  details.append(textElement("summary", "", "Ver respuesta técnica del modelo"));
  details.append(textElement("pre", "", JSON.stringify(result, null, 2)));
  container.append(details);

  $("#emptyState").hidden = true;
  $("#errorBox").hidden = true;
  container.hidden = false;
  $("#resultBadge").textContent = "PRUEBA COMPLETA";
  $("#resultBadge").classList.add("done");
}

async function classify() {
  if (busy || !(isCloud() ? jevReady : modelReady)) return;
  const source = document.querySelector('input[name="source"]:checked').value;
  const payload = new FormData();
  if (source === "text") {
    if (!textArea.value.trim()) return showError("Pega el texto que quieres probar.");
    payload.append("text", textArea.value);
  } else {
    const file = $("#requestFile").files[0];
    if (!file) return showError("Selecciona un PDF.");
    if (file.size > 10 * 1024 * 1024) return showError("El PDF supera el límite de 10 MB.");
    payload.append("file", file);
  }
  payload.append("provider", $("#provider").value);
  payload.append("type_model", $("#typeModel").value);
  payload.append("rude_model", $("#rudeModel").value);
  busy = true;
  $("#provider").disabled = true;
  runButton.disabled = true;
  runButton.querySelector("span:first-child").textContent = isCloud() ? "Analizando con JEV en la nube…" : "Analizando localmente…";
  $("#errorBox").hidden = true;
  try {
    const response = await fetch("/api/classify", { method: "POST", body: payload, cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "No se pudo clasificar la comunicación.");
    renderResult(data);
  } catch (error) {
    showError(error instanceof Error ? error.message : "No se pudo clasificar la comunicación.");
  } finally {
    busy = false;
    $("#provider").disabled = false;
    runButton.querySelector("span:first-child").textContent = isCloud() ? "Enviar a JEV y clasificar" : "Clasificar con Laya";
    updateButton();
  }
}

document.querySelectorAll('input[name="source"]').forEach((input) => {
  input.addEventListener("change", () => setMode(input.value));
});
textArea.addEventListener("input", () => {
  clearResult();
  updateCount();
  updateButton();
});
$("#requestFile").addEventListener("change", (event) => {
  clearResult();
  const file = event.target.files[0];
  $("#fileInfo").textContent = file
    ? file.name + " · " + (file.size / 1024 / 1024).toFixed(2) + " MB · se extraerá solo el texto"
    : "Se extraerá el texto seleccionable. Este banco no hace OCR.";
  updateButton();
});
$("#neutralExample").addEventListener("click", () => {
  document.querySelector('input[name="source"][value="text"]').checked = true;
  setMode("text");
  textArea.value = NEUTRAL_SAMPLE;
  updateCount();
  updateButton();
});
$("#rudeExample").addEventListener("click", () => {
  document.querySelector('input[name="source"][value="text"]').checked = true;
  setMode("text");
  textArea.value = RUDE_SAMPLE;
  updateCount();
  updateButton();
});
$("#classifyBtn").addEventListener("click", classify);
$("#clearBtn").addEventListener("click", () => {
  textArea.value = "";
  $("#requestFile").value = "";
  $("#fileInfo").textContent = "Se extraerá el texto seleccionable. Este banco no hace OCR.";
  updateCount();
  clearResult();
  updateButton();
});
["#typeModel", "#rudeModel"].forEach((selector) => {
  $(selector).addEventListener("change", () => {
    clearResult();
    updateModelNote();
    updateButton();
  });
});
updateCount();
updateModelNote();
checkStatus();
window.setInterval(checkStatus, 5000);

$("#provider").addEventListener("change", () => {
  clearResult();
  $("#localModels").hidden = isCloud();
  $(".privacy span:last-child").textContent = isCloud()
    ? "Prueba en la nube: al clasificar, el texto se envía a Vercel AI Gateway y TypeSafe. Usa datos ficticios o anonimizados. Este laboratorio no guarda el contenido ni modifica expedientes; el tratamiento externo depende del proveedor."
    : "Prueba temporal y local. El texto no se guarda ni se agrega a expedientes. Se envía a Laya en este equipo.";
  $(".local-note").textContent = isCloud() ? "JEV · typesafe-ai/jev · clave privada en el servidor local" : "Inferencia local en 127.0.0.1:8770";
  runButton.querySelector("span:first-child").textContent = isCloud() ? "Enviar a JEV y clasificar" : "Clasificar con Laya";
  updateButton();
  checkStatus();
});
