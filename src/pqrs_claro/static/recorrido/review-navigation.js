import {esc} from './views.js';
import {initialReady,routes} from './initial-review.js?v=phase4';

export function reviewItems(current,value,draft){
  const valid=initialReady(value), decisions=draft?.requests||value.decisions||[];
  return (current.identification?.requests||[]).map((request,index)=>{
    const report=value.report?.requests.find(r=>r.request_id===request.id);
    const decision=decisions.find(r=>r.request_id===request.id);
    const attention=valid&&report&&(decision?.petition_type||report.petition_type)==='undetermined'
      ||valid&&report&&((decision?.route||report.proposed_route)!=='continue'
        ||(report.checks||[]).some(c=>['attention','unverified'].includes(c.state)));
    const state=!valid?'Análisis pendiente':attention?'Con observaciones':decision?.reviewed?(draft?'Revisada · sin confirmar':'Revisión registrada'):'Por revisar';
    return {id:request.id,index,title:request.title,label:request.label,state,attention:Boolean(attention)};
  });
}
export function nextReviewIndex(items,cursor=-1){
  const candidates=items.some(r=>r.attention)?items.filter(r=>r.attention):items;
  return (candidates.find(r=>r.index>cursor)||candidates[0])?.index??-1;
}
export function suggestedReviewer(managers,selected){
  return managers.find(m=>m.id===selected)?.name||'';
}
export function reviewRoute(value,draft){
  if(!initialReady(value))return 'Disponible al terminar el análisis vigente';
  const route=draft?.document?.route||value.document_decision?.route||value.report.document.proposed_route;
  const requests=draft?.requests||value.decisions||value.report.requests;
  return (routes[route]||route)+(route==='continue'&&requests.some(r=>(r.route||r.proposed_route)!=='continue')?' · Hay peticiones con ruta alternativa':'');
}
export function reviewNavigation(current,value,draft,{cursor=-1,busy=false}={}){
  const items=reviewItems(current,value,draft);if(!items.length)return '';
  const closed=current.management?.state==='closed',ready=initialReady(value),count=items.filter(r=>r.attention).length;
  const next=closed?'Consulta el análisis guardado.':!ready?'Espera el análisis o reintenta lo pendiente desde el resumen.':value.can_prepare&&!draft?'Revisión confirmada. Puedes preparar las respuestas.':'Revisa las peticiones y confirma al terminar. Guardar borrador no inicia la preparación.';
  return `<section class="review-overview" aria-label="Ruta y siguiente paso"><p><strong data-review-route-label>${value.document_decision&&!draft?'Ruta registrada':'Ruta propuesta'}:</strong> <span data-review-route>${esc(reviewRoute(value,draft))}</span></p><p data-review-next>${esc(next)}</p></section>
  <nav class="review-navigator" aria-label="Navegación de peticiones"><label>Ir a petición<select data-review-index aria-label="Ir a petición"><option value="">${items.length} peticiones · ${count} con observaciones</option>${items.map(r=>`<option value="${r.index}" ${cursor===r.index?'selected':''}>${esc(r.label)} · ${esc(r.title)} — ${esc(r.state)}</option>`).join('')}</select></label><button type="button" data-action="live-review-next">${count?'Siguiente con observaciones':'Siguiente petición'}</button>${!closed&&ready?`<button type="button" data-action="live-initial-save" ${busy?'disabled':''}>Guardar borrador</button><button type="button" class="primary" data-action="live-review-confirm">Ir a confirmar</button>`:''}<span class="sr-only" data-review-position aria-live="polite"></span></nav>`;
}
export function focusReviewPetition(view,index,{reveal=false}={}){
  const card=view.querySelector(`#identified-${index}`),heading=card?.querySelector('h2');
  if(!heading)return false;
  if(reveal){
    const details=card.querySelector('.intake-petition-details');if(details)details.open=true;
    card.querySelectorAll('.initial-checks details').forEach(item=>{
      if(item.querySelector('.initial-state.attention,.initial-state.unverified'))item.open=true;
    });
  }
  heading.tabIndex=-1;heading.focus({preventScroll:true});
  heading.scrollIntoView({block:'center',behavior:'auto'});
  const select=view.querySelector('[data-review-index]');if(select)select.value=String(index);
  const status=view.querySelector('[data-review-position]');if(status)status.textContent=`Petición ${index+1}: ${heading.textContent}`;
  return true;
}
export function syncReviewNavigation(view,current,value,draft){
  const label=view.querySelector('[data-review-route-label]');if(label)label.textContent=value.document_decision&&!draft?'Ruta registrada:':'Ruta propuesta:';
  const route=view.querySelector('[data-review-route]');if(route)route.textContent=reviewRoute(value,draft);
  const select=view.querySelector('[data-review-index]');
  const items=reviewItems(current,value,draft),count=items.filter(r=>r.attention).length;
  const next=view.querySelector('[data-action="live-review-next"]');
  if(next)next.textContent=count?'Siguiente con observaciones':'Siguiente petición';
  const summary=select?.querySelector('option[value=""]');
  if(summary)summary.textContent=`${items.length} peticiones · ${count} con observaciones`;
  const message=view.querySelector('[data-review-next]');
  if(message&&draft)message.textContent='Cambios pendientes de confirmación. Guardar borrador conserva tu trabajo sin iniciar la preparación.';
  if(select)for(const row of items){
    const option=select.querySelector(`option[value="${row.index}"]`);
    if(option)option.textContent=`${row.label} · ${row.title} — ${row.state}`;
  }
}
