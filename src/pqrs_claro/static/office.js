import { officeView } from "./office-view.js";

const storagePrefix = "pqrs-claro-office-v1:";
const signature = (form) =>
  JSON.stringify({
    metadata: Object.fromEntries(
      Object.entries(form.metadata).sort(([a], [b]) => a.localeCompare(b)),
    ),
    prepared_by: form.prepared_by,
    attachment_source_ids: [...form.attachment_source_ids].sort(),
  });
function storedGeneration(caseId) {
  try {
    return JSON.parse(
      sessionStorage.getItem(storagePrefix + "generated:" + caseId),
    );
  } catch {
    return null;
  }
}
function localDate() {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function blankForm(defaults) {
  return {
    prepared_by: "",
    attachment_source_ids: [],
    metadata: {
      institution: "",
      department: "",
      city: "",
      issue_date: localDate(),
      office_number: "",
      petition_number: "",
      recipient: defaults.recipient || "",
      recipient_contact: "",
      subject: defaults.subject || "",
      signer_name: "",
      signer_role: "",
    },
  };
}
function storedForm(caseId) {
  try {
    const value = JSON.parse(sessionStorage.getItem(storagePrefix + caseId));
    return value?.metadata && Array.isArray(value.attachment_source_ids)
      ? value
      : null;
  } catch {
    return null;
  }
}
export function createOffice({
  api,
  notify,
  getCase,
  hasReviewChanges,
  render,
  back,
}) {
  const cases = new Map();
  let state = null;
  const path = (s, suffix = "") =>
    `/api/cases/${encodeURIComponent(s.caseId)}/office${suffix}`;
  function setCase(current) {
    if (!current) {
      state = null;
      return;
    }
    if (!cases.has(current.id))
      cases.set(current.id, {
        caseId: current.id,
        form: storedForm(current.id),
        generated: storedGeneration(current.id),
        data: null,
        preview: null,
        previewSignature: null,
        loaded: false,
        loading: false,
        busy: false,
        error: null,
        expanded: new Set(),
        run: null,
        selectedRun: null,
        page: 1,
        poll: null,
      });
    state = cases.get(current.id);
  }
  const refresh = (s) => {
    if (state === s) render();
  };
  function persist(s) {
    try {
      sessionStorage.setItem(storagePrefix + s.caseId, JSON.stringify(s.form));
      if (s.generated)
        sessionStorage.setItem(
          storagePrefix + "generated:" + s.caseId,
          JSON.stringify(s.generated),
        );
    } catch {
      s.storageWarning = true;
    }
  }
  const changedPreview = (s = state) =>
    !s.preview ||
    s.previewSignature !== signature(s.form) ||
    s.preview.approval_snapshot_hash !== s.data?.approval_snapshot_hash;
  function selectedMatchesForm(s = state) {
    return Boolean(
      s.run &&
      s.form &&
      ((s.generated?.run_id === s.run.id &&
        s.generated.form_signature === signature(s.form)) ||
        (s.run.preview_hash === s.preview?.preview_hash && !changedPreview(s))),
    );
  }
  function schedule(s) {
    clearTimeout(s.poll);
    if (
      s.run?.status === "generating" ||
      s.data?.latest?.status === "generating"
    )
      s.poll = setTimeout(() => load({ quiet: true, target: s }), 1800);
  }
  async function load({ quiet = false, target = state } = {}) {
    const s = target;
    if (!s || s.loading) return;
    s.loading = true;
    if (!quiet) refresh(s);
    try {
      s.data = await api(path(s));
      if (!s.form) s.form = blankForm(s.data.defaults || {});
      if (!s.selectedRun || s.selectedRun === s.data.latest?.id)
        s.run = s.data.latest;
      else
        s.run = await api(
          path(s, `/runs/${encodeURIComponent(s.selectedRun)}`),
        );
      s.loaded = true;
      s.error = null;
      persist(s);
    } catch (error) {
      s.error = error.message;
    } finally {
      s.loading = false;
      refresh(s);
      schedule(s);
    }
  }
  async function task(work) {
    const s = state;
    if (!s || s.busy) return;
    s.busy = true;
    s.error = null;
    refresh(s);
    try {
      await work(s);
    } catch (error) {
      s.error = error.message;
    } finally {
      s.busy = false;
      refresh(s);
      schedule(s);
    }
  }
  function validReview(s) {
    if (hasReviewChanges(s.caseId))
      throw new Error(
        "Hay cambios de revisión sin guardar en este expediente. Vuelve a la fase 6 para guardarlos, comprobarlos y aprobarlos o descartar la edición local.",
      );
    if (!s.data?.eligible)
      throw new Error(
        "Todas las respuestas vigentes deben estar aprobadas antes de preparar el oficio.",
      );
  }
  const actions = {
    load,
    back,
    changedPreview,
    selectedMatchesForm,
    hasReviewChanges: () => (state ? hasReviewChanges(state.caseId) : false),
    change(rerender = false) {
      const s = state;
      persist(s);
      if (rerender) {
        refresh(s);
        return;
      }
      const generate = document.getElementById("office-generate");
      if (generate) generate.disabled = true;
      const previewState = document.getElementById("office-preview-state");
      if (previewState)
        previewState.textContent =
          "Los datos cambiaron. Prepara de nuevo la vista previa para generar esta versión.";
      const context = document.getElementById("office-file-context");
      if (context)
        context.textContent =
          "Este archivo se generó con los datos anteriores. Puedes descargar esa versión guardada o preparar una nueva.";
      const localState = document.getElementById("office-form-state");
      if (localState)
        localState.textContent =
          "Datos conservados en esta pestaña. La versión del oficio se guardará al generar los archivos.";
    },
    preview() {
      return task(async (s) => {
        validReview(s);
        const form = structuredClone(s.form);
        const inputSignature = signature(form);
        const preview = await api(path(s, "/preview"), {
          method: "POST",
          body: JSON.stringify({
            ...form,
            approval_snapshot_hash: s.data.approval_snapshot_hash,
          }),
        });
        s.preview = preview;
        s.previewSignature = inputSignature;
        s.expanded.add("office-text-preview");
        notify(
          "Vista previa preparada. Comprueba los datos y los anexos antes de generar los archivos.",
        );
      });
    },
    generate() {
      return task(async (s) => {
        validReview(s);
        if (changedPreview(s))
          throw new Error(
            "Prepara una vista previa con los datos actuales antes de generar.",
          );
        if (!s.data.capabilities?.pdf_available)
          throw new Error(
            s.data.capabilities?.error ||
              "La conversión a PDF no está disponible en este equipo.",
          );
        s.run = await api(path(s, "/generate"), {
          method: "POST",
          body: JSON.stringify({
            ...s.form,
            approval_snapshot_hash: s.data.approval_snapshot_hash,
            preview_hash: s.preview.preview_hash,
          }),
        });
        s.selectedRun = s.run.id;
        s.page = 1;
        s.generated = { run_id: s.run.id, form_signature: signature(s.form) };
        persist(s);
        s.data.latest = s.run;
        notify(
          s.run.status === "ready"
            ? "Los archivos de esta versión ya estaban preparados y se conservaron."
            : "Generación iniciada. El contenido aprobado se conserva sin reescribirlo.",
        );
      });
    },
    selectRun(id) {
      return task(async (s) => {
        s.run = await api(path(s, `/runs/${encodeURIComponent(id)}`));
        s.selectedRun = id;
        s.page = 1;
      });
    },
    page(number) {
      state.page = number;
      refresh(state);
      document
        .getElementById("office-pdf-page")
        ?.focus({ preventScroll: true });
    },
    download(kind) {
      return task(async (s) => {
        validReview(s);
        if (!s.run || s.run.status !== "ready" || s.run.stale)
          throw new Error(
            "Esta versión no está disponible para descargar. Revisa sus pendientes y actualiza el estado.",
          );
        const file = s.run.files?.find((item) => item.kind === kind);
        if (!file) throw new Error("No se encontró el archivo solicitado.");
        const response = await fetch(
          path(s, `/runs/${encodeURIComponent(s.run.id)}/files/${kind}`),
        );
        if (!response.ok) {
          let problem;
          try {
            problem = await response.json();
          } catch {
            problem = null;
          }
          throw new Error(
            typeof problem?.detail === "string"
              ? problem.detail
              : "El archivo ya no está disponible para esta versión. Actualiza el estado del oficio.",
          );
        }
        const blob = await response.blob();
        validReview(s);
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = file.name;
        anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    },
  };
  return {
    get state() {
      return state;
    },
    setCase,
    load,
    hasUnprotectedChanges() {
      return [...cases.values()].some((s) => s.storageWarning && s.form);
    },
    view() {
      return officeView({ state, actions });
    },
  };
}
