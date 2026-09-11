const toggle = document.querySelector('#workspace-toggle');
const menu = document.querySelector('#workspace-menu');
const shell = document.querySelector('.shell');
function setExpanded(expanded) {
  menu.hidden = !expanded;
  shell.classList.toggle('workspace-expanded', expanded);
  toggle.setAttribute('aria-expanded', String(expanded));
  const label = expanded ? 'Plegar espacio de trabajo' : 'Abrir espacio de trabajo';
  toggle.setAttribute('aria-label', label);
  toggle.title = label;
}
toggle.addEventListener('click', () => setExpanded(menu.hidden));
document.querySelector('.workspace-rail').addEventListener('keydown', event => {
  if (event.key === 'Escape' && !menu.hidden) { setExpanded(false); toggle.focus(); }
});
menu.addEventListener('click', event => {
  if (innerWidth <= 760 && event.target.closest('button')) setExpanded(false);
}, true);