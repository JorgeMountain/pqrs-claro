import {esc} from './views.js';

const prefix='pqrs-review-draft-v1:';
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const content=r=>Object.fromEntries(Object.entries(r||{}).filter(([k])=>k!=='parent_id'));
export function draftEnvelope(current,value,decision,previous=null){
  const requests={...previous?.requests};
  for(const item of decision.requests){
    requests[item.request_id]={decision:{...item,reviewed:false},
      original:content(current.identification.requests.find(r=>r.id===item.request_id)),
      report:value.report.requests.find(r=>r.request_id===item.request_id)};
  }
  return structuredClone({case_id:current.id,sha256:current.sha256,revision:value.revision,
    fingerprint:value.selection_basis?.fingerprint||value.fingerprint,
    documentReport:value.report.document,requests,
    decision:{...decision,document:{...decision.document,reviewed:false},requests:decision.requests.map(r=>({...r,reviewed:false}))},
    updated_at:new Date().toISOString()});
}
export function restoreDraft(saved,current,value){
  if(!saved||saved.case_id!==current.id)return {draft:null,message:''};
  if(value.status==='running'||!value.report?.document)return {draft:null,message:'Tu borrador está conservado. Podrás recuperarlo cuando termine el análisis.'};
  const compatible=!value.stale&&saved.sha256===current.sha256&&
    ((saved.revision===value.revision&&saved.fingerprint===(value.selection_basis?.fingerprint||value.fingerprint))||Boolean(value.selection_basis)&&saved.fingerprint===value.selection_basis.fingerprint)&&
    same(saved.documentReport,value.report.document)&&value.report.requests.every(r=>{
      const previous=saved.requests[r.request_id];
      return previous&&same(previous.report,r)&&same(previous.original,content(current.identification.requests.find(x=>x.id===r.request_id)));
    });
  if(!compatible)return {draft:null,conflict:true,message:'El análisis cambió. Conservamos el borrador anterior para consultarlo; revisa los cambios antes de confirmar.'};
  return {draft:{...saved.decision,revision:value.revision,document:{...saved.decision.document,reviewed:false},
    requests:value.report.requests.map(r=>({...saved.requests[r.request_id].decision,reviewed:false}))},
    message:'Borrador recuperado de este navegador. Revisa y confirma cuando termines.'};
}
export function createReviewDraftStore(storage){
  const seen=new Map(),cache=new Map();
  function read(id){
    const raw=storage.getItem(prefix+id);seen.set(id,raw);
    const value=raw?JSON.parse(raw):null;cache.set(id,value);return value;
  }
  function write(current,value,decision){
    const id=current.id;if(!seen.has(id))read(id);
    const raw=storage.getItem(prefix+id);
    if(raw!==seen.get(id))throw new Error('Otra pestaña cambió el borrador. Tus cambios siguen en esta pantalla; descarga una copia antes de salir y recarga para revisar la otra versión.');
    const envelope=draftEnvelope(current,value,decision,cache.get(id));
    const encoded=JSON.stringify(envelope);storage.setItem(prefix+id,encoded);
    seen.set(id,encoded);cache.set(id,envelope);return envelope;
  }
  function clear(id){if(storage.getItem(prefix+id)===seen.get(id))storage.removeItem(prefix+id);seen.delete(id);cache.delete(id);}
  return {read,write,clear};
}
export function draftPreview(saved){
  if(!saved)return '<p>No hay un borrador anterior disponible.</p>';
  const row=(label,d)=>`<section><h3>${esc(label)}</h3><p>Ruta: ${esc(d.route||'')} · Tipo: ${esc(d.petition_type||'')}</p><p>${esc(d.note||'Sin observación adicional.')}</p>${d.communication?`<pre style="white-space:pre-wrap">${esc(d.communication)}</pre>`:''}</section>`;
  return `<p>Borrador sin confirmar · ${esc(saved.updated_at)} · ${esc(saved.decision.reviewed_by||'Sin responsable')}</p>${row('Documento completo',saved.decision.document)}${Object.entries(saved.requests).map(([id,r])=>row(r.original?.title||id,r.decision)).join('')}`;
}
