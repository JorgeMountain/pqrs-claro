// The storage event carries only the case ID; every tab reads its own current projection.
const key = "pqrs-source-scope-reduced";

export function watchSourceScope(onReduced, {getCaseId, read, watchRedaction = () => false, onRedactionChange}) {
  let caseId = null, linked = null, pending = null, revision = 0, unverified = false;
  let redaction = null, retryRedaction = false;
  function select(id) {
    if (id === caseId) return;
    caseId = id; linked = null; pending = null; unverified = false; redaction = null; retryRedaction = false; revision++;
  }
  function remember(id, ids) {
    if (getCaseId() !== id || !Array.isArray(ids)) return;
    select(id);
    const next = new Set(ids);
    if (linked && (next.size !== linked.size || [...linked].some(id => !next.has(id)))) redaction = null;
    linked = next; pending = null; unverified = false; revision++;
  }
  function check(force = false) {
    const id = getCaseId();
    select(id);
    if (!id || (document.hidden && force !== true) || pending) return pending;
    const before = revision;
    const watching = watchRedaction();
    pending = read(id, watching).then(({collection_ids: ids, correction_revision, result_revision}) => {
      if (revision !== before || getCaseId() !== id || !Array.isArray(ids)) return;
      const previous = linked, refreshUnknown = unverified;
      remember(id, ids);
      const reduced = previous && [...previous].some(collection => !linked.has(collection));
      let corrected = false, recalculated = false;
      if (watching && typeof correction_revision === 'string' && typeof result_revision === 'string') {
        corrected = redaction !== null && redaction.corrections !== correction_revision;
        recalculated = retryRedaction || (redaction !== null && redaction.results !== result_revision);
        redaction = {corrections: correction_revision, results: result_revision};
        retryRedaction = false;
      }
      if (refreshUnknown || reduced) onReduced(id);
      else if (corrected || recalculated) onRedactionChange?.(id, corrected);
    }).catch(() => {
      if (before === revision && !linked) unverified = true;
      if (before === revision && watching && !redaction) retryRedaction = true;
    }).finally(() => { if (before === revision) pending = null; });
    return pending;
  }
  window.addEventListener("storage", (event) => {
    if (event.key !== key || !event.newValue) return;
    let entry;
    try { entry = JSON.parse(event.newValue); } catch { return; }
    if (typeof entry?.caseId === "string") onReduced(entry.caseId);
  });
  window.addEventListener("focus", check);
  document.addEventListener?.("visibilitychange", check);
  window.setInterval?.(check, 5000);
  return {
    remember,
    beforeRead(id) { select(id); return linked && (!watchRedaction() || redaction) ? null : check(true); },
  };
}

export function announceScopeReduction(caseId) {
  try {
    localStorage.setItem(key, JSON.stringify({ caseId, change: Math.random() }));
  } catch { /* The initiating tab also updates directly when storage is unavailable. */ }
}
