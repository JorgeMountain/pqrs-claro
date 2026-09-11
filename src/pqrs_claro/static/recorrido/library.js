import {createEvidenceUpload} from '/library-evidence.js';
import {esc} from './views.js';

const categories={historical_response:'Respuesta anterior',historical_attachment:'Anexo histórico',historical_petition:'Petición anterior',historical_other:'Otro archivo histórico',institutional_norm:'Normativa institucional',national_norm:'Normativa nacional',previous_response:'Referencia de estilo'};
const readings={ready:'Texto disponible',error:'Error de lectura',pending:'Lectura pendiente',partial:'Lectura parcial',unsupported:'Formato sin lectura automática'};
const normalize=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('es');
const original=id=>`/api/sources/${encodeURIComponent(id)}/original`;
async function api(path){
  const response=await fetch(path);let value;
  try{value=await response.json();}catch{throw new Error('No pudimos leer la biblioteca. Reintenta en unos momentos.');}
  if(!response.ok)throw new Error(value.detail||'No se pudo consultar la biblioteca.');
  return value;
}
export function createLibrary({open,close,notice}){
  let sources=[],collections=[],page=1,query='',category='',reading='',token=0;
  const intake=createEvidenceUpload({open,close,notice,getCase:()=>null,getData:()=>({requests:[]}),render:()=>{},changed:()=>{},onUpdated:()=>show()});
  function bindAdd(previous){
    return async()=>{try{await intake.uploadForm('',true,previous);}catch(error){notice(error.message);}};
  }
  async function show(){
    const current=++token;
    open('Biblioteca de fuentes',`<div class="library-panel"><p>Documentos compartidos para consultar y sustentar las respuestas. Los soportes privados permanecen en sus expedientes.</p><div class="library-actions"><button class="primary" id="library-add">Agregar fuente</button><button id="library-refresh">Actualizar</button></div><label class="field">Buscar por nombre, radicado o procedencia<input id="library-query" type="search" value="${esc(query)}" placeholder="Por ejemplo: 00995, Plan de Trabajo o Drive"></label><div class="library-filters"><label class="field">Tipo<select id="library-category"><option value="">Todos los tipos</option>${Object.entries(categories).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><label class="field">Lectura<select id="library-reading"><option value="">Todos los estados</option>${Object.entries(readings).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label></div><div id="library-list" role="status" aria-live="polite"><span class="source-loading"><span class="source-spinner" aria-hidden="true"></span>Cargando documentos…</span></div><p class="muted library-note">Se muestra la última versión de cada documento. Puedes consultar las anteriores en su ficha. Las colecciones históricas se usan según el alcance vinculado a cada expediente.</p></div>`);
    const list=document.querySelector('#library-list');
    const controls=document.querySelectorAll('#library-query,#library-category,#library-reading');
    controls.forEach(control=>control.disabled=true);
    document.querySelector('#library-add').onclick=bindAdd();
    document.querySelector('#library-refresh').onclick=show;
    try{
      const [catalog,groups]=await Promise.all([api('/api/sources'),api('/api/source-collections')]);
      if(current!==token||!list.isConnected)return;
      sources=catalog.sources;collections=groups.collections;
      controls.forEach(control=>control.disabled=false);
      const filter=document.querySelector('#library-category'),status=document.querySelector('#library-reading');
      filter.value=category;status.value=reading;
      document.querySelector('#library-query').oninput=e=>{query=e.target.value;page=1;draw(list);};
      filter.onchange=e=>{category=e.target.value;page=1;draw(list);};
      status.onchange=e=>{reading=e.target.value;page=1;draw(list);};
      draw(list);
    }catch(error){if(current===token&&list.isConnected)list.innerHTML=`<p role="alert">${esc(error.message)}</p><p>Usa «Actualizar» para volver a intentarlo.</p>`;}
  }
  function draw(list){
    const q=normalize(query),groupNames=new Map(collections.map(c=>[c.id,c.name]));
    const matches=sources.filter(s=>s.is_latest&&(!category||s.category===category)&&(!reading||(s.extraction_status||'ready')===reading)&&normalize([s.title,s.filename,s.origin,groupNames.get(s.collection_id)].join(' ')).includes(q));
    const pages=Math.max(1,Math.ceil(matches.length/15));page=Math.min(page,pages);
    list.innerHTML=`<p class="library-count">${matches.length} documentos${query||category||reading?' encontrados':''}</p>${matches.length?matches.slice((page-1)*15,page*15).map(s=>`<article class="source library-source"><h3>${esc(s.title)}</h3><p class="library-meta">${esc(categories[s.category]||s.category)} · Versión ${s.version} · ${esc(readings[s.extraction_status]||s.extraction_status||'Texto disponible')}</p>${groupNames.get(s.collection_id)?`<p class="library-meta">${esc(groupNames.get(s.collection_id))}</p>`:''}<div class="library-actions"><button data-library-detail="${esc(s.id)}">Ver documento</button><a href="${original(s.id)}" target="_blank" rel="noopener">Abrir original ↗</a></div></article>`).join(''):'<p>No hay documentos que coincidan. Prueba otro término o cambia los filtros.</p>'}<div class="library-pagination"><button id="library-prev" ${page===1?'disabled':''}>Anterior</button><span>Página ${page} de ${pages}</span><button id="library-next" ${page===pages?'disabled':''}>Siguiente</button></div>`;
    list.querySelectorAll('[data-library-detail]').forEach(b=>b.onclick=()=>detail(b.dataset.libraryDetail));
    list.querySelector('#library-prev').onclick=()=>{page--;draw(list);list.scrollIntoView({block:'start'});list.querySelector('#library-next').focus({preventScroll:true});};
    list.querySelector('#library-next').onclick=()=>{page++;draw(list);list.scrollIntoView({block:'start'});list.querySelector('#library-prev').focus({preventScroll:true});};
  }
  async function detail(id){
    const current=++token;
    open('Documento de la biblioteca','<button id="library-back">← Volver a la biblioteca</button><div id="library-document" role="status"><span class="source-loading"><span class="source-spinner" aria-hidden="true"></span>Cargando documento…</span></div>');
    document.querySelector('#library-back').onclick=show;
    const container=document.querySelector('#library-document');
    try{
      const result=await api('/api/sources/'+encodeURIComponent(id));
      if(current!==token||!container.isConnected)return;
      const s=result.source,versions=sources.filter(v=>v.document_id===s.document_id).sort((a,b)=>b.version-a.version);
      const uploadable=['historical_response','historical_attachment','institutional_norm','national_norm'].includes(s.category);
      container.innerHTML=`<section class="source"><h3>${esc(s.title)}</h3><p>${esc(categories[s.category]||s.category)} · ${esc(readings[s.extraction_status]||s.extraction_status||'Texto disponible')}</p><p><strong>Procedencia:</strong> ${esc(s.origin||'Sin procedencia registrada')}</p><p><strong>Archivo:</strong> ${esc(s.filename)}</p><p class="muted">La disponibilidad del texto no equivale a una verificación de su contenido.</p>${s.extraction_error?`<p role="alert">${esc(s.extraction_error)}</p>`:''}<label class="field">Versión<select id="library-version">${versions.map(v=>`<option value="${esc(v.id)}" ${v.id===id?'selected':''}>Versión ${v.version}${v.is_latest?' · actual':''}</option>`).join('')}</select></label><div class="library-actions"><a href="${original(id)}" target="_blank" rel="noopener">Abrir original ↗</a>${uploadable&&s.is_latest?'<button id="library-new-version">Agregar nueva versión</button>':''}</div></section>${result.pages.length?`<label class="field">Texto extraído · página o sección<select id="library-page">${result.pages.map((p,i)=>`<option value="${i}">${esc(p.number||i+1)}</option>`).join('')}</select></label><pre id="library-text" class="library-extract"></pre>`:'<p>No hay texto extraído disponible. Puedes consultar el archivo original.</p>'}`;
      document.querySelector('#library-version').onchange=e=>detail(e.target.value);
      document.querySelector('#library-new-version')?.addEventListener('click',bindAdd(s));
      if(result.pages.length){const text=document.querySelector('#library-text');text.textContent=result.pages[0].text;document.querySelector('#library-page').onchange=e=>{text.textContent=result.pages[Number(e.target.value)].text;};}
    }catch(error){if(current===token&&container.isConnected)container.innerHTML=`<p role="alert">${esc(error.message)}</p>`;}
  }
  return {show};
}
