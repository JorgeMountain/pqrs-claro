import { el, button, dateLabel } from "./ui.js";
import { verificationEditor, verificationRecord, verificationRevokeForm } from "./verification-forms.js";

const blockedReasons = new Set(["document_missing", "missing_document", "extraction_error", "partial_extraction", "analysis_error", "retrieval_error"]);
const writtenReasons = new Set(["fact_confirmation", "applicability", "fact", "model_fact"]);

/** Comprobaciones humanas y declaraciones documentales mantienen su origen y alcance. */
export function createVerifications({ api, notify, getCase, render, getMapping, onChanged, showSource }) {
  const state = { caseId: null, records: [], applications: [], loading: false, loaded: false,
    busy: false, error: null, editor: null, revoke: null, token: 0 };
  const path = (suffix = "", caseId = state.caseId) => `/api/cases/${encodeURIComponent(caseId)}/verifications${suffix}`;
  function reset() {
    state.token++; state.caseId = getCase()?.id || null;
    Object.assign(state, { records: [], applications: [], loading: false, loaded: false,
      error: null, editor: null, revoke: null });
  }
  async function load({ quiet = false } = {}) {
    const caseId = getCase()?.id;
    if (state.caseId !== caseId) reset();
    if (!caseId) return;
    const token = ++state.token;
    state.loading = true; state.error = null;
    if (!quiet) render();
    try {
      const data = await api(path());
      if (token !== state.token || caseId !== getCase()?.id) return;
      state.records = data.records || []; state.applications = data.applications || [];
      state.loaded = true;
    } catch (error) {
      if (token === state.token) state.error = error.message;
    } finally {
      if (token === state.token) { state.loading = false; render(); }
    }
  }
  async function mutation(task) {
    if (state.busy) return;
    state.busy = true; render();
    try { await task(); }
    catch (error) {
      if (state.editor) state.editor.error = error.message;
      else state.error = error.message;
      notify(error.message, "error");
    } finally { state.busy = false; render(); }
  }
  function checkAction(check, requestIds, supports = []) {
    const openIds = requestIds.filter((id) => {
      const application = check.applications?.find((item) => item.request_id === id);
      return (application?.resolution || check.resolution)?.status !== "resolved";
    });
    if (!openIds.length || check.stage === "fulfillment" || !check.check_key || blockedReasons.has(check.reason_code) ||
        ["document_missing", "analysis_error"].includes(check.evidence_state || check.state) ||
        ["resolved", "confirmed", "applied"].includes(check.status)) return null;
    return button("Registrar o reutilizar comprobación", async () => {
      const caseId = getCase()?.id;
      if (state.caseId !== getCase()?.id) reset();
      if (!state.loaded) await load({ quiet: true });
      if (getCase()?.id !== caseId) return;
      const current = getCase();
      const unique = [...new Map(supports.filter((support) => check.linked_source_ids?.includes(support.source_id))
        .map((support) => [support.chunk_id, support])).values()];
      state.editor = { check, requestIds: [...new Set(openIds)], selectedIds: [...new Set(openIds)],
        supports: unique, recordId: "new", passageId: unique[0]?.chunk_id || "",
        caseId, version: current.version, allowWritten: writtenReasons.has(check.reason_code),
        draft: {}, error: null };
      state.revoke = null; render();
      requestAnimationFrame(() => {
        document.getElementById("verification-editor-heading")?.focus();
        document.getElementById("verification-editor-heading")?.scrollIntoView({ block: "center", behavior: "smooth" });
      });
    }, "quiet", { className: "button button-quiet button-small", disabled: state.busy || getMapping()?.stale || getMapping()?.status !== "ready" });
  }
  async function submit() {
    const editor = state.editor;
    if (!editor.selectedIds.length) { editor.error = "Selecciona al menos una pregunta."; render(); return; }
    await mutation(async () => {
      if (getCase()?.id !== editor.caseId || getCase()?.version !== editor.version) throw new Error("La petición cambió. Vuelve a abrir la comprobación para revisar su alcance.");
      let recordId = editor.recordId;
      if (!recordId || recordId === "new") {
        const support = editor.supports.find((item) => item.chunk_id === editor.passageId);
        const record = await api(path("", editor.caseId), { method: "POST", body: JSON.stringify({
          version: editor.version, fact: editor.draft.fact, basis: editor.draft.basis,
          recorded_by: editor.draft.recordedBy, request_ids: editor.selectedIds,
          source_id: support?.source_id || null,
          passage: support ? Object.fromEntries(["chunk_id", "page", "line_start", "line_end", "quote"].map((key) => [key, support[key]])) : null,
          scope: { person: editor.draft.person || null, period: editor.draft.period || null, subject: editor.draft.subject || null },
        }) });
        recordId = record.id; editor.recordId = record.id;
        if (state.caseId === editor.caseId) state.records.unshift({ ...record, active: true });
      }
      await api(path(`/${encodeURIComponent(recordId)}/applications`, editor.caseId), { method: "POST", body: JSON.stringify({
        version: editor.version, request_ids: editor.selectedIds, check_key: editor.check.check_key,
        basis: editor.draft.applicationBasis, recorded_by: editor.draft.recordedBy,
      }) });
      notify("Comprobación aplicada a las preguntas seleccionadas. Se conserva su atribución y alcance.");
      if (getCase()?.id === editor.caseId) {
        state.editor = null; await load({ quiet: true });
        if (getCase()?.id === editor.caseId) await onChanged?.();
      }
    });
  }
  async function revoke() {
    const caseId = state.caseId;
    const target = state.revoke;
    const version = getCase().version;
    await mutation(async () => {
      await api(`/api/cases/${encodeURIComponent(caseId)}/verification-applications/${encodeURIComponent(target.id)}/revoke`, {
        method: "POST", body: JSON.stringify({ version,
          reason: target.reason, recorded_by: target.recordedBy }),
      });
      notify("Retiro registrado; la aplicación anterior se conserva en el historial.");
      if (getCase()?.id === caseId) {
        state.revoke = null; await load({ quiet: true });
        if (getCase()?.id === caseId) await onChanged?.();
      }
    });
  }
  function view() {
    if (!getCase() || getCase().status !== "confirmed") return null;
    const active = state.applications.filter((item) => item.active);
    return el("section", { className: "sources-verifications", "aria-label": "Comprobaciones registradas" },
      state.editor ? verificationEditor({ editor: state.editor, records: state.records, busy: state.busy,
        changed: render, submit, close: () => { state.editor = null; render(); }, caseId: state.caseId, showSource }) : null,
      el("details", { className: "source-review", open: Boolean(state.revoke) },
        el("summary", {}, `Comprobaciones registradas · ${active.length} aplicaciones vigentes`),
        el("div", { className: "source-review-form", "aria-busy": state.loading },
          el("p", { className: "small muted" }, "Una declaración encontrada en un oficio y una comprobación humana conservan su origen. Selecciona un pendiente para confirmar a qué preguntas se aplica."),
          state.loading ? el("p", { role: "status" }, "Cargando comprobaciones…") : null,
          state.error ? el("p", { className: "warning-box", role: "alert" }, state.error) : null,
          !state.loaded || state.error ? button("Cargar comprobaciones", () => load(), "quiet", { disabled: state.loading }) : null,
          state.loaded && !state.records.length ? el("p", { className: "small muted" }, "Aún no hay comprobaciones registradas para estas fuentes.") : null,
          active.map((item) => el("div", { className: "source-group" },
            el("p", {}, el("strong", {}, `Aplicada a ${(item.active_request_ids || item.request_ids).join(", ")}`)),
            el("p", { className: "small" }, item.basis),
            el("p", { className: "small muted" }, `${item.recorded_by} · ${dateLabel(item.recorded_at, true)}`),
            button("Retirar esta aplicación", () => { state.revoke = { id: item.id, reason: "", recordedBy: "" }; render(); }, "quiet", { disabled: state.busy }))),
          state.revoke ? verificationRevokeForm({ target: state.revoke, busy: state.busy, submit: revoke,
            close: () => { state.revoke = null; render(); } }) : null,
          state.records.slice(0, 30).map((record) => el("details", { className: "source-review" },
            el("summary", {}, `${record.kind === "human_review" ? "Revisión humana" : "Declaración del antecedente"} · ${record.fact}`),
            verificationRecord(record, state.caseId, showSource))),
          state.records.length > 30 ? el("p", { className: "small muted" }, "Vista de las últimas 30 comprobaciones. El selector de cada pendiente incluye todas las aplicables a su fuente.") : null,
        )),
    );
  }
  return { load, reset, view, checkAction };
}
