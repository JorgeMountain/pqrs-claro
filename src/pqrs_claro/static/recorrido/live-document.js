import {esc} from './views.js';
import {bindActor,sessionActor} from './session-actor.js';
import {createDocumentTools,toolsMarkup} from './document-tools.js?v=draft-workspace1';
import {paginate,fragmentText,selectionPoint,focusPoint} from './document-pages.js';
import {deriveDraftReview,draftReviewMarkup} from './draft-review.js?v=draft-workspace1';
import {createDraftFragment} from './draft-fragment.js?v=draft-workspace1';
import {icon} from './inbox-icons.js';
import {draftSettings} from './draft-settings.js?v=draft-workspace1';
import {draftProgress} from './stage-progress.js?v=approval-progress1';
import {actor as managementActor} from './management-ui.js?v=phase2';

const clone=v=>structuredClone(v);
const signature=s=>JSON.stringify([s.metadata,s.attachment_source_ids,s.requests.map(r=>[r.request_id,r.paragraphs])]);
async function api(url,body,method='POST'){
  let res;
  try{res=await fetch(url,{signal:AbortSignal.timeout(60000),...(body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});}
  catch(error){if(['TimeoutError','AbortError'].includes(error.name))throw new Error('La operación está tardando más de lo esperado. Tu texto local se conserva; comprueba el estado guardado antes de volver a intentarlo.');throw error;}
  const data=await res.json();
  if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:'Revisa los datos del oficio. No se pudo completar la operación.');
  return data;
}
export function createFinal({getCase,hasChanges,notice,isVisible,back,onStateChange,getProgress,onFinalized}){
  const readOnly=s=>s?.closed||getCase()?.management?.state==='closed';
  const states=new Map();
  const state=()=>{
    const id=getCase()?.id;if(!id)return null;
    if(!states.has(id))states.set(id,{id,node:document.createElement('section'),work:null,saved:null,info:null,busy:false,message:'',error:'',timer:null,selectedId:null,confirmation:null,generatedSignature:null});
    return states.get(id);
  };
  const path=(s,suffix='')=>`/api/cases/${s.id}/office${suffix}`;
  const dirty=s=>Boolean(s.work&&signature(s.work)!==signature(s.saved));
  const active=s=>getCase()?.id===s.id&&isVisible();
  const progressFor=s=>active(s)?getProgress?.():null;
  function stamp(s){s.confirmation=null;s.approvalProgress=null;s.fragment?.clear();s.generatedSignature=null;s.node.querySelector('[data-downloads]')?.replaceChildren();s.tools?.refresh();status(s);}
  function updateText(s,index,text){
    s.fragment?.clear();
    const block=s.work.blocks[index];
    const meta={recipient:'recipient',subject:'subject',signer:'signer_name',signer_role:'signer_role',salutation:'salutation',intro:'introduction',closing:'closing'}[block.kind];
    if(meta){s.work.metadata[meta]=text;const field=s.node.querySelector(`[data-meta="${meta}"]`);if(field)field.value=text;}
    else for(const mark of block.bookmarks||[]){const [,ri,pi]=mark.split('_');if(s.work.requests[Number(ri)]?.paragraphs[Number(pi)])s.work.requests[Number(ri)].paragraphs[Number(pi)].text=text;}
    block.text=text;
  }
  function paragraph(s,index,action){
    s.fragment?.clear();
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
  function renderSheet(s,point=null){
    s.fragment?.clear();
    paginate(s.node,s.work.blocks,(b,i)=>editor(s,b,i),s.work.letterhead);
    s.node.querySelectorAll('[data-block]').forEach(el=>{
      el.oninput=event=>{
        const index=Number(el.dataset.block),point=selectionPoint(s.node);
        const text=[...s.node.querySelectorAll(`[data-block="${index}"]`)].map(fragmentText).join('');
        updateText(s,index,text.replace(/\r\n/g,'\n'));stamp(s);
        if(!event.isComposing)renderSheet(s,point);
      };
      el.addEventListener('compositionend',()=>renderSheet(s,selectionPoint(s.node)));
      el.addEventListener('beforeinput',event=>{
        const point=selectionPoint(s.node);if(!point)return;
        const index=point.block,text=s.work.blocks[index].text;
        const enter=['insertParagraph','insertLineBreak'].includes(event.inputType);
        const back=event.inputType==='deleteContentBackward'&&point.start===point.end&&point.start===Number(el.dataset.offset)&&point.start>0;
        const forward=event.inputType==='deleteContentForward'&&point.start===point.end&&point.start===Number(el.dataset.offset)+fragmentText(el).length&&point.start<text.length;
        if(!enter&&!back&&!forward)return;
        event.preventDefault();s.tools?.record(el.dataset.block);
        const start=back?point.start-[...text.slice(0,point.start)].at(-1).length:point.start;
        const end=forward?point.end+[...text.slice(point.end)][0].length:point.end;
        updateText(s,index,text.slice(0,start)+(enter?'\n':'')+text.slice(end));stamp(s);
        renderSheet(s,{block:index,start:start+(enter?1:0),end:start+(enter?1:0)});
      });
      el.addEventListener('paste',event=>{event.preventDefault();s.tools?.record(el.dataset.block);document.execCommand('insertText',false,event.clipboardData.getData('text/plain'));});
    });
    s.tools?.bindSheet();
    focusPoint(s.node,point);
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
  function confirmationKey(s){
    return JSON.stringify([signature(s.work),sessionActor(),s.work.requests.map(r=>[r.revision,r.assessment?.input_hash])]);
  }
  function paint(s){
    s.fragment?.clear();s.tools?.destroy();s.tools=null;
    s.node.className='live-final document-workspace draft-workspace';
    if(!s.work){s.node.innerHTML=`${draftProgress(null,null,{error:s.error,completed:progressFor(s)?.completed})}<p role="status">${esc(s.error||'Armando el documento con las respuestas guardadas…')}</p><button data-reload>Volver a cargar</button>`;s.node.querySelector('[data-reload]').onclick=()=>load();return;}
    const w=s.work;
    s.node.innerHTML=`<div data-draft-progress></div><div class="draft-layout">
      <section class="document-stage" aria-labelledby="draft-document-title">
        <div class="draft-editor-heading"><h2 id="draft-document-title">Documento del oficio</h2>${toolsMarkup({compact:true})}</div>
        <div class="draft-fragment-bar" data-fragment-bar hidden><span data-fragment-label role="status"></span><button type="button" class="text-button" data-clear-fragment>Quitar resaltado</button></div>
        <div class="document-canvas" tabindex="0" aria-label="Documento con desplazamiento independiente"><div class="oficio-pages" aria-label="Borrador editable del oficio"></div></div>
      </section>
      <aside class="draft-review-panel" aria-labelledby="draft-review-title">
        <div class="draft-review-heading"><h2 id="draft-review-title">Revisión final</h2><span class="draft-review-status" data-review-status></span></div>
        ${draftSettings(w,sessionActor()||getCase()?.management?.owner_name||'')}
        <div class="document-checks" data-checks role="status" aria-live="polite"></div>
        <div class="draft-adjustments" data-adjustments></div>
        <div class="draft-confirmation"><label><input type="checkbox" data-confirm-office><span data-confirm-label>He revisado el oficio completo</span></label><p data-confirm-hint></p></div>
      </aside>
    </div>
    <footer class="document-toolbar"><div class="document-buttons"><button type="button" data-command="save">${icon('check')}Guardar cambios</button><button type="button" class="text-button" data-command="cancel">Descartar cambios</button><span class="document-save-state" data-save-state role="status"></span></div><div class="draft-generation"><button type="button" class="primary" data-command="generate">Aprobar y generar ${icon('arrow-right')}</button><button type="button" class="primary" data-command="finalize" hidden>${icon('check')}Finalizar expediente</button><small data-generate-hint></small></div></footer>
    <p data-operation role="status"></p><p data-error role="alert"></p><div data-downloads class="document-downloads"></div>`;
    s.node.querySelector('.draft-editor-heading').after(s.node.querySelector('.document-tool-status'));
    s.fragment=createDraftFragment(s.node);
    s.node.querySelector('[data-clear-fragment]').onclick=()=>{s.fragment.clear();s.node.querySelector(`[data-select-adjustment="${s.selectedId}"]`)?.focus();};
    const form=s.node.querySelector('form');bindActor(form);
    form.onsubmit=e=>{e.preventDefault();void act(s,()=>save(s));};
    s.node.querySelector('#office-actor').addEventListener('change',()=>{s.confirmation=null;status(s);});
    s.node.querySelector('[data-confirm-office]').onchange=e=>{const checked=e.target.checked;try{if(checked)actor(s);s.confirmation=checked?confirmationKey(s):null;s.error='';}catch(error){s.error=error.message;s.confirmation=null;}status(s);};
    s.node.querySelectorAll('[data-attachment]').forEach(input=>input.onchange=()=>{s.tools.record();w.attachment_source_ids=[...s.node.querySelectorAll('[data-attachment]:checked')].map(e=>e.dataset.attachment);stamp(s);});
    s.node.querySelectorAll('[data-meta]').forEach(input=>input.oninput=()=>{
      s.tools.record('meta-'+input.dataset.meta);w.metadata[input.dataset.meta]=input.value;
      const kind={recipient:'recipient',subject:'subject',signer_name:'signer',signer_role:'signer_role'}[input.dataset.meta];
      const block=w.blocks.find(b=>b.kind===kind);if(block)block.text=input.value;
      if(['city','issue_date'].includes(input.dataset.meta)){
        const date=new Date(`${w.metadata.issue_date}T12:00:00`),line=w.blocks.find(b=>b.kind==='date');
        if(line&&!Number.isNaN(date.getTime()))line.text=`${w.metadata.city||'Medellín'}, ${date.toLocaleDateString('es-CO',{day:'numeric',month:'long',year:'numeric'})}`;
      }
      stamp(s);renderSheet(s);
    });
    renderSheet(s);
    s.tools=createDocumentTools(s,{isReadOnly:()=>readOnly(s),renderSheet:()=>renderSheet(s),changed:()=>stamp(s),updateText:(i,text)=>updateText(s,i,text),paragraph:(i,action)=>paragraph(s,i,action),save:()=>void act(s,()=>save(s))});
    s.node.querySelectorAll('[data-command]').forEach(button=>button.onclick=()=>{
      if(button.dataset.command==='cancel')void act(s,async()=>{await load(true);notice('Se descartaron los cambios sin guardar.');});
      else if(button.dataset.command==='save')void act(s,()=>save(s));
      else if(button.dataset.command==='finalize')void act(s,()=>finalize(s));
      else void act(s,()=>generate(s));
    });
    s.panelMarkup=null;status(s);
  }
  function renderAdjustments(s,model){
    if(!model.items.some(item=>item.id===s.selectedId)){s.selectedId=model.items[0]?.id||null;s.fragment?.clear();}
    const box=s.node.querySelector('[data-adjustments]');
    const markup=draftReviewMarkup(model,{selectedId:s.selectedId,dirty:dirty(s),busy:s.busy});
    if(markup===s.panelMarkup)return;
    const focus=document.activeElement?.closest('[data-select-adjustment]')?.dataset.selectAdjustment;
    s.panelMarkup=markup;box.innerHTML=markup;
    const reveal=id=>{const list=box.querySelector('.draft-adjustment-list'),card=box.querySelector(`[data-select-adjustment="${id}"]`)?.closest('li');if(list&&card&&list.scrollHeight>list.clientHeight)list.scrollTop+=card.getBoundingClientRect().top-list.getBoundingClientRect().top-4;};
    const select=id=>{s.fragment?.clear();s.selectedId=id;s.panelMarkup=null;status(s);box.querySelector(`[data-select-adjustment="${id}"]`)?.focus({preventScroll:true});reveal(id);};
    box.querySelectorAll('[data-select-adjustment]').forEach(button=>button.onclick=()=>select(button.dataset.selectAdjustment));
    box.querySelectorAll('[data-view-fragment]').forEach(button=>button.onclick=()=>{
      const item=model.items.find(item=>item.id===button.dataset.viewFragment);
      if(dirty(s)){s.error='Guarda y comprueba los cambios para localizar el fragmento actualizado.';status(s);return;}
      if(!s.fragment.show(item,model.items.indexOf(item)+1)){s.error='Este ajuste no tiene un párrafo localizado. Revisa la respuesta completa.';status(s);}
      reveal(item?.id);
    });
    box.querySelectorAll('[data-review-adjustment]').forEach(button=>button.onclick=()=>back(model.items.find(item=>item.id===button.dataset.reviewAdjustment)?.requestId));
    box.querySelector('[data-adjustment-prev]')?.addEventListener('click',()=>{const i=model.items.findIndex(item=>item.id===s.selectedId);if(i>0)select(model.items[i-1].id);});
    box.querySelector('[data-adjustment-next]')?.addEventListener('click',()=>{const i=model.items.findIndex(item=>item.id===s.selectedId);if(i<model.items.length-1)select(model.items[i+1].id);});
    if(focus)box.querySelector(`[data-select-adjustment="${focus}"]`)?.focus({preventScroll:true});
  }
  function status(s){
    if(!s.work)return;
    const model=deriveDraftReview(s.work),unsaved=dirty(s),externalChanges=hasChanges(s.id);
    const generated=s.generatedSignature===signature(s.work)&&!unsaved&&!externalChanges&&model.canGenerate;
    const canGenerate=model.canGenerate&&!unsaved&&!externalChanges&&!readOnly(s);
    const confirmed=s.confirmation===confirmationKey(s);
    const checkbox=s.node.querySelector('[data-confirm-office]');checkbox.checked=confirmed&&canGenerate;checkbox.disabled=s.busy||!canGenerate||generated;checkbox.hidden=generated||readOnly(s);
    s.node.querySelector('[data-confirm-label]').textContent=generated?'Revisión del oficio registrada':readOnly(s)?'Consulta del oficio guardado':'He revisado el oficio completo';
    if(!canGenerate)s.confirmation=null;
    renderAdjustments(s,model);
    const readyNotice=s.node.querySelector('.draft-review-empty.is-ready');if(readyNotice&&generated)readyNotice.textContent='El oficio revisado y sus archivos están guardados.';
    const count=model.items.length,checking=model.checking;
    const redactionComplete=s.work.requests.length>0&&s.work.requests.length===getCase()?.request_count&&s.work.requests.every(r=>r.paragraphs.length&&!r.stale);
    const completed=[...(progressFor(s)?.completed||[])];completed[2]=redactionComplete;
    const progress=draftProgress(s.work,model,{total:getCase()?.request_count,dirty:unsaved,externalChanges,busy:s.busy,message:s.message,error:s.error,generated,confirmed:confirmed&&canGenerate,completed,approval:s.approvalProgress});
    const progressNode=s.node.querySelector('[data-draft-progress]');
    if(progressNode.innerHTML!==progress)progressNode.innerHTML=progress;
    const label=readOnly(s)?'Expediente finalizado':generated?'Oficio generado':checking?'Comprobando':count?`${count} ${count===1?'ajuste pendiente':'ajustes pendientes'}`:unsaved?'Sin guardar':model.canGenerate?'Listo para revisar':'Por preparar';
    const badge=s.node.querySelector('[data-review-status]');badge.textContent=label;badge.classList.toggle('complete',model.canGenerate&&!unsaved);
    const hint=readOnly(s)?'La gestión está finalizada. El contenido se conserva para consulta.':generated?'La revisión y generación de esta versión ya están registradas.':unsaved?'Guarda los cambios para comprobar la nueva redacción.':externalChanges?'Hay cambios sin guardar en Redacción.':checking?'Espera a que terminen las comprobaciones.':count?`Resuelve ${count} ${count===1?'ajuste':'ajustes'} antes de aprobar.`:!model.canGenerate?'Prepara las respuestas para continuar.':confirmed?'Al generar apruebas el contenido guardado del oficio.':'Confirma la revisión del oficio completo.';
    s.node.querySelector('[data-confirm-hint]').textContent=hint;
    const own=getCase()?.id===s.id&&getCase().management?.owner_id===managementActor();
    s.node.querySelector('[data-generate-hint]').textContent=readOnly(s)?'Conservado en Finalizadas para consulta.':generated?own?'Pasará a Finalizadas. Podrás consultar las respuestas y descargar el oficio.':'Selecciona al gestor responsable para finalizar el expediente.':confirmed&&canGenerate?'Se generarán Word y PDF.':hint;
    const approving=s.busy&&s.approvalProgress;
    s.node.querySelector('[data-command="generate"]').innerHTML=generated?'Oficio generado':approving?approving.phase==='generating'?'Generando Word y PDF…':`Aprobadas ${approving.count}/${approving.total}…`:`Aprobar y generar ${icon('arrow-right')}`;
    if(approving)s.node.querySelector('[data-generate-hint]').textContent=s.message;
    s.node.querySelector('[data-command="generate"]').hidden=generated||readOnly(s);
    const finish=s.node.querySelector('[data-command="finalize"]');finish.hidden=!generated||readOnly(s);
    finish.innerHTML=s.closing?'Finalizando expediente…':`${icon('check')}Finalizar expediente`;
    s.node.querySelector('[data-checks]').innerHTML=!s.work.requests.length?'<button type="button" data-back>Volver a redacción</button>':'';
    s.node.querySelector('[data-back]')?.addEventListener('click',()=>back());
    s.node.querySelector('[data-error]').textContent=s.error;
    s.node.querySelector('[data-operation]').textContent=s.message;
    s.node.querySelector('[data-save-state]').textContent=unsaved?'Cambios sin guardar':s.work.revision?'Cambios guardados':'Borrador sin cambios';
    s.node.querySelectorAll('[data-command]').forEach(b=>b.disabled=s.busy||readOnly(s)||(b.dataset.command!=='cancel'&&checking>0)||(b.dataset.command==='generate'&&(generated||!canGenerate||!confirmed))||(b.dataset.command==='finalize'&&(!generated||!own)));
    s.node.querySelectorAll('[contenteditable]').forEach(e=>e.contentEditable=s.busy||readOnly(s)?'false':'plaintext-only');
    s.node.querySelectorAll('input:not([data-confirm-office])').forEach(e=>e.disabled=s.busy||readOnly(s));
    s.tools?.refresh();
    if(readOnly(s)){
      s.node.querySelectorAll('[data-tool="save"],[data-tool="add"],[data-tool="remove"],[data-tool="undo"],[data-tool="redo"],[data-tool="replace"],[data-tool="all"]').forEach(e=>e.disabled=true);
      s.node.querySelector('[data-operation]').textContent='Expediente finalizado · consulta del oficio y descargas disponibles.';
    }
    const summary={id:s.id,redactionComplete,draftComplete:generated};
    const key=JSON.stringify(summary);if(key!==s.summaryKey){s.summaryKey=key;if(active(s))onStateChange?.(summary);}
  }
  async function act(s,work){
    if(readOnly(s)){s.error='Reabre la gestión desde la bandeja antes de modificar el oficio.';status(s);return;}
    if(s.busy)return;s.busy=true;s.error='';status(s);
    try{await work();}catch(e){s.error=e.message;}
    finally{s.busy=false;s.message='';status(s);}
  }
  function actor(s){
    const input=s.node.querySelector('#office-actor');
    if(input?.value.trim()&&input.value.trim()!==sessionActor())input.dispatchEvent(new Event('change'));
    if(!sessionActor()){
      s.node.querySelector('[data-responsible-details]').open=true;
      input?.focus();
      throw new Error('Indica el responsable en «Responsable y firma». Se reutilizará durante esta sesión.');
    }
    return sessionActor();
  }
  async function save(s){
    if(hasChanges(s.id))throw new Error('Hay una edición sin guardar en «Preparar las respuestas». Guárdala o cancélala antes de guardar el oficio.');
    if(s.work.requests.some(r=>r.paragraphs.some(p=>!p.text.trim()||p.text.length>6000)))throw new Error('Completa o quita los párrafos vacíos. Cada párrafo admite hasta 6.000 caracteres.');
    const name=actor(s);s.message='Guardando el oficio…';status(s);
    const saved=await api(path(s,'/workspace'),{revision:s.work.revision,edited_by:name,metadata:s.work.metadata,attachment_source_ids:s.work.attachment_source_ids,requests:s.work.requests.map(r=>({request_id:r.request_id,revision:r.revision,paragraphs:r.paragraphs}))},'PUT');
    s.work=clone(saved);s.saved=clone(saved);s.editHistory=null;s.confirmation=null;s.generatedSignature=null;paint(s);
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
      if(JSON.stringify(row.paragraphs)!==JSON.stringify(saved.paragraphs)){s.error='Una respuesta cambió en otra ventana. Tu texto local se conserva; usa «Descartar cambios» para cargar la versión actual.';s.confirmation=null;s.fragment?.clear();continue;}
      for(const key of ['status','revision','assessment','approval','stale','error']){local[key]=clone(row[key]);saved[key]=clone(row[key]);}
    }
    status(s);
    if(latest.requests.some(r=>r.status==='checking')&&active(s))s.timer=setTimeout(()=>poll(s).catch(e=>{s.error=e.message;status(s);}),1800);
  }
  async function generate(s){
    const name=actor(s);
    if(s.confirmation!==confirmationKey(s))throw new Error('Confirma que has revisado el oficio completo antes de aprobar y generar.');
    if(dirty(s)||hasChanges(s.id))throw new Error('Guarda tus cambios antes de generar el documento.');
    const required={city:'ciudad',recipient:'destinatario',subject:'asunto',signer_name:'nombre de quien suscribe',signer_role:'cargo de quien suscribe'};
    const missing=Object.entries(required).filter(([k])=>!s.work.metadata[k]?.trim()).map(([,label])=>label);
    if(missing.length)throw new Error('Completa en el oficio: '+missing.join(', ')+'.');
    s.approvalProgress={count:s.work.requests.filter(r=>r.status==='approved').length,total:s.work.requests.length,phase:'validating'};
    s.message='Comprobando la versión guardada del oficio…';status(s);
    const fresh=await api(path(s,'/workspace'));
    if(fresh.revision!==s.work.revision||signature(fresh)!==signature(s.work))throw new Error('El oficio cambió en otra ventana. Usa «Descartar cambios» para cargar la versión actual antes de generar.');
    if(!deriveDraftReview(fresh).canGenerate)throw new Error('Guarda el oficio y espera a que terminen las comprobaciones. Los ajustes aparecerán en «Revisión final».');
    s.approvalProgress={count:fresh.requests.filter(r=>r.status==='approved').length,total:fresh.requests.length,phase:'approving'};
    for(const row of fresh.requests){
      if(row.status!=='ready')continue;
      s.message=`Aprobando la respuesta ${fresh.requests.indexOf(row)+1} de ${fresh.requests.length}…`;status(s);
      await api(`/api/cases/${s.id}/review/requests/${encodeURIComponent(row.request_id)}/approve`,{revision:row.revision,assessment_hash:row.assessment.input_hash,approved_by:name,note:'Aprobación explícita del oficio completo mediante Generar.',confirmed:true});
      s.approvalProgress.count++;status(s);
    }
    s.approvalProgress.phase='preparing';s.message='Aprobaciones guardadas. Preparando el oficio final…';status(s);
    const info=await api(path(s));s.info=info;
    const body={approval_snapshot_hash:info.approval_snapshot_hash,metadata:s.work.metadata,prepared_by:name,attachment_source_ids:s.work.attachment_source_ids};
    const preview=await api(path(s,'/preview'),body);
    s.approvalProgress.phase='generating';s.message='Creando Word y PDF con el membrete institucional…';status(s);
    let run=await api(path(s,'/generate'),{...body,preview_hash:preview.preview_hash});
    while(run.status==='generating'){
      await new Promise(resolve=>setTimeout(resolve,1500));
      run=await api(path(s,`/runs/${run.id}`));
    }
    if(run.status!=='ready'||run.stale)throw new Error(run.error||'La versión cambió durante la generación. Actualiza el oficio.');
    await poll(s);
    showDownloads(s,run);
    s.node.querySelector('[data-downloads]')?.scrollIntoView({block:'nearest'});notice('Word y PDF generados. Ya puedes descargarlos.');
  }
  async function finalize(s){
    const unchanged=()=>s.generatedSignature===signature(s.work)&&!dirty(s)&&!hasChanges(s.id)&&deriveDraftReview(s.work).canGenerate;
    if(!s.generatedRun||!unchanged())throw new Error('Guarda tus cambios y genera el oficio actualizado antes de finalizar el expediente.');
    const manager=managementActor();
    if(!manager||getCase()?.id!==s.id||getCase().management?.owner_id!==manager)throw new Error('Selecciona al gestor responsable para finalizar el expediente.');
    s.closing=true;s.message='Conservando el expediente en Finalizadas…';status(s);
    try{
      const latest=await api(`/api/cases/${s.id}`);
      if(latest.management?.owner_id!==manager)throw new Error('El responsable cambió. Actualiza el expediente antes de finalizar.');
      if(latest.processing)throw new Error('Espera a que termine el procesamiento antes de finalizar el expediente.');
      if(latest.management?.state!=='closed'){
        const fresh=await api(path(s,'/workspace'));
        const info=await api(path(s));
        if(!unchanged()||fresh.revision!==s.work.revision||signature(fresh)!==signature(s.work)||!deriveDraftReview(fresh).canGenerate||info.latest?.id!==s.generatedRun.id||info.latest?.status!=='ready'||info.latest.stale)throw new Error('El oficio cambió. Actualiza el borrador y comprueba la versión generada antes de finalizar.');
        if(managementActor()!==manager)throw new Error('El gestor activo cambió. Vuelve a comprobar el expediente antes de finalizar.');
        latest.management=await api(`/api/cases/${s.id}/management`,{revision:latest.management.revision,actor_id:manager,action:'state',state:'closed',note:'Finalizado desde Borrador con el oficio revisado y generado. Se conservan las respuestas, revisiones y archivos.'});
      }
      s.closed=true;clearTimeout(s.timer);
      if(getCase()?.id===s.id)await onFinalized?.(s.id,latest.management);
      notice('Expediente finalizado. Puedes consultarlo en Finalizadas.');
    }finally{s.closing=false;}
  }
  function showDownloads(s,run){
    if(!run||run.status!=='ready'||run.stale||dirty(s))return;
    s.generatedSignature=signature(s.work);
    s.generatedRun=run;
    s.node.querySelector('[data-downloads]').innerHTML=`<strong>Versión generada</strong>${(run.attachment_count?['docx','pdf','zip']:['docx','pdf']).map(k=>`<a class="button" href="${path(s,`/runs/${encodeURIComponent(run.id)}/files/${k}`)}" download>Descargar ${k==='docx'?'Word':k==='pdf'?'PDF':'paquete con anexos'}</a>`).join('')}<details><summary>Ver las páginas del PDF final</summary>${Array.from({length:run.page_count||0},(_,i)=>`<img loading="lazy" src="${path(s,`/runs/${encodeURIComponent(run.id)}/pages/${i+1}`)}" alt="Página ${i+1} del oficio final">`).join('')}</details>`;
    status(s);
  }
  async function restoreDownloads(s,run,info){
    if(!run||run.status!=='ready'||run.stale||dirty(s)||!info.approval_snapshot_hash||!run.prepared_by||!run.preview_hash)return;
    const current=signature(s.work);
    const preview=await api(path(s,'/preview'),{approval_snapshot_hash:info.approval_snapshot_hash,metadata:s.work.metadata,prepared_by:run.prepared_by,attachment_source_ids:s.work.attachment_source_ids});
    if(preview.preview_hash===run.preview_hash&&current===signature(s.work))showDownloads(s,run);
  }
  async function load(discard=false){
    const s=state();if(!s)return;
    s.closed=getCase()?.management?.state==='closed';
    if(!s.busy)s.approvalProgress=null;
    try{
      const work=await api(path(s,'/workspace'));
      if(!s.work||discard||!dirty(s)){s.work=clone(work);s.saved=clone(work);s.editHistory=null;s.error='';s.confirmation=null;s.generatedSignature=null;paint(s);
      }else status(s);
      // The editor can be read before looking up previous exports. Unapproved
      // replies cannot have a current final version; avoid a second costly review.
      const info=work.requests.length&&work.requests.every(row=>row.status==='approved'&&!row.stale)?await api(path(s)):{latest:null};
      s.info=info;
      await restoreDownloads(s,info.latest,info);
      if(info.latest?.status==='generating'&&!s.busy)void act(s,async()=>{s.message='Generación en curso…';status(s);let run=info.latest;while(run.status==='generating'){await new Promise(resolve=>setTimeout(resolve,1500));run=await api(path(s,`/runs/${run.id}`));}if(run.status!=='ready'||run.stale)throw new Error(run.error||'La versión generada requiere actualizarse.');await restoreDownloads(s,run,await api(path(s)));});
      if(work.requests.some(r=>r.status==='checking'))void poll(s).catch(e=>{s.error=e.message;status(s);});
    }catch(e){s.error=e.message;s.work?status(s):paint(s);if(discard)throw e;}
  }
  window.addEventListener('beforeunload',event=>{if([...states.values()].some(dirty)){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pqrs-manager-change',()=>{const s=states.get(getCase()?.id);if(s?.work&&active(s))status(s);});
  return {view(){const s=state();if(!s.node.childNodes.length)paint(s);return s.node;},load,hide(){state()?.fragment?.clear();},setCase(){for(const s of states.values()){s.fragment?.clear();clearTimeout(s.timer);s.confirmation=null;}},hasChanges:id=>states.has(id)&&dirty(states.get(id))};
}
