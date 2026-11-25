export async function safeJson(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function apiJson(url, {
  body,
  method = 'POST',
  timeoutMs = 60000,
  signal,
  fallbackError = 'No se pudo completar la operación.',
  timeoutError = 'La operación está tardando más de lo esperado. Vuelve a intentarlo.',
} = {}) {
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const init = body === undefined
    ? {}
    : {
        method,
        body: isForm ? body : JSON.stringify(body),
        headers: isForm ? {} : {'Content-Type': 'application/json'},
      };
  const signals = [];
  if (timeoutMs > 0 && typeof AbortSignal?.timeout === 'function') {
    signals.push(AbortSignal.timeout(timeoutMs));
  }
  if (signal) signals.push(signal);
  if (signals.length) {
    init.signal = signals.length === 1 ? signals[0] : AbortSignal.any(signals);
  }
  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (signal?.aborted) {
      const aborted = new Error('Consulta cancelada.');
      aborted.name = 'AbortError';
      aborted.aborted = true;
      throw aborted;
    }
    if (error?.name === 'TimeoutError' || error?.name === 'AbortError') {
      const timeout = new Error(timeoutError);
      timeout.timeout = true;
      timeout.uncertain = true;
      throw timeout;
    }
    if (error && typeof error === 'object') error.uncertain = true;
    throw error;
  }
  const data = await safeJson(response);
  if (!response.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : '';
    const err = new Error(detail || fallbackError);
    err.status = response.status;
    err.data = data;
    throw err;
  }
  if (data === null) {
    const err = new Error(fallbackError);
    err.status = response.status;
    throw err;
  }
  return data;
}
