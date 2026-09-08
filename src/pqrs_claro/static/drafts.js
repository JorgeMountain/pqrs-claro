import { draftsView } from "./draft-view.js";

export function createDrafts({
  api,
  notify,
  getCase,
  getSources,
  render,
  showSource,
  back,
  review,
}) {
  const state = {
    caseId: null,
    run: null,
    loaded: false,
    loading: false,
    busy: false,
    error: null,
    selected: null,
    poll: null,
    token: 0,
    expanded: new Set(),
  };
  function setCase(current) {
    if (state.caseId === (current?.id || null)) return;
    clearTimeout(state.poll);
    state.token++;
    Object.assign(state, {
      caseId: current?.id || null,
      run: null,
      loaded: false,
      loading: false,
      busy: false,
      error: null,
      selected: current?.identification?.requests?.[0]?.id || null,
      expanded: new Set(),
    });
  }
  function schedule() {
    clearTimeout(state.poll);
    if (state.run?.status === "running")
      state.poll = setTimeout(() => load({ quiet: true }), 1800);
  }
  async function load({ quiet = false } = {}) {
    const current = getCase();
    if (current?.status !== "confirmed") return;
    const token = ++state.token;
    state.loading = true;
    state.error = null;
    if (!quiet) render();
    try {
      const run = await api(
        `/api/cases/${encodeURIComponent(current.id)}/drafts`,
      );
      if (token !== state.token || current.id !== getCase()?.id) return;
      state.run = run;
      state.loaded = true;
    } catch (error) {
      if (token !== state.token || current.id !== getCase()?.id) return;
      state.error = error.message;
    } finally {
      if (token === state.token && current.id === getCase()?.id) {
        state.loading = false;
        render();
        schedule();
      }
    }
  }
  async function generate() {
    if (state.busy) return;
    const current = getCase();
    state.busy = true;
    state.error = null;
    render();
    try {
      const run = await api(
        `/api/cases/${encodeURIComponent(current.id)}/drafts/generate`,
        {
          method: "POST",
          body: JSON.stringify({ version: current.version }),
        },
      );
      if (getCase()?.id !== current.id) return;
      state.run = run;
      state.loaded = true;
      notify(
        "Preparación iniciada. Puedes seguir el avance de cada solicitud.",
      );
    } catch (error) {
      if (getCase()?.id === current.id) state.error = error.message;
    } finally {
      if (getCase()?.id === current.id) {
        state.busy = false;
        render();
        schedule();
      }
    }
  }
  function view() {
    return draftsView({
      state,
      current: getCase(),
      mapping: getSources(),
      generate,
      load,
      back,
      review,
      showSource,
      select(id) {
        state.selected = id;
        render();
        document
          .getElementById(`response-select-${id}`)
          ?.focus({ preventScroll: true });
      },
    });
  }
  return { state, setCase, load, view };
}
