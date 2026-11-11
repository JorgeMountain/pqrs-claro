import assert from "node:assert/strict";
import {setImmediate as tick} from "node:timers/promises";
import fs from "node:fs/promises";
import {createSources} from "../src/pqrs_claro/static/sources.js";
import {createResponseEditor} from "../src/pqrs_claro/static/recorrido/live-edit.js";
import * as localReview from "../src/pqrs_claro/static/review-local.js";

const events = {};
globalThis.window = {
  addEventListener(name, action) { events[name] = action; },
  setInterval(action, ms) { assert.equal(ms, 5000); events.poll = action; },
};
globalThis.document = {hidden: true, querySelectorAll: () => []};
const current = {id: "C01", status: "confirmed"};
const original = {status: "ready", results: [{supports: [{quote: "Cita retirada"}]}]};
const allowed = {status: "stale", results: []};
let selected = ["archivo"], mapping = original, delay, failFirst = false, changes = 0;
const calls = [];
const api = async path => {
  calls.push(path);
  if (path === "/api/cases/C01/source-collections") {
    if (failFirst) { failFirst = false; throw Error("Sin conexión"); }
    return {collection_ids: [...selected]};
  }
  if (path === "/api/cases/C01/sources") {
    if (!delay) return mapping;
    const pending = delay; delay = null; return pending;
  }
  if (path.startsWith("/api/source-collections?")) return {collections: [], linked_collection_ids: [...selected]};
  return {};
};
function controller() {
  const sources = createSources({
    api, render() {}, getCase: () => current, onScopeReduced: () => { changes++; },
  });
  sources.setCase(current);
  return sources;
}
const first = controller();
await first.load({quiet: true});
assert.equal(first.state.mapping, original);
assert.equal(calls[0], "/api/cases/C01/source-collections", "capture scope before reading even in a hidden tab");
let release;
delay = new Promise(resolve => { release = resolve; });
const previousRead = first.load({quiet: true});
await tick();
selected = []; mapping = allowed;
document.hidden = false;
await events.focus(); await tick();
assert.equal(changes, 1);
assert.equal(first.state.mapping, allowed, "external unlink reaches an already open case on focus");
release(original); await previousRead;
assert.equal(first.state.mapping, allowed, "an older response cannot restore revoked content");

failFirst = true; changes = 0; selected = ["archivo"]; mapping = original;
const second = controller();
await second.load({quiet: true});
assert.equal(second.state.mapping, original);
selected = []; mapping = allowed;
await events.poll(); await tick();
assert.equal(changes, 1);
assert.equal(second.state.mapping, allowed, "recovering the first permissions read also refreshes the projection");
const count = calls.length;
await events.poll();
assert.equal(calls.length, count + 1);
assert.equal(calls.at(-1), "/api/cases/C01/source-collections");
assert.ok(calls.every(path => !path.endsWith("/search")));

const row = {case_id: "C01", request_id: "P1", revision: 5, stale: true,
  can_replace_withdrawn_paragraphs: true, paragraphs: []};
let received;
const newText = "Texto de la revisora con el alcance actualizado.";
const formFields = new Map();
const form = {
  querySelector(selector) {
    if (selector.includes('[name="author"]')) return null;
    if (!formFields.has(selector)) formFields.set(selector, {focus(){}, value: "", hidden: true});
    return formFields.get(selector);
  },
  querySelectorAll: () => [], isConnected: true,
};
const drawer = {querySelector: () => form};
document.querySelector = selector => selector === "#drawer-body" ? drawer : {open: true};
globalThis.fetch = async (_url, opts) => {
  if (opts?.method) received = JSON.parse(opts.body);
  return {ok: true, json: async () => opts?.method ? {...row, revision: 6} : {requests: [row]}};
};
const editor = createResponseEditor({open(){}, close(){}, notice(){}, getCase: () => current, onSaved(){}});
await editor.edit("P1");
form.querySelector("#response-add").onclick();
form.oninput({target: {matches: () => true, dataset: {paragraph: "0"}, value: newText}});
form.querySelector("#response-actor").value = "QA";
await form.onsubmit({preventDefault(){}});
assert.equal(received.replace_withdrawn_paragraphs, true);
assert.equal(received.paragraphs[0].text, newText);

// Render adapter retains the same save action wired to the button in the shared review view.
const reviewJS = (await fs.readFile(new URL("../src/pqrs_claro/static/review.js", import.meta.url), "utf8"))
  .replace(/import \{ reviewView \} from ".\/review-view.js";/, "const reviewView = ({actions}) => actions;")
  .replace(/import \{([\s\S]*?)\} from ".\/review-local.js";/, "const {$1} = globalThis.localReview;");
globalThis.localReview = localReview;
const {createReview} = await import("data:text/javascript;base64," + Buffer.from(reviewJS).toString("base64"));
const review = createReview({api: async (_url, opts) => {
  if (!opts) return {requests: [row]};
  received = JSON.parse(opts.body);
  return {...row, revision: 6, paragraphs: received.paragraphs};
}, getCase: () => current, render(){}, notify(){}, getDrafts: () => ({}), getSources: () => ({})});
review.setCase(current);
await review.load({quiet: true});
const actions = review.view();
Object.assign(actions.localFor(row), {dirty: true, edited_by: "QA",
  paragraphs: [{text: newText, cited_chunk_ids: [], cited_fact_ids: []}]});
received = null;
await actions.save(row);
assert.equal(received.replace_withdrawn_paragraphs, true);
assert.equal(received.paragraphs[0].text, newText);
