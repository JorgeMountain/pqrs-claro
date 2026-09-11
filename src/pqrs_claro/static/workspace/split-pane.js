const STORAGE_KEY = 'pqrs-demo-request-width';
let preferred = 60;
try {
  const saved = Number(localStorage.getItem(STORAGE_KEY));
  if (Number.isFinite(saved) && saved >= 30 && saved <= 70) preferred = saved;
} catch { /* The divider also works when storage is unavailable. */ }

export function bindSplitPane() {
  const layout = document.querySelector('.understanding-layout');
  const handle = document.querySelector('#request-divider');
  if (!layout || !handle) return () => {};
  let current = preferred;
  const limits = () => {
    const usable = layout.clientWidth - handle.offsetWidth;
    const minimum = usable >= 560 ? Math.max(30, 280 / usable * 100) : 30;
    return [minimum, 100 - minimum];
  };
  const apply = (value, save = false) => {
    const [min, max] = limits();
    current = Math.min(max, Math.max(min, value));
    layout.style.setProperty('--requests-track', `${current}fr`);
    layout.style.setProperty('--document-track', `${100 - current}fr`);
    handle.setAttribute('aria-valuemin', String(Math.round(min)));
    handle.setAttribute('aria-valuemax', String(Math.round(max)));
    handle.setAttribute('aria-valuenow', String(Math.round(current)));
    handle.setAttribute('aria-valuetext', `Solicitudes ${Math.round(current)} %, documento ${Math.round(100-current)} %`);
    if (save) {
      preferred = current;
      try { localStorage.setItem(STORAGE_KEY, String(preferred)); } catch {}
    }
  };
  const fromPointer = event => {
    const bounds = layout.getBoundingClientRect();
    apply((event.clientX - bounds.left - handle.offsetWidth / 2) /
      (bounds.width - handle.offsetWidth) * 100, true);
  };
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || !event.isPrimary) return;
    event.preventDefault();
    handle.focus({preventScroll:true});
    handle.setPointerCapture(event.pointerId);
    layout.classList.add('resizing');
  });
  handle.addEventListener('pointermove', event => {
    if (handle.hasPointerCapture(event.pointerId)) fromPointer(event);
  });
  const finish = event => {
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    layout.classList.remove('resizing');
  };
  handle.addEventListener('pointerup', finish);
  handle.addEventListener('pointercancel', finish);
  handle.addEventListener('lostpointercapture', () => layout.classList.remove('resizing'));
  handle.addEventListener('dblclick', () => apply(60, true));
  handle.addEventListener('keydown', event => {
    const [min, max] = limits();
    const values = {ArrowLeft:current-2, ArrowRight:current+2, Home:min, End:max, Enter:60};
    if (event.key in values) { event.preventDefault(); apply(values[event.key], true); }
  });
  const observer = new ResizeObserver(() => apply(preferred));
  observer.observe(layout);
  apply(preferred);
  return () => observer.disconnect();
}
