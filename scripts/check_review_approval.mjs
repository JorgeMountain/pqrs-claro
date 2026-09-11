import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { createHash } from "node:crypto";
import vm from "node:vm";

// Read-only rendering of the real product modules against a minimal DOM.
// Event handlers are collected, never dispatched; no approval/API action runs.
const repo = resolve(process.argv[2] || ".");
const outputDir = resolve(repo, "output/qa/review-approval");
mkdirSync(outputDir, { recursive: true });
class TestNode {
  constructor(tag, text = "") {
    this.tagName = tag;
    this.text = text;
    this.attributes = {};
    this.childNodes = [];
    this.listeners = new Map();
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  append(...children) { this.childNodes.push(...children); }
}
const context = vm.createContext({
  Node: TestNode,
  document: {
    createElement: (tag) => new TestNode(tag),
    createTextNode: (text) => new TestNode("#text", text),
    getElementById: () => null,
  },
  structuredClone,
});
const modules = new Map();
const sources = [];
function moduleFor(path) {
  path = resolve(path);
  if (!modules.has(path)) {
    const source = readFileSync(path, "utf8");
    sources.push({ path, sha256: createHash("sha256").update(source).digest("hex") });
    modules.set(path, new vm.SourceTextModule(source, { identifier: path, context }));
  }
  return modules.get(path);
}
const entry = moduleFor(resolve(repo, "src/pqrs_claro/static/review-decisions.js"));
await entry.link((specifier, referring) => moduleFor(resolve(dirname(referring.identifier), specifier)));
await entry.evaluate();
const { approvalView } = entry.namespace;
function descendants(node) {
  return [node, ...node.childNodes.flatMap(descendants)];
}
function fresh() {
  return {
    row: { request_id: "QA-P1", revision: 1, status: "ready", assessment: { status: "passed" }, stale: false, pending: [] },
    local: { dirty: false, resolutions: {}, approval: { approved_by: "", note: "", confirmed: false } },
  };
}
const action = { id: "later", stage: "fulfillment", blocks_approval: false, resolution: { action: "open" } };
const evidence = { id: "evidence", stage: "evidence", blocks_approval: true, resolution: { action: "open" } };
const cases = [
  ["ready_no_pending", true, () => {}],
  ["ready_open_fulfillment", true, ({ row }) => { row.pending = [action]; }],
  ["ready_open_evidence", false, ({ row }) => { row.pending = [evidence]; }],
  ["ready_evidence_and_fulfillment", false, ({ row }) => { row.pending = [action, evidence]; }],
  ["ready_closed_evidence_and_open_fulfillment", true, ({ row }) => { row.pending = [action, { ...evidence, resolution: { action: "resolved" } }]; }],
  ["ready_legacy_open_pending", false, ({ row }) => { row.pending = [{ id: "legacy" }]; }],
  ["fulfillment_without_explicit_nonblocking_flag", false, ({ row }) => { row.pending = [{ id: "later", stage: "fulfillment" }]; }],
  ["fulfillment_explicitly_blocking", false, ({ row }) => { row.pending = [{ ...action, blocks_approval: true }]; }],
  ["evidence_nonblocking_flag_does_not_make_fulfillment", false, ({ row }) => { row.pending = [{ ...evidence, blocks_approval: false }]; }],
  ["stale_with_open_fulfillment", false, ({ row }) => { row.pending = [action]; row.stale = true; }],
  ["dirty_with_open_fulfillment", false, ({ row, local }) => { row.pending = [action]; local.dirty = true; }],
  ["failed_assessment_with_open_fulfillment", false, ({ row }) => { row.pending = [action]; row.assessment.status = "failed"; }],
  ["needs_changes_assessment", false, ({ row }) => { row.assessment.status = "needs_changes"; }],
  ["missing_assessment", false, ({ row }) => { row.assessment = null; }],
  ["checking_status", false, ({ row }) => { row.status = "checking"; }],
  ["local_open_resolution_overrides_saved_resolved", false, ({ row, local }) => {
    row.pending = [{ ...evidence, resolution: { action: "resolved" } }];
    local.resolutions.evidence = { action: "open" };
  }],
];
let calledActions = 0;
const results = [];
for (const [name, expectedForm, setup] of cases) {
  const data = fresh();
  setup(data);
  const tree = approvalView(data.row, data.local, {}, {
    approve: () => { calledActions++; },
    formChanged: () => { calledActions++; },
  }, false);
  const nodes = descendants(tree);
  const forms = nodes.filter((node) => node.tagName === "form");
  assert.equal(forms.length, expectedForm ? 1 : 0, name);
  if (expectedForm) {
    assert(nodes.some((node) => node.tagName === "input" && node.attributes.id === "review-approver" && node.attributes.required === "true"), `${name}: approver field required`);
    assert(nodes.some((node) => node.tagName === "input" && node.attributes.type === "checkbox" && node.attributes.required === "true" && !node.checked), `${name}: explicit unchecked approval required`);
    assert(nodes.some((node) => node.tagName === "button" && node.attributes.type === "submit" && !node.disabled), `${name}: submit is available`);
  }
  results.push({ name, expected_form: expectedForm, actual_form_count: forms.length, passed: true });
}
assert.equal(calledActions, 0, "No event handler or approval action may run during this QA");
const report = {
  tested_at: new Date().toISOString(),
  kind: "real_product_modules_with_minimal_dom_no_events",
  sources,
  cases: results,
  passed: results.length,
  failed: 0,
  approval_actions_executed: calledActions,
  institutional_approval: false,
};
writeFileSync(resolve(outputDir, "approval-view-regression.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify({ passed: results.length, failed: 0, approval_actions_executed: calledActions, source_modules: sources.length }));
