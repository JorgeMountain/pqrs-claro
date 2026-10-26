import {icon} from './inbox-icons.js?v=sidebar1';
import {inboxSections,sectionCounts} from './inbox-navigation.js?v=sidebar1';

const toggle = document.querySelector('#workspace-toggle');
const menu = document.querySelector('#workspace-menu');
const shell = document.querySelector('.shell');
document.querySelectorAll('[data-workspace-icon]').forEach(node=>node.innerHTML=icon(node.dataset.workspaceIcon));
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
export function syncWorkspaceQueue({active=[],trash=[],manager='',loaded=false}){
  const counts=sectionCounts(active,trash,manager);
  menu.querySelectorAll('[data-workspace-count]').forEach(node=>{
    const key=node.dataset.workspaceCount,value=counts[key];
    node.textContent=loaded?(value??'—'):'…';
    node.title=!loaded?'Cargando expedientes':value===null?'Selecciona tu gestor':`${value} ${value===1?'expediente':'expedientes'}`;
    node.closest('button').setAttribute('aria-label',`${inboxSections[key].title}: ${node.title}`);
  });
}
export function selectWorkspaceInbox(section){
  setWorkspaceSection((inboxSections[section]||inboxSections.mine).id);
}
export const workspaceHelp = `<div class="workspace-help">
  <p>Selecciona tu gestor en la cabecera. Los contadores indican expedientes; Pendientes y Borradores son vistas de tu trabajo y pueden coincidir.</p>
  <dl>
    <dt>Nuevo expediente</dt><dd>Recibe un PDF o un correo y abre el preanálisis. La identificación comienza cuando tú la confirmas.</dd>
    <dt>Mi trabajo</dt><dd>Expedientes abiertos a tu cargo, con su avance conservado.</dd>
    <dt>Pool del equipo</dt><dd>Consulta los expedientes abiertos del equipo y toma los que estén disponibles.</dd>
    <dt>Pendientes por resolver</dt><dd>Encuentra expedientes que necesitan revisión o una acción del gestor. Los procesos en curso aparecen en Mi trabajo.</dd>
    <dt>Borradores</dt><dd>Retoma los oficios guardados. Generar un oficio no finaliza por sí solo el expediente.</dd>
    <dt>Finalizadas</dt><dd>Consulta lo que cerraste con «Finalizar expediente», conservando sus documentos y respuestas.</dd>
    <dt>Papelera</dt><dd>Consulta o restaura expedientes eliminados.</dd>
  </dl><p class="muted">Dentro del expediente puedes volver a las etapas disponibles para consultar el avance guardado.</p>
</div>`;
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
