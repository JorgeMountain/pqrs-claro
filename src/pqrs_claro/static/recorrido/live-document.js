import {esc} from './views.js';
import {bindActor,sessionActor} from './session-actor.js';
import {createDocumentTools,toolsMarkup} from './document-tools.js?v=20260911-tools';

const clone=v=>structuredClone(v);
const signature=s=>JSON.stringify([s.metadata,s.attachment_source_ids,s.requests.map(r=>[r.request_id,r.paragraphs])]);
const labels={city:'Ciudad',issue_date:'Fecha del oficio',received_date:'Fecha de recepción (opcional)',office_number:'Número de oficio (opcional)',petition_number:'Radicado (opcional)',recipient_contact:'Contacto del destinatario (opcional)'};
async function api(url,body,method='POST'){
  const res=await fetch(url,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await res.json();
  if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Revisa los datos del oficio. No se pudo completar la operación.');
  return data;
}
export function createFinal({getCase,hasChanges,notice,isVisible,back}){
  const states=new Map();
  const state=()=>{
    const id=getCase()?.id;if(!id)return null;
    if(!states.has(id))states.set(id,{id,node:document.createElement('section'),work:null,saved:null,info:null,busy:false,message:'',error:'',timer:null});
    return states.get(id);
  };
  const path=(s,suffix='')=>`/api/cases/${s.id}/office${suffix}`;
  const dirty=s=>Boolean(s.work&&signature(s.work)!==signature(s.saved));
  const active=s=>getCase()?.id===s.id&&isVisible();
  function stamp(s){s.node.querySelector('[data-save-state]').textContent=dirty(s)?'Cambios sin guardar':s.work.revision?'Borrador guardado':'Oficio armado';s.node.querySelector('[data-downloads]')?.replaceChildren();s.tools?.refresh();status(s);}
  function updateText(s,index,text){
    const block=s.work.blocks[index];
    const meta={recipient:'recipient',subject:'subject',signer:'signer_name',signer_role:'signer_role',salutation:'salutation',intro:'introduction',closing:'closing'}[block.kind];
    if(meta)s.work.metadata[meta]=text;
    else for(const mark of block.bookmarks||[]){const [,ri,pi]=mark.split('_');if(s.work.requests[Number(ri)]?.paragraphs[Number(pi)])s.work.requests[Number(ri)].paragraphs[Number(pi)].text=text;}
    block.text=text;
  }
  function paragraph(s,index,action){
    const block=s.work.blocks[index];if(block?.bookmarks?.length!==1)return index;
    const [,ri,pi]=block.bookmarks[0].split('_').map((v,i)=>i?Number(v):v),row=s.work.requests[ri];
    const adding=action==='add',delta=adding?1:-1;
    if(adding&&row.paragraphs.length>=30||!adding&&row.paragraphs.length<=1)return index;
    const source=row.paragraphs[pi];
    if(!adding&&source.office_section==='response'&&row.paragraphs.filter(p=>p.office_section==='response').length===1)return index;
    if(adding)row.paragraphs.splice(pi+1,0,{...clone(source),text:''});else row.paragraphs.splice(pi,1);
    if(!adding)s.work.blocks.splice(index,1);
    for(const item of s.work.blocks){
      if(!item.bookmarks)continue;
      item.bookmarks=item.bookmarks.map(mark=>{const [,r,p]=mark.split('_');return Number(r)===ri&&Number(p)>pi?`response_${r}_${Number(p)+delta}`:mark;});
      item.bookmark=item.bookmarks[0];
    }
    if(adding){const mark=`response_${ri}_${pi+1}`;s.work.blocks.splice(index+1,0,{...clone(block),text:'',bookmark:mark,bookmarks:[mark]});return index+1;}
    return Math.max(0,index-1);
  }
  function renderSheet(s){
    s.node.querySelector('.oficio-sheet').innerHTML=`<div class="oficio-letterhead"><img src="/logo.png" alt="Universidad de Antioquia · Facultad de Ingeniería"></div>${s.work.blocks.map((b,i)=>editor(s,b,i)).join('')||'<p>Las respuestas aparecerán cuando estén preparadas.</p>'}`;
    s.node.querySelectorAll('[data-block]').forEach(el=>{
      el.oninput=()=>{updateText(s,Number(el.dataset.block),el.innerText.replace(/\r\n/g,'\n'));stamp(s);};
      el.addEventListener('paste',event=>{event.preventDefault();s.tools?.record(el.dataset.block);document.execCommand('insertText',false,event.clipboardData.getData('text/plain'));});
    });
    s.tools?.bindSheet();
  }
  function editor(s,block,index){
    const meta={recipient:'recipient',subject:'subject',signer:'signer_name',signer_role:'signer_role',salutation:'salutation',intro:'introduction',closing:'closing'}[block.kind];
    const editable=meta||(block.bookmarks||[]).some(mark=>{const [,ri,pi]=mark.split('_');return s.work.requests[Number(ri)]?.paragraphs[Number(pi)];});
    let text=block.text;
    if(meta&&meta!=='introduction')text=s.work.metadata[meta]||'';
    const placeholder={salutation:'Saludo',introduction:'Introducción',closing:'Despedida',recipient:'Destinatario',subject:'Asunto',signer_name:'Nombre de quien suscribe',signer_role:'Cargo de quien suscribe'}[meta]||'Escribe aquí';
    const tag=block.kind==='heading'?'h3':'div';
    const attrs=editable?`contenteditable="plaintext-only" role="textbox" aria-multiline="true" aria-label="${esc(meta?placeholder:'Respuesta · '+(block.request_ids||[]).join(', '))}" data-block="${index}" data-placeholder="${esc(placeholder)}" spellcheck="true"`:'';
    return `<${tag} class="oficio-block kind-${block.kind}${editable?' oficio-editable':''}" ${attrs}>${esc(text)}</${tag}>`;
  }
  function paint(s){
    s.tools?.destroy();s.tools=null;
    s.node.className='live-final document-workspace';
    if(!s.work){s.node.innerHTML=`<h1>Tu oficio</h1><p role="status">${esc(s.error||'Armando el documento con las respuestas guardadas…')}</p><button data-reload>Volver a cargar</button>`;s.node.querySelector('[data-reload]').onclick=()=>load();return;}
    const w=s.work;
    s.node.innerHTML=`<header class="document-heading"><div><p class="eyebrow">PASO 3 · OFICIO</p><h1>Tu oficio, listo para ajustar</h1><p class="muted">Edita directamente sobre el documento. Guarda los cambios y genera la versión final.</p></div><span class="document-save-state" data-save-state>${dirty(s)?'Cambios sin guardar':s.work.revision?'Borrador guardado':'Oficio armado'}</span></header>
      <form class="document-settings"><details><summary>Datos del oficio y responsable</summary><div class="document-fields">${Object.entries(labels).map(([key,label])=>`<label>${label}<input data-meta="${key}" type="${key.endsWith('date')?'date':'text'}" value="${esc(w.metadata[key]||'')}" maxlength="300"></label>`).join('')}</div><fieldset class="document-attachments"><legend>Anexos que se incluirán</legend>${w.attachment_options.map(a=>`<label><input type="checkbox" data-attachment="${esc(a.source_id)}" ${w.attachment_source_ids.includes(a.source_id)?'checked':''}>${esc(a.title)}</label>`).join('')||'<p>No hay documentos citados disponibles para anexar.</p>'}</fieldset><label class="field">Responsable de esta sesión<input id="office-actor" required maxlength="240" value="${esc(sessionActor())}" autocomplete="name"></label><p class="small muted">Se registra una vez en esta sesión. La persona que suscribe se indica al cierre del oficio.</p></details></form>
      <div class="document-checks" role="status" aria-live="polite" data-checks></div>
      <div class="document-stage">${toolsMarkup()}<div class="document-canvas" tabindex="0" aria-label="Documento con desplazamiento independiente"><article class="oficio-sheet ${w.letterhead?'with-letterhead':''}" aria-label="Borrador editable del oficio"></article></div></div>
      <footer class="document-toolbar"><div><span data-operation role="status"></span><small>Al generar apruebas el contenido guardado de este oficio.</small></div><div class="document-buttons"><button data-command="cancel">Cancelar</button><button data-command="save">Guardar cambios</button><button class="primary" data-command="docx">Generar Word</button><button class="primary" data-command="pdf">Generar PDF</button></div></footer>
      <p data-error role="alert"></p><div data-downloads class="document-downloads"></div>`;
    const form=s.node.querySelector('form');bindActor(form);
    form.onsubmit=e=>{e.preventDefault();void act(s,()=>save(s));};
    s.node.querySelectorAll('[data-attachment]').forEach(input=>input.onchange=()=>{s.tools.record();w.attachment_source_ids=[...s.node.querySelectorAll('[data-attachment]:checked')].map(e=>e.dataset.attachment);stamp(s);});
    s.node.querySelectorAll('[data-meta]').forEach(input=>input.oninput=()=>{
      s.tools.record('meta-'+input.dataset.meta);w.metadata[input.dataset.meta]=input.value;
      if(['city','issue_date'].includes(input.dataset.meta)){
        const date=new Date(`${w.metadata.issue_date}T12:00:00`),block=w.blocks.find(b=>b.kind==='date');
        if(block&&!Number.isNaN(date.getTime())){block.text=`${w.metadata.city||'Medellín'}, ${date.toLocaleDateString('es-CO',{day:'numeric',month:'long',year:'numeric'})}`;s.node.querySelector('.kind-date').textContent=block.text;}
      }stamp(s);
    });
    renderSheet(s);
    s.tools=createDocumentTools(s,{renderSheet:()=>renderSheet(s),changed:()=>stamp(s),updateText:(i,text)=>updateText(s,i,text),paragraph:(i,action)=>paragraph(s,i,action),save:()=>void act(s,()=>save(s))});
    s.node.querySelectorAll('[data-command]').forEach(button=>button.onclick=()=>{
      if(button.dataset.command==='cancel')void act(s,async()=>{await load(true);notice('Se descartaron los cambios sin guardar.');});
      else if(button.dataset.command==='save')void act(s,()=>save(s));
      else void act(s,()=>generate(s,button.dataset.command));
    });
    status(s);
  }
  function status(s){
    if(!s.work)return;
    const rows=s.work.requests,checking=rows.filter(r=>r.status==='checking').length;
    const errors=rows.filter(r=>r.stale||['needs_changes','needs_evidence','error'].includes(r.status)||!r.paragraphs.length);
    const needs=rows.filter(r=>!['approved','ready','checking'].includes(r.status)&&r.paragraphs.length&&!r.stale);
    const box=s.node.querySelector('[data-checks]');
    if(box){
      box.innerHTML=checking?`<span class="source-spinner" aria-hidden="true"></span> Comprobando ${checking} ${checking===1?'respuesta':'respuestas'}… Puedes seguir leyendo el oficio.`:errors.length?`<details><summary>${errors.length} ${errors.length===1?'respuesta requiere un ajuste':'respuestas requieren ajustes'}</summary>${errors.map(r=>`<p><strong>${esc(r.label)}. ${esc(r.title)}</strong></p><ul>${(r.assessment?.issues?.length?r.assessment.issues.map(i=>i.description):[r.error||(r.stale?'Las fuentes cambiaron. Actualiza esta respuesta.':!r.paragraphs.length?'Esta respuesta aún no está preparada.':'Revisa los puntos pendientes de esta respuesta.')]).map(t=>`<li>${esc(t)}</li>`).join('')}</ul>`).join('')}<button data-back>Ir a las respuestas</button></details>`:dirty(s)?'Hay cambios sin guardar. Guarda para comprobar la nueva redacción.':needs.length?'Al guardar se comprobará la redacción pendiente.':'El contenido guardado pasó las comprobaciones. Puedes generar el oficio.';
      box.querySelector('[data-back]')?.addEventListener('click',back);
    }
    s.node.querySelector('[data-error]').textContent=s.error;
    s.node.querySelector('[data-operation]').textContent=s.message;
    s.node.querySelectorAll('[data-command]').forEach(b=>b.disabled=s.busy||(b.dataset.command!=='cancel'&&checking>0));
    s.node.querySelectorAll('[contenteditable]').forEach(e=>e.contentEditable=s.busy?'false':'plaintext-only');
    s.node.querySelectorAll('input').forEach(e=>e.disabled=s.busy);
    s.tools?.refresh();
  }
  async function act(s,work){
    if(s.busy)return;s.busy=true;s.error='';status(s);
    try{await work();}catch(e){s.error=e.message;}
    finally{s.busy=false;s.message='';status(s);}
  }
  function actor(s){
    const input=s.node.querySelector('#office-actor');
    if(input?.value.trim()&&input.value.trim()!==sessionActor())input.dispatchEvent(new Event('change'));
    if(!sessionActor()){
      s.node.querySelector('.document-settings details').open=true;
      throw new Error('Identifica una vez al responsable en «Datos del oficio y responsable». Se reutilizará durante esta sesión.');
    }
    return sessionActor();
  }
  async function save(s){
    if(hasChanges(s.id))throw new Error('Hay una edición sin guardar en «Preparar las respuestas». Guárdala o cancélala antes de guardar el oficio.');
    if(s.work.requests.some(r=>r.paragraphs.some(p=>!p.text.trim()||p.text.length>6000)))throw new Error('Completa o quita los párrafos vacíos. Cada párrafo admite hasta 6.000 caracteres.');
    const name=actor(s);s.message='Guardando el oficio…';status(s);
    const saved=await api(path(s,'/workspace'),{revision:s.work.revision,edited_by:name,metadata:s.work.metadata,attachment_source_ids:s.work.attachment_source_ids,requests:s.work.requests.map(r=>({request_id:r.request_id,revision:r.revision,paragraphs:r.paragraphs}))},'PUT');
    s.work=clone(saved);s.saved=clone(saved);s.editHistory=null;paint(s);
    await check(s);notice('Oficio guardado. Las comprobaciones pendientes continúan automáticamente.');
  }
  async function check(s){
    const candidates=s.work.requests.filter(r=>r.paragraphs.length&&!r.stale&&['editing','error'].includes(r.status));
    const results=await Promise.allSettled(candidates.map(r=>api(`/api/cases/${s.id}/review/requests/${encodeURIComponent(r.request_id)}/assess`,{revision:r.revision})));
    const failed=results.filter(r=>r.status==='rejected');
    if(failed.length)s.error=failed.map(r=>r.reason.message).join(' ');
    await poll(s);
  }
  async function poll(s){
    clearTimeout(s.timer);
    const latest=await api(`/api/cases/${s.id}/review`);
    for(const row of latest.requests){
      const local=s.work.requests.find(r=>r.request_id===row.request_id),saved=s.saved.requests.find(r=>r.request_id===row.request_id);
      if(!local||!saved)continue;
      if(JSON.stringify(row.paragraphs)!==JSON.stringify(saved.paragraphs)){s.error='Una respuesta cambió en otra ventana. Tu texto local se conserva; cancela para cargar la versión actual.';continue;}
      for(const key of ['status','revision','assessment','approval','stale','error']){local[key]=clone(row[key]);saved[key]=clone(row[key]);}
    }
    status(s);
    if(latest.requests.some(r=>r.status==='checking')&&active(s))s.timer=setTimeout(()=>poll(s).catch(e=>{s.error=e.message;status(s);}),1800);
  }
  async function generate(s,kind){
    const name=actor(s);
    if(dirty(s)||hasChanges(s.id))throw new Error('Guarda tus cambios antes de generar el documento.');
    const required={city:'ciudad',recipient:'destinatario',subject:'asunto',signer_name:'nombre de quien suscribe',signer_role:'cargo de quien suscribe'};
    const missing=Object.entries(required).filter(([k])=>!s.work.metadata[k]?.trim()).map(([,label])=>label);
    if(missing.length)throw new Error('Completa en el oficio: '+missing.join(', ')+'.');
    const fresh=await api(path(s,'/workspace'));
    if(fresh.revision!==s.work.revision||signature(fresh)!==signature(s.work))throw new Error('El oficio cambió en otra ventana. Cancela para cargar la versión actual antes de generar.');
    if(!fresh.requests.length||fresh.requests.some(r=>r.stale||!['ready','approved'].includes(r.status)))throw new Error('Guarda el oficio y espera a que terminen las comprobaciones. Los ajustes concretos aparecerán sobre el documento.');
    s.message='Preparando la versión final…';status(s);
    for(const row of fresh.requests){if(row.status==='ready')await api(`/api/cases/${s.id}/review/requests/${encodeURIComponent(row.request_id)}/approve`,{revision:row.revision,assessment_hash:row.assessment.input_hash,approved_by:name,note:'Aprobación explícita del oficio completo mediante Generar.',confirmed:true});}
    const info=await api(path(s));s.info=info;
    const body={approval_snapshot_hash:info.approval_snapshot_hash,metadata:s.work.metadata,prepared_by:name,attachment_source_ids:s.work.attachment_source_ids};
    const preview=await api(path(s,'/preview'),body);
    let run=await api(path(s,'/generate'),{...body,preview_hash:preview.preview_hash});
    s.message='Creando Word y PDF con el membrete institucional…';status(s);
    while(run.status==='generating'){
      await new Promise(resolve=>setTimeout(resolve,1500));
      run=await api(path(s,`/runs/${run.id}`));
    }
    if(run.status!=='ready'||run.stale)throw new Error(run.error||'La versión cambió durante la generación. Actualiza el oficio.');
    await poll(s);
    showDownloads(s,run);
    s.node.querySelector(`[data-downloads] [href$="/${kind}"]`).click();notice('Word y PDF generados con la redacción guardada.');
  }
  function showDownloads(s,run){
    if(!run||run.status!=='ready'||run.stale||dirty(s))return;
    s.node.querySelector('[data-downloads]').innerHTML=`<strong>Documento generado</strong>${(run.attachment_count?['docx','pdf','zip']:['docx','pdf']).map(k=>`<a class="button" href="${path(s,`/runs/${run.id}/files/${k}`)}" download>Descargar ${k==='docx'?'Word':k==='pdf'?'PDF':'paquete con anexos'}</a>`).join('')}<details><summary>Ver las páginas del PDF final</summary>${Array.from({length:run.page_count||0},(_,i)=>`<img loading="lazy" src="${path(s,`/runs/${run.id}/pages/${i+1}`)}" alt="Página ${i+1} del oficio final">`).join('')}</details>`;
  }
  async function load(discard=false){
    const s=state();if(!s)return;
    try{
      const [work,info]=await Promise.all([api(path(s,'/workspace')),api(path(s))]);
      s.info=info;
      if(!s.work||discard||!dirty(s)){s.work=clone(work);s.saved=clone(work);s.editHistory=null;s.error='';paint(s);if(JSON.stringify(info.latest?.metadata)===JSON.stringify(work.metadata))showDownloads(s,info.latest);}else status(s);
      if(info.latest?.status==='generating'&&!s.busy)void act(s,async()=>{s.message='Generación en curso…';status(s);let run=info.latest;while(run.status==='generating'){await new Promise(resolve=>setTimeout(resolve,1500));run=await api(path(s,`/runs/${run.id}`));}if(run.status!=='ready'||run.stale)throw new Error(run.error||'La versión generada requiere actualizarse.');showDownloads(s,run);});
      if(work.requests.some(r=>r.status==='checking'))void poll(s).catch(e=>{s.error=e.message;status(s);});
    }catch(e){s.error=e.message;s.work?status(s):paint(s);}
  }
  window.addEventListener('beforeunload',event=>{if([...states.values()].some(dirty)){event.preventDefault();event.returnValue='';}});
  return {view(){const s=state();if(!s.node.childNodes.length)paint(s);return s.node;},load,setCase(){},hasChanges:id=>states.has(id)&&dirty(states.get(id))};
}
