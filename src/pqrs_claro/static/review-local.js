import { el } from "./ui.js";

const prefix = "pqrs-claro-review-v1:";
const blankFact = () => ({ text: "", author: "", basis: "", observed_at: "" });
export function makeLocal(row, previous = null) {
  return {
    request_id: row.request_id,
    label: row.label,
    title: row.title,
    revision: row.revision,
    paragraphs: structuredClone(row.paragraphs || []),
    resolutions: {},
    edited_by: previous?.edited_by || "",
    fact: previous?.fact || blankFact(),
    approval:
      previous?.revision === row.revision
        ? previous.approval || { approved_by: "", note: "", confirmed: false }
        : { approved_by: "", note: "", confirmed: false },
    dirty: false,
  };
}
export function loadCaseLocals(caseId) {
  const saved = new Map();
  try {
    const keyPrefix = prefix + caseId + ":";
    for (const key of Object.keys(sessionStorage)) {
      if (!key.startsWith(keyPrefix)) continue;
      const local = JSON.parse(sessionStorage.getItem(key));
      if (local && Array.isArray(local.paragraphs) && isUnsent(local))
        saved.set(key.slice(keyPrefix.length), local);
    }
  } catch {
    /* Keep any entries already recovered. */
  }
  return saved;
}
export function removeLocal(caseId, requestId) {
  try {
    sessionStorage.removeItem(prefix + caseId + ":" + requestId);
  } catch {
    /* The in-memory copy can still be removed. */
  }
}
export function loadLocal(caseId, row) {
  try {
    const saved = JSON.parse(
      sessionStorage.getItem(prefix + caseId + ":" + row.request_id),
    );
    if (saved && Array.isArray(saved.paragraphs)) {
      if (saved.dirty) return saved;
      return makeLocal(row, saved);
    }
  } catch {
    /* An unavailable browser store must not prevent editing. */
  }
  return makeLocal(row);
}
export function persistLocal(caseId, requestId, local) {
  try {
    sessionStorage.setItem(
      prefix + caseId + ":" + requestId,
      JSON.stringify(local),
    );
    return true;
  } catch {
    return false;
  }
}
export function isUnsent(local) {
  return Boolean(
    local.dirty ||
    Object.values(local.fact || {}).some(Boolean) ||
    local.approval?.approved_by ||
    local.approval?.note ||
    local.approval?.confirmed,
  );
}
export function hasStoredUnsent() {
  try {
    return Object.keys(sessionStorage).some(
      (key) =>
        key.startsWith(prefix) &&
        isUnsent(JSON.parse(sessionStorage.getItem(key))),
    );
  } catch {
    return false;
  }
}
export function downloadLocal(caseId, row, local) {
  const url = URL.createObjectURL(
    new Blob(
      [
        JSON.stringify(
          { case_id: caseId, request_id: row.request_id, ...local },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    ),
  );
  el("a", {
    href: url,
    download: `revision-local-${row.label || row.request_id}.json`,
  }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function resetFact(local) {
  local.fact = blankFact();
}
