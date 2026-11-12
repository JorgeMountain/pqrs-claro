// The browser sends signs of activity, never a duration. The server owns the clock.
export function workId() {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

export function createWorkClock({post, status, newId = workId}) {
  let target = null, session = null, reported = '';
  const stopping = new Set();

  function show(value) {
    if (value !== reported) {
      reported = value;
      status(value);
    }
  }

  function send(row, event) {
    const message = {
      actor_id: row.actorId, session_id: row.id, sequence: event === 'start' ? 0 : ++row.sequence,
      event, activity: row.activity,
    };
    row.activity = false;
    return post(row.caseId, message);
  }

  async function update(event) {
    const row = session;
    if (!row || row.busy) return;
    row.busy = true;
    try {
      const result = await send(row, event);
      if (session !== row) return;
      row.started = true;
      if (result.status === 'ended') {
        session = null;
        show('ended');
      } else {
        show(result.status);
      }
    } catch (error) {
      if (session !== row) return;
      if ([403, 404, 409, 422].includes(error.status)) {
        session = null;
        show('unavailable');
      } else {
        show('offline');
      }
    } finally {
      row.busy = false;
      if (session === row && row.confirmRequested) {
        row.confirmRequested = false;
        if (reported === 'unconfirmed') void update('confirm');
      }
    }
  }

  function start() {
    session = {...target, id: newId(), sequence: 0, activity: false, started: false, busy: false};
    show('connecting');
    return update('start');
  }

  function setTarget(next) {
    if (next?.caseId === target?.caseId && next?.actorId === target?.actorId) return;
    const old = session;
    session = null;
    target = next;
    // Dispatch immediately even if a heartbeat or start is still in flight.
    // stop has a higher sequence and the server retires this ID permanently.
    if (old) {
      const stopped = send(old, 'stop').catch(() => {});
      stopping.add(stopped);
      void stopped.finally(() => stopping.delete(stopped));
    }
    if (target) return start();
    show('away');
  }

  function interact() {
    if (session) session.activity = true;
    else if (target && reported === 'ended') return start();
  }

  function tick() {
    if (session) return update(session.started ? 'heartbeat' : 'start');
  }

  function confirm() {
    if (session && reported === 'unconfirmed') {
      if (session.busy) {
        session.confirmRequested = true;
        return;
      }
      return update('confirm');
    }
  }

  return {setTarget, interact, tick, confirm, flush: () => Promise.all([...stopping])};
}
