import {progress} from './inbox-progress.js?v=office-progress1';

export const inboxSections = {
  mine: {id:'live-open', title:'Mi trabajo', description:'Tus expedientes abiertos y el siguiente paso de cada uno.'},
  active: {id:'workspace-pool', title:'Pool del equipo', description:'Expedientes disponibles y asignados a los gestores del equipo.'},
  pending: {id:'workspace-pending', title:'Pendientes por resolver', description:'Tus expedientes que necesitan una revisión o una acción del gestor.'},
  drafts: {id:'workspace-drafts', title:'Borradores', description:'Tus oficios guardados para continuar la revisión o finalizar la gestión.'},
  closed: {id:'workspace-closed', title:'Finalizadas', description:'Consulta tus expedientes finalizados y sus documentos conservados.'},
  trash: {id:'workspace-trash', title:'Papelera', description:'Expedientes eliminados que puedes consultar y restaurar.'},
};

export function needsAttention(c){
  if(c.deleted_at || c.management?.state==='closed')return false;
  // Waiting for a worker is not a task for the manager.
  if(c.processing || ['reading','identifying','confirming'].includes(c.status) ||
    c.preanalysis_status==='running' || c.initial_review_status==='running' ||
    c.preparation?.status==='running' || c.office_progress?.status==='generating')return false;
  if(c.office_progress?.status==='ready')return false;
  return c.management?.state==='pending' || ['review','error','preanalysis'].includes(progress(c).tone) ||
    c.initial_review_status==='routed' || Boolean(c.preparation?.stale) ||
    ['waiting_review','error','interrupted'].includes(c.preparation?.status);
}

export function sectionCases(active,trash,section,manager){
  if(section==='trash')return trash;
  const cases=active.filter(c=>!c.deleted_at);
  const own=c=>Boolean(manager)&&c.management?.owner_id===manager;
  if(section==='closed')return cases.filter(c=>own(c)&&c.management?.state==='closed');
  const open=cases.filter(c=>c.management?.state!=='closed');
  if(section==='active')return open;
  if(section==='unassigned')return open.filter(c=>!c.management?.owner_id);
  const mine=open.filter(own);
  if(section==='pending')return mine.filter(needsAttention);
  if(section==='drafts')return mine.filter(c=>c.saved_stage>=3 || c.office_progress || c.management?.state==='ready_review');
  return mine;
}

export function sectionCounts(active,trash,manager){
  return Object.fromEntries(Object.keys(inboxSections).map(section=>[
    section, !manager&&['mine','pending','drafts','closed'].includes(section)?null:sectionCases(active,trash,section,manager).length,
  ]));
}

export function caseStep(c,section){
  return ['drafts','closed'].includes(section)?3:Math.min(progress(c).stage,3);
}
