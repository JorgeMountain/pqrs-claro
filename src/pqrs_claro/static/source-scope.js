// The storage event carries only the case ID; every tab reads its own current projection.
const key = "pqrs-source-scope-reduced";

export function watchSourceScope(onReduced, {getCaseId, read}) {
  let caseId = null, linked = null, pending = null, revision = 0, unverified = false;
  function select(id) {
    if (id === caseId) return;
    caseId = id; linked = null; pending = null; unverified = false; revision++;
  }
  function remember(id, ids) {
    if (getCaseId() !== id || !Array.isArray(ids)) return;
    select(id);
    linked = new Set(ids); pending = null; unverified = false; revision++;
  }
  function check(force = false) {
    const id = getCaseId();
    select(id);
    if (!id || (document.hidden && force !== true) || pending) return pending;
    const before = revision;
    pending = read(id).then(({collection_ids: ids}) => {
      if (revision !== before || getCaseId() !== id || !Array.isArray(ids)) return;
      const previous = linked, refreshUnknown = unverified;
      remember(id, ids);
      if (refreshUnknown || (previous && [...previous].some(collection => !linked.has(collection)))) onReduced(id);
    }).catch(() => {
      if (before === revision && !linked) unverified = true;
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
    beforeRead(id) { select(id); return linked ? null : check(true); },
  };
}

export function announceScopeReduction(caseId) {
  try {
    localStorage.setItem(key, JSON.stringify({ caseId, change: Math.random() }));
  } catch { /* The initiating tab also updates directly when storage is unavailable. */ }
}
