const toggle = document.querySelector('#workspace-toggle');
const menu = document.querySelector('#workspace-menu');
const shell = document.querySelector('.shell');
function setExpanded(expanded) {
  menu.hidden = !expanded;
  shell.classList.toggle('workspace-expanded', expanded);
  toggle.setAttribute('aria-expanded', String(expanded));
  const label = expanded ? 'Plegar menú' : 'Abrir menú';
  toggle.setAttribute('aria-label', label);
  toggle.title = label;
}
export function setWorkspaceSection(id) {
  menu.querySelectorAll('button').forEach(button => {
    if (button.id === id) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
}
const desktop = matchMedia('(min-width: 1024px)');
setExpanded(desktop.matches);
desktop.addEventListener('change', event => setExpanded(event.matches));
toggle.addEventListener('click', () => setExpanded(menu.hidden));
document.querySelector('.workspace-rail').addEventListener('keydown', event => {
  if (event.key === 'Escape' && !menu.hidden) { setExpanded(false); toggle.focus(); }
});
menu.addEventListener('click', event => {
  if (innerWidth <= 760 && event.target.closest('button')) setExpanded(false);
}, true);
