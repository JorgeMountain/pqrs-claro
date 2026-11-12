import {esc} from './views.js';
import {states,request} from './management-ui.js?v=phase2';

function formatDuration(seconds, missing='Sin medición'){
  if(!Number.isFinite(seconds))return missing;
  const value=Math.floor(seconds), days=Math.floor(value/86400), hours=Math.floor(value/3600)%24;
  const minutes=Math.floor(value/60)%60;
  if(days)return `${days} d ${hours} h`;
  if(hours)return `${hours} h ${minutes} min`;
  if(minutes)return `${minutes} min ${value%60} s`;
  return `${value} s`;
}
const dateFormat=new Intl.DateTimeFormat('es-CO',{timeZone:'America/Bogota',dateStyle:'short',timeStyle:'short'});
function instant(value,empty='Sin registro'){
  return value?dateFormat.format(new Date(value)):empty;
}
function cell(label,value){return `<td data-label="${label}">${value}</td>`;}
function caseRow(item){
  const contributors=(item.contributors||[]).map(person=>`<li>${esc(person.manager_name)} · En pantalla ${formatDuration(person.active_seconds)} · Sin confirmar ${formatDuration(person.unconfirmed_seconds)} · Externo ${formatDuration(person.external_seconds)}</li>`).join('');
  const declarations=(item.external_entries||[]).map(entry=>`<li>${esc(entry.manager_name)} · ${esc(entry.minutes)} min · ${instant(entry.declared_at)}<br>${esc(entry.reason)}</li>`).join('');
  const coverage={unmeasured:'Sin sesiones registradas',partial:'Parcial desde la instalación',observed:'Con sesiones registradas'};
  const details=[
    ['Alta en el sistema',instant(item.created_at)],
    ['Primera asignación',instant(item.first_assignment_at)],
    ['Cierre',instant(item.closed_at,item.state==='closed'?'Sin registro':'Abierto')],
    ['Peticiones identificadas',item.request_count],['Reasignaciones',item.transfers??'Sin historial'],
    ['En estado pendiente',formatDuration(item.pending_seconds,'Sin historial')],
    ['Tiempo sin confirmar',formatDuration(item.unconfirmed_seconds)],['Trabajo externo declarado',formatDuration(item.external_seconds)],
    ['Medición en pantalla',coverage[item.measurement]||'Sin sesiones registradas']
  ];
  return `<tr><th scope="row"><details><summary>${esc(item.reference||item.internal_number)}<small>${esc(item.subject)}</small></summary>
    <dl>${details.map(([label,v])=>`<dt>${label}</dt><dd>${esc(v)}</dd>`).join('')}</dl>${contributors?`<strong>Participación por gestor</strong><ul>${contributors}</ul>`:''}
    ${declarations?`<strong>Actividades externas declaradas</strong><ul>${declarations}</ul>`:''}</details></th>
    ${cell('Gestor actual',esc(item.owner_name||'Sin asignar'))}${cell('Estado',esc(states[item.state]||item.state))}
    ${cell('Tiempo total',formatDuration(item.total_seconds,'Sin historial'))}${cell('En el pool',formatDuration(item.pool_seconds,'Sin historial'))}
    ${cell('Activo estimado',formatDuration(item.active_seconds)+(item.measurement==='partial'?'<small>Medición parcial</small>':''))}</tr>`;
}
function managerRow(item){
  return `<tr><th scope="row">${esc(item.manager_name)}</th>${cell('Expedientes',esc(item.case_count))}${cell('Con medición',esc(item.measured_case_count))}
    ${cell('Finalizados',esc(item.closed_count))}${cell('Mediana al cierre',formatDuration(item.median_resolution_seconds,'Sin cierres medibles'))}
    ${cell('Activo estimado',formatDuration(item.active_seconds))}${cell('Sin confirmar',formatDuration(item.unconfirmed_seconds))}
    ${cell('Externo declarado',formatDuration(item.external_seconds))}</tr>`;
}
const caseHeaders=['Expediente','Gestor actual','Estado','Tiempo total','En el pool','Activo estimado'];
const managerHeaders=['Gestor','Expedientes','Con medición','Finalizados','Mediana al cierre','Activo estimado','Sin confirmar','Externo declarado'];
export function renderManagementTimes(container,{beforeRead}={}){
  container.innerHTML=`<section class="management-times" aria-labelledby="times-title">
    <h1 id="times-title" tabindex="-1">Tiempos de gestión</h1>
    <p class="muted">Sigue cada PQRS desde su alta en el sistema hasta su cierre y consulta cuánto trabajo quedó registrado por gestor.</p>
    <form class="times-filters"><label>Alta desde<input type="date" name="date_from"></label><label>Alta hasta<input type="date" name="date_to"></label>
      <div><label for="times-manager-filter">Gestor</label><select id="times-manager-filter" name="manager_id"><option value="">Todos los gestores</option></select></div>
      <div><label for="times-state-filter">Estado</label><select id="times-state-filter" name="state"><option value="">Todos los estados</option>${Object.entries(states).map(([k,v])=>`<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select></div>
      <button type="submit">Actualizar</button></form>
    <div class="times-toolbar"><div class="times-switch" role="group" aria-label="Agrupar tiempos">
      <button type="button" data-group="cases" aria-pressed="true">Por expediente</button><button type="button" data-group="managers" aria-pressed="false">Por gestor</button></div>
      <a class="times-download" download hidden>Descargar CSV</a></div>
    <p class="times-status" role="status"></p><div class="times-results"></div>
    <details class="times-guide"><summary>Cómo se calculan los tiempos</summary>
      <p>El total corre desde el alta hasta el cierre, o hasta la hora de consulta si el expediente sigue abierto. El pool cuenta la espera sin asignación. Los filtros de fecha usan el día del alta en Bogotá.</p>
      <p>El activo estimado recoge sesiones del gestor responsable en el expediente. Una lectura prolongada puede requerir confirmación. El trabajo externo declarado y el tiempo sin confirmar se muestran por separado. Los expedientes anteriores a la medición pueden tener una cobertura parcial.</p>
      <p>El filtro de gestor incluye expedientes en los que participó. El tiempo total de cada PQRS abarca a todos sus gestores. La mediana al cierre usa los expedientes finalizados que se atribuyen a ese gestor.</p></details></section>`;
  const root=container.querySelector('.management-times'), form=root.querySelector('form');
  const result=root.querySelector('.times-results'), status=root.querySelector('[role=status]'), download=root.querySelector('.times-download');
  const picker=form.elements.manager_id, dateFrom=form.elements.date_from, dateTo=form.elements.date_to;
  const options=document.querySelector('#cases-actor')?.options||[];
  for(const option of options)if(option.value)picker.add(new Option(option.text,option.value));
  let group='cases', data=null, query, version=0, page=0;
  const size=20;
  function display(){
    if(!data)return;
    const items=data[group], byCase=group==='cases', headers=byCase?caseHeaders:managerHeaders;
    const totalPages=Math.max(1,Math.ceil(items.length/size));
    page=Math.min(page,totalPages-1);
    const unit=byCase?(items.length===1?'expediente':'expedientes'):(items.length===1?'gestor':'gestores');
    status.textContent=`${items.length} ${unit} · Corte ${instant(data.as_of)} (Bogotá)`;
    const params=new URLSearchParams(query);params.set('view',group);
    download.href='/api/management-times.csv?'+params; download.hidden=!items.length;
    if(!items.length){result.innerHTML='<p class="times-empty">Sin resultados para estos filtros.</p>';return;}
    result.innerHTML=`<div class="times-table-wrap"><table aria-label="${byCase?'Tiempos por expediente':'Tiempos por gestor'}">
      <thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead>
      <tbody>${items.slice(page*size,(page+1)*size).map(byCase?caseRow:managerRow).join('')}</tbody></table></div>
      ${totalPages>1?`<div class="times-pages"><button data-page="-1" ${page===0?'disabled':''}>Anterior</button><span>Página ${page+1} de ${totalPages}</span><button data-page="1" ${page+1===totalPages?'disabled':''}>Siguiente</button></div>`:''}`;
  }
  async function refresh(){
    const current=++version;
    data=null;download.hidden=true;result.replaceChildren();page=0;
    dateFrom.max=dateTo.value;dateTo.min=dateFrom.value;
    if(!form.reportValidity()){status.textContent='Revisa el rango de fechas.';return;}
    query=new URLSearchParams();
    for(const [key,value] of new FormData(form))if(value)query.set(key,value);
    status.textContent='Consultando tiempos…';
    try{
      await beforeRead?.();
      if(current!==version||!root.isConnected)return;
      const payload=await request('/api/management-times?'+query);
      if(current!==version||!root.isConnected)return;
      data=payload;display();
    }catch(error){
      if(current===version&&root.isConnected)status.textContent=`No se pudieron consultar los tiempos. ${error.message} Pulsa Actualizar para reintentar.`;
    }
  }
  form.onsubmit=event=>{event.preventDefault();refresh();};
  form.onchange=refresh;
  root.addEventListener('click',event=>{
    const groupButton=event.target.closest('[data-group]'), pageButton=event.target.closest('[data-page]');
    if(groupButton){
      group=groupButton.dataset.group;page=0;
      root.querySelectorAll('[data-group]').forEach(b=>b.setAttribute('aria-pressed',String(b===groupButton)));
      display();
    }
    if(pageButton){page+=Number(pageButton.dataset.page);display();root.querySelector(`[data-page="${pageButton.dataset.page}"]:not(:disabled)`)?.focus();}
  });
  root.querySelector('h1').focus({preventScroll:true});
  return refresh();
}
