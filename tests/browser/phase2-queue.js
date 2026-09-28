// QA isolated inbox: real UI modules, fictional GET responses, no AI or real cases.
import {createCaseBrowser} from '/case-browser.js?v=phase2';
let processing=true,reads=0,fail=false;
const row=(id,closed=false)=>({id,version:1,lifecycle_revision:0,filename:'Caso ficticio.pdf',subject:closed?'Expediente finalizado de prueba':'Expediente en proceso de prueba',internal_number:id,created_at:'2026-09-28T12:00:00Z',last_activity:'2026-09-28T12:01:00Z',origin_kind:'gmail',status:'needs_review',request_count:2,processing:closed?false:processing,management:{revision:2,owner_id:'gestor-1',owner_name:'Gestor ficticio',started_at:'2026-09-28T12:00:00Z',updated_at:'2026-09-28T12:01:00Z',received_date:'2026-09-16',state:closed?'closed':'in_progress'}});
window.fetch=async(url,options={})=>{
 if(options.method)throw Error('QA bloquea toda escritura');
 reads++;document.querySelector('#qa-reads').textContent='Lecturas simuladas: '+reads;
 if(fail){fail=false;throw Error('Fallo simulado');}
 let data;if(url==='/api/managers')data=[{id:'gestor-1',name:'Gestor ficticio'}];
 else if(url==='/api/cases')data=[row('QA-A'),row('QA-B',true)];
 else if(url==='/api/cases?deleted=true')data=[];
 else throw Error('API inesperada: '+url);
 return {ok:true,json:async()=>data};
};
document.querySelector('.steps').hidden=true;document.querySelector('.prototype').hidden=true;
document.querySelector('#main').insertAdjacentHTML('afterbegin','<p class="alert">QA FASE 2 · Datos ficticios · Sin llamadas a IA</p><p id="qa-reads"></p><button id="qa-finish">Terminar trabajo simulado</button> <button id="qa-fail">Simular fallo de lectura</button> <button id="qa-leave">Salir de la bandeja de prueba</button>');
const browser=createCaseBrowser({container:document.querySelector('#view'),open(){},close(){},notice(){},onSelect(){},onNew(){}});
document.querySelector('#qa-finish').onclick=()=>{processing=false;};document.querySelector('#qa-fail').onclick=()=>{fail=true;};
document.querySelector('#qa-leave').onclick=()=>{document.querySelector('#view').innerHTML='<h1>Fuera de la bandeja</h1><p>El contador de lecturas debe dejar de aumentar.</p>';};
await browser.show();
