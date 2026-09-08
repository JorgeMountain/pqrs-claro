import { reviewView } from "./review-view.js";
import {
  makeLocal,
  loadLocal,
  persistLocal,
  isUnsent,
  hasStoredUnsent,
  downloadLocal,
  resetFact,
  loadCaseLocals,
  removeLocal,
} from "./review-local.js";

export function createReview({
  api,
  notify,
  getCase,
  getDrafts,
  getSources,
  render,
  showSource,
  openSources,
  openLibrary,
  openOffice,
}) {
  const cases = new Map();
  let state = null;
  const path = (s, suffix = "") =>
    `/api/cases/${encodeURIComponent(s.caseId)}/review${suffix}`;
  const requestPath = (row, suffix = "") =>
    `/requests/${encodeURIComponent(row.request_id)}${suffix}`;
  function setCase(current) {
    if (!current) {
      state = null;
      return;
    }
    if (!cases.has(current.id))
      cases.set(current.id, {
        caseId: current.id,
        data: null,
        locals: loadCaseLocals(current.id),
        selected: null,
        loading: false,
        loaded: false,
        busy: false,
        error: null,
        expanded: new Set(),
        history: new Map(),
        poll: null,
      });
    state = cases.get(current.id);
  }
  function localFor(row, s = state) {
    if (!s.locals.has(row.request_id))
      s.locals.set(row.request_id, loadLocal(s.caseId, row));
    return s.locals.get(row.request_id);
  }
  function persist(row, local, s = state) {
    if (!persistLocal(s.caseId, row.request_id, local)) s.storageWarning = true;
  }
  function accept(row, s, force = false) {
    const previous = localFor(row, s);
    if (force || !previous.dirty) {
      const local = makeLocal(row, previous);
      s.locals.set(row.request_id, local);
      persist(row, local, s);
    }
    if (s.data) {
      const index = s.data.requests.findIndex(
        (item) => item.request_id === row.request_id,
      );
      if (index >= 0) s.data.requests[index] = row;
    }
  }
  function refresh(s = state) {
    if (s === state) render();
  }
  function schedule(s) {
    clearTimeout(s.poll);
    if (s.data?.requests?.some((row) => row.status === "checking"))
      s.poll = setTimeout(() => load({ quiet: true, target: s }), 1800);
  }
  async function load({ quiet = false, target = state } = {}) {
    const s = target;
    if (!s || s.loading) return;
    s.loading = true;
    if (!quiet) refresh(s);
    try {
      const data = await api(path(s));
      s.data = data;
      for (const row of data.requests || []) accept(row, s);
      s.loaded = true;
      s.error = null;
    } catch (error) {
      s.error = error.message;
    } finally {
      s.loading = false;
      refresh(s);
      schedule(s);
    }
  }
  function changed(row, local, rerender = false) {
    local.dirty = true;
    local.approval = { approved_by: "", note: "", confirmed: false };
    persist(row, local);
    if (rerender) refresh();
    else {
      const indicator = document.getElementById("review-save-state");
      if (indicator)
        indicator.textContent =
          "Cambios sin guardar · Tu edición se conserva en esta pestaña.";
      const save = document.getElementById("review-save");
      if (save)
        save.disabled =
          state.busy ||
          row.status === "checking" ||
          local.revision !== row.revision;
      const start = document.getElementById("review-start");
      if (start) start.disabled = true;
      const next = document.getElementById("continue-office");
      if (next) next.disabled = true;
      const requestLabel = document.querySelector(
        `#review-select-${CSS.escape(row.request_id)} .muted`,
      );
      if (requestLabel) requestLabel.textContent = "Cambios sin guardar";
      const totals = document.getElementById("review-totals");
      if (totals) {
        const rows = state.data.requests || [];
        const dirty = rows.filter((item) => localFor(item).dirty).length;
        const approved = rows.filter(
          (item) => item.approval && !item.stale && !localFor(item).dirty,
        ).length;
        totals.textContent = `${approved} de ${rows.length} respuestas aprobadas · ${dirty} con cambios sin guardar`;
      }
      const check = document.getElementById("review-assess");
      if (check) check.disabled = true;
      const approval = document.getElementById("review-approval");
      if (approval) approval.hidden = true;
      const label = document.getElementById("review-current-status");
      if (label) label.textContent = "Edición sin guardar";
      const evaluation = document.getElementById("review-assessment-state");
      if (evaluation)
        evaluation.textContent =
          "La comprobación guardada corresponde al texto anterior. Guarda y vuelve a comprobar.";
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
      s.error =
        error.status === 409
          ? `${error.message} Tu edición permanece intacta. Puedes descargarla y comparar con la versión guardada.`
          : error.message;
    } finally {
      s.busy = false;
      refresh(s);
      schedule(s);
    }
  }
  async function saveRow(row, s) {
    const local = localFor(row, s);
    if (!local.dirty) return row;
    if (!local.edited_by.trim())
      throw new Error("Escribe quién realizó la edición antes de guardar.");
    const saved = await api(path(s, requestPath(row)), {
      method: "PUT",
      body: JSON.stringify({
        revision: local.revision,
        edited_by: local.edited_by.trim(),
        paragraphs: local.paragraphs,
        pending_resolutions: Object.values(local.resolutions).map(
          ({ pending_id, action, note, cited_chunk_ids, cited_fact_ids }) => ({
            pending_id,
            action,
            note: note || "",
            cited_chunk_ids: cited_chunk_ids || [],
            cited_fact_ids: cited_fact_ids || [],
          }),
        ),
      }),
    });
    accept(saved, s, true);
    s.history.delete(row.request_id);
    return saved;
  }
  async function start() {
    await task(async (s) => {
      if ((s.data?.requests || []).some((row) => localFor(row, s).dirty))
        throw new Error(
          "Guarda las respuestas editadas antes de actualizar las fuentes de la revisión. Conservamos tus cambios.",
        );
      s.data = await api(path(s, "/start"), {
        method: "POST",
        body: JSON.stringify({ version: getCase().version }),
      });
      for (const row of s.data.requests || []) accept(row, s, true);
      s.loaded = true;
      notify(
        "Revisión preparada. El texto humano y los aportes se conservan al actualizar las fuentes.",
      );
    });
  }
  const actions = {
    showSource,
    openSources,
    openLibrary,
    openOffice,
    hasLocalChanges() {
      return (
        [...state.locals.values()].some(isUnsent) ||
        loadCaseLocals(state.caseId).size > 0
      );
    },
    load,
    start,
    localFor,
    changed,
    formChanged(row, local) {
      persist(row, local);
      const next = document.getElementById("continue-office");
      if (next)
        next.disabled =
          state.busy ||
          state.data?.stale ||
          !state.data?.requests?.length ||
          state.data.requests.some((item) => !item.approval || item.stale) ||
          actions.hasLocalChanges();
    },
    select(id) {
      state.selected = id;
      refresh();
      document
        .getElementById(`review-select-${id}`)
        ?.focus({ preventScroll: true });
    },
    save(row) {
      return task(async (s) => {
        await saveRow(row, s);
        notify("Cambios guardados. Comprueba esta versión antes de aprobarla.");
      });
    },
    assess(row) {
      return task(async (s) => {
        if (localFor(row, s).dirty)
          throw new Error(
            "Guarda los cambios antes de comprobar la respuesta.",
          );
        const next = await api(path(s, requestPath(row, "/assess")), {
          method: "POST",
          body: JSON.stringify({ revision: row.revision }),
        });
        accept(next, s, true);
      });
    },
    addFact(row) {
      return task(async (s) => {
        let local = localFor(row, s);
        const form = structuredClone(local.fact);
        if (
          !form.text.trim() ||
          !form.author.trim() ||
          !form.basis.trim() ||
          !form.observed_at
        )
          throw new Error(
            "Completa el hecho, su autor, cómo lo conoce y la fecha de comprobación.",
          );
        row = await saveRow(row, s);
        const next = await api(path(s, requestPath(row, "/facts")), {
          method: "POST",
          body: JSON.stringify({ revision: row.revision, ...form }),
        });
        accept(next, s, true);
        local = localFor(next, s);
        resetFact(local);
        persist(next, local, s);
        s.history.delete(row.request_id);
        notify(
          "Aporte registrado con su autor y fundamento. Selecciónalo en el párrafo o pendiente al que corresponda.",
        );
      });
    },
    removeFact(row, fact) {
      return task(async (s) => {
        const local = localFor(row, s);
        if (!local.edited_by.trim())
          throw new Error(
            "Escribe quién realiza el retiro en Responsable de la edición.",
          );
        row = await saveRow(row, s);
        const next = await api(
          path(s, requestPath(row, `/facts/${encodeURIComponent(fact.id)}`)),
          {
            method: "DELETE",
            body: JSON.stringify({
              revision: row.revision,
              edited_by: local.edited_by.trim(),
            }),
          },
        );
        accept(next, s, true);
        s.history.delete(row.request_id);
        notify(
          "Aporte retirado. Su historial se conserva; revisa los párrafos que lo citaban.",
        );
      });
    },
    approve(row) {
      return task(async (s) => {
        const local = localFor(row, s);
        if (
          local.dirty ||
          !local.approval.confirmed ||
          !local.approval.approved_by.trim()
        )
          throw new Error(
            "Indica quién aprueba y confirma expresamente la versión revisada.",
          );
        const next = await api(path(s, requestPath(row, "/approve")), {
          method: "POST",
          body: JSON.stringify({
            revision: row.revision,
            assessment_hash: row.assessment.input_hash,
            ...local.approval,
          }),
        });
        accept(next, s, true);
        s.history.delete(row.request_id);
        notify(
          "Esta versión quedó aprobada y conservada en el historial. El oficio se generará en la siguiente fase.",
        );
        await load({ quiet: true, target: s });
      });
    },
    history(row) {
      return task(async (s) => {
        s.history.set(
          row.request_id,
          await api(path(s, requestPath(row, "/history"))),
        );
        s.expanded.add(`${row.request_id}-history`);
      });
    },
    download(row) {
      downloadLocal(state.caseId, row, localFor(row));
    },
    reset(row) {
      if (
        !window.confirm(
          "¿Reemplazar los cambios de esta solicitud por la versión guardada? Puedes descargar tu edición antes de hacerlo.",
        )
      )
        return;
      const local = makeLocal(row);
      state.locals.set(row.request_id, local);
      persist(row, local);
      refresh();
    },
    rebase(row) {
      const local = localFor(row);
      if (
        !window.confirm(
          `¿Conservar tu texto y tus decisiones sobre la revisión ${row.revision}? Compara primero con la versión guardada. Al guardar se creará una nueva revisión.`,
        )
      )
        return;
      local.revision = row.revision;
      actions.changed(row, local, true);
    },
    discardOrphan(id) {
      if (
        !window.confirm(
          "¿Descartar esta copia local de una solicitud retirada? El historial guardado se conserva.",
        )
      )
        return;
      removeLocal(state.caseId, id);
      state.locals.delete(id);
      refresh();
    },
  };
  return {
    get state() {
      return state;
    },
    setCase,
    load,
    hasUnsaved() {
      return (
        [...cases.values()].some((s) =>
          [...s.locals.values()].some(isUnsent),
        ) || hasStoredUnsent()
      );
    },
    hasUnsavedFor(caseId) {
      return (
        [...(cases.get(caseId)?.locals.values() || [])].some(isUnsent) ||
        loadCaseLocals(caseId).size > 0
      );
    },
    view() {
      return reviewView({
        state,
        current: getCase(),
        drafts: getDrafts(),
        mapping: getSources(),
        actions,
      });
    },
  };
}
