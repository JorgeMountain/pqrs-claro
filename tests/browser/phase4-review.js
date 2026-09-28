// QA only: fictional APIs; refuses every unexpected request, never calls an AI provider.
import {createLive} from '/live.js?v=phase4';
const ids=Array.from({length:30},(_,i)=>'P'+(i+1));
const request=id=>({id,label:id.slice(1),title:'Petición '+id.slice(1)+' · información académica de demostración',description:'Solicitud ficticia de información '+id,source_refs:[],parent_id:null});
let record={id:'qa-phase4-browser',sha256:'qa-hash',version:1,status:'needs_review',filename:'Prueba ficticia.pdf',subject:'Validación de borradores',pages:[],identification:{requests:ids.map(request)}};
const check=key=>({key,state:'no_observation',summary:'Sin observaciones en esta prueba ficticia.',reason:'',original_refs:[],sources:[],pending:[]});
const report={document:{proposed_route:'continue',checks:[check('requirements'),check('respect')]},requests:ids.map(request_id=>({request_id,petition_type:'information',proposed_route:'continue',checks:[{...check('classification'),summary:request_id==='P3'||request_id==='P17'?'Verifica el tipo de solicitud propuesto.':'Sin observaciones en esta prueba ficticia.',reason:'Contrasta la intención de la persona con la clasificación sugerida. Ejemplo ficticio.',state:request_id==='P3'||request_id==='P17'?'attention':'no_observation'}, {...check('repetition'),state:'unavailable'}]})),special_treatment:{detected:false},warnings:[]};
let review={revision:1,fingerprint:'qa-generation',status:'needs_review',can_prepare:false,report:structuredClone(report)};
const requests=[];window.fetch=async(url,options={})=>{
 requests.push({url,method:options.method||'GET'});let data;
 if(url==='/api/config')data={initial_review_enabled:true,automatic_initial_review:true,management_enabled:true};
 else if(url==='/api/managers')data=[{id:localStorage.getItem('pqrs-pilot-manager')||'qa-manager',name:'Gestora de demostración'}];
 else if(url==='/api/cases/'+record.id)data=record;
 else if(url==='/api/cases/'+record.id+'/initial-review')data=review;
 else if(url==='/api/cases/'+record.id+'/identification'&&options.method==='PUT'){
  record={...record,identification:JSON.parse(options.body).identification,version:record.version+1};
  review={...review,revision:review.revision+1,selection_basis:{fingerprint:'qa-generation'},report:{...report,requests:report.requests.filter(r=>record.identification.requests.some(x=>x.id===r.request_id))}};data=record;
 }else throw Error('API inesperada bloqueada en QA: '+url);
 return {ok:true,json:async()=>structuredClone(data)};
};
const view=document.querySelector('#view'),drawer=document.querySelector('#drawer');
const notice=message=>document.querySelector('#notice').textContent=message;
const open=(title,html)=>{document.querySelector('#drawer-title').textContent=title;document.querySelector('#drawer-body').innerHTML=html;drawer.showModal();};
const live=createLive({open,close:()=>drawer.close(),notice,releaseDemo(){},onBrowse:()=>{
 if(live.leave()===false)return;view.innerHTML='<h1>Bandeja ficticia</h1><button id="qa-reopen">Reabrir expediente ficticio</button><p>Las APIs están simuladas. Ningún expediente real se modifica.</p>';
 document.querySelector('#qa-reopen').onclick=()=>live.select(record.id);
}});
document.querySelector('#close').onclick=()=>drawer.close();
document.querySelector('#workspace-inbox').onclick=()=>live.choose();
document.querySelector('#home-logo').onclick=e=>e.preventDefault();
document.querySelector('#main').insertAdjacentHTML('afterbegin','<p class="alert">QA FASE 4 · Datos ficticios · Sin llamadas a IA <button id="qa-reset">Limpiar borrador de prueba</button></p>');
document.querySelector('#qa-reset').onclick=()=>{localStorage.removeItem('pqrs-review-draft-v1:'+record.id);location.reload();};
await live.select(record.id);
