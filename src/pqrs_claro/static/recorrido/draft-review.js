import {esc} from './views.js';
import {icon} from './inbox-icons.js';

const list=value=>Array.isArray(value)?value:[];
const text=value=>typeof value==='string'?value.trim():'';
const finished=new Set(['ready','approved']);

// The identity follows the finding, not its position in a refreshed list.
function fingerprint(value){
  let hash=2166136261;
  for(const char of value){hash^=char.codePointAt(0);hash=Math.imul(hash,16777619);}
  return (hash>>>0).toString(36);
}

function shorten(value,limit){
  if(value.length<=limit)return value;
  const candidate=value.slice(0,limit-1),space=candidate.lastIndexOf(' ');
  return candidate.slice(0,space>limit*0.7?space:limit-1)+'…';
}

const shortTitle=description=>shorten(description,110);

function requestLabel(value,index){
  const label=text(value),number=label.match(/^(\d+(?:\.\d+)*)(?:[.)])?$/);
  return number?`Petición ${number[1]}`:label||`Petición ${index+1}`;
}

function location(work,row,requestIndex,paragraphIndex){
  const paragraphs=list(row.paragraphs);
  // null, an empty string and false must never be converted into paragraph zero.
  if(!Number.isInteger(paragraphIndex)||paragraphIndex<0||paragraphIndex>=paragraphs.length){
    return {paragraphIndex:null,blockIndices:[],excerpt:''};
  }
  const mark=`response_${requestIndex}_${paragraphIndex}`;
  const blockIndices=[];
  list(work.blocks).forEach((block,index)=>{
    if(!block||!list(block.request_ids).includes(row.request_id))return;
    const marks=list(block.bookmarks).length?block.bookmarks:[block.bookmark];
    if(marks.includes(mark)&&text(block.text))blockIndices.push(index);
  });
  return {paragraphIndex,blockIndices,
    excerpt:blockIndices.map(index=>text(work.blocks[index].text)).join('\n\n')};
}

/** Pure projection of the saved review. It neither resolves findings nor approves text. */
export function deriveDraftReview(work={},identified=[]){
  const savedRows=list(work?.requests),items=[],identities=new Map();
  const savedIds=new Set(savedRows.map(row=>row.request_id));
  const missing=list(identified).flatMap((request,index)=>request?.id&&!savedIds.has(request.id)
    ?[{request_id:request.id,label:requestLabel(request.label,index),title:request.title,paragraphs:[]}]
    :[]);
  const rows=[...savedRows,...missing];
  let checking=0,awaitingCheck=0,unprepared=0,ready=0,written=0;
  rows.forEach((row,requestIndex)=>{
    const requestId=text(row.request_id),label=requestLabel(row.label,requestIndex);
    const paragraphs=list(row.paragraphs);
    const hasResponse=paragraphs.some(paragraph=>text(paragraph?.text)
      &&(!paragraph.office_section||paragraph.office_section==='response'));
    const hasText=hasResponse&&paragraphs.every(paragraph=>text(paragraph?.text));
    if(hasResponse)written++;
    const gaps=row.stale||row.status==='stale'?[]:[...new Set(list(row.pending)
      .filter(item=>item?.blocks_approval!==false&&!['resolved','not_applicable'].includes(item?.resolution?.action))
      .map(item=>text(item?.description)).filter(Boolean))];
    const add=(kind,title,description,issue={},needs=[])=>{
      const position=location(work,row,requestIndex,issue.paragraph_index);
      const identity=JSON.stringify([requestId||`missing-${requestIndex}`,kind,text(issue.code),description,position.paragraphIndex]);
      const count=(identities.get(identity)||0)+1;identities.set(identity,count);
      items.push({id:`adjustment-${fingerprint(identity)}-${count}`,requestId,requestLabel:label,
        requestTitle:text(row.title),title,description,needs,...position,kind,...(text(issue.severity)?{severity:text(issue.severity)}:{})});
    };
    if(!hasText){
      unprepared++;
      add('unprepared',hasResponse?'Respuesta por completar':'Sin respuesta',
        gaps.length?'Revisa estos faltantes en Redacción para completar la respuesta.'
          :hasResponse?'Completa el texto de la respuesta en Redacción.'
          :'Prepara la respuesta en Redacción y verifica los respaldos disponibles.',{},gaps);
    }
    if(row.stale||row.status==='stale'){
      add('stale','Respuesta desactualizada',text(row.error)||'Las fuentes o la solicitud cambiaron. Actualiza esta respuesta en Redacción; el texto se conserva.');
      return;
    }
    if(hasText&&gaps.length)add('evidence','Respuesta con faltantes','Revisa estos faltantes en Redacción para completar la respuesta.',{},gaps);
    if(row.status==='checking'){checking++;return;}
    if(!hasText)return;
    const issues=list(row.assessment?.issues).filter(issue=>issue&&text(issue.description));
    if(issues.length){
      for(const issue of issues.filter(issue=>!gaps.includes(text(issue.description)))){
        const description=text(issue.description);
        add('issue',shortTitle(description),description,issue);
      }
      return;
    }
    if(finished.has(row.status)){if(!gaps.length)ready++;return;}
    if(row.status==='error'){
      add('error','No se pudo completar la comprobación',text(row.error)||'Guarda de nuevo para reintentar la comprobación de esta respuesta.');
    }else if(row.status==='needs_evidence'){
      if(!gaps.length)add('evidence','Respaldo pendiente de revisar','Revisa los respaldos y los pendientes de esta respuesta en Redacción.');
    }else if(row.status==='needs_changes'){
      add('issue','Esta respuesta necesita un ajuste','La comprobación solicita cambios, pero no indica un fragmento concreto. Revisa la respuesta en Redacción.');
    }else if(!gaps.length){
      awaitingCheck++;
    }
  });
  const priority={unprepared:0,evidence:1};
  items.sort((a,b)=>(priority[a.kind]??2)-(priority[b.kind]??2));
  return {items,checking,awaitingCheck,unprepared,ready,written,total:rows.length,
    canGenerate:rows.length>0&&ready===rows.length&&items.length===0&&checking===0};
}

function reviewOverview(review,{dirty,total,generated}){
  const expected=Math.max(total,review.total),unanswered=expected-review.written;
  let title='Documento por completar',detail='',tone='is-unprepared';
  if(dirty){
    detail='Hay cambios sin guardar. Guarda para comprobar la versión actual.';
    tone='is-dirty';
  }else if(review.checking){
    detail=`Comprobando ${review.checking} ${review.checking===1?'respuesta':'respuestas'}…`;
    tone='is-checking';
  }else if(review.canGenerate&&review.ready===expected){
    title=generated?'Oficio generado':'Documento listo para revisión final';
    detail=generated?'El oficio revisado y sus archivos están guardados.':'El contenido guardado pasó las comprobaciones. Falta la aprobación final.';
    tone='is-ready';
  }else if(!review.written){
    detail='Todavía no hay respuestas preparadas. Vuelve a Redacción para preparar el borrador.';
  }else if(unanswered){
    detail='Empieza por completar las peticiones sin respuesta en Redacción.';
  }else if(review.unprepared){
    detail='Completa el texto pendiente y revisa los ajustes.';
  }else if(!review.items.length&&review.awaitingCheck){
    title='Sin ajustes pendientes';
    detail=review.awaitingCheck===1?'Queda por comprobar 1 respuesta redactada.'
      :`Quedan por comprobar ${review.awaitingCheck} respuestas redactadas.`;
  }else{
    detail='Las respuestas están redactadas. Revisa los faltantes y las comprobaciones pendientes.';
  }
  return `<div class="draft-review-overview draft-review-empty ${tone}" role="status" aria-atomic="true">
    <h3>${title}</h3>
    ${expected?`<p>${review.written} de ${expected} con respuesta redactada · ${review.ready} ${review.ready===1?'comprobada':'comprobadas'}${unanswered?` · ${unanswered} sin respuesta`:''}</p>`:''}
    <p>${detail}</p>
  </div>`;
}

/** Markup only; the document controller owns navigation, saving and highlighting. */
export function draftReviewMarkup(review,{selectedId,dirty=false,busy=false,total=0,generated=false}={}){
  const items=list(review?.items),value={...review,items};
  const selected=Math.max(0,items.findIndex(item=>item.id===selectedId));
  return `<section class="draft-adjustments" aria-label="Ajustes del borrador">
    ${reviewOverview(value,{dirty,total,generated})}
    ${items.length?`<div class="draft-adjustment-summary"><h3>Peticiones y ajustes pendientes</h3><span class="draft-adjustment-count" aria-label="${items.length} ${items.length===1?'ajuste pendiente':'ajustes pendientes'}">${items.length}</span></div>
    <ol class="draft-adjustment-list">${items.map((item,index)=>{
      const active=index===selected,located=Number.isInteger(item.paragraphIndex)&&item.blockIndices.length>0;
      const action=item.needs.length||item.kind==='evidence'?'Revisar faltantes'
        :item.kind==='unprepared'?'Preparar respuesta':item.kind==='stale'?'Actualizar respuesta':'Revisar ajuste';
      const sameExplanation=item.title===shortTitle(item.description);
      const heading=active&&sameExplanation?item.description:item.title;
      const excerpt=shorten(text(item.excerpt).replace(/\s+/g,' '),180);
      return `<li class="draft-review-item${active?' is-active':''} kind-${esc(item.kind)}">
        <button type="button" class="draft-adjustment-toggle" data-select-adjustment="${esc(item.id)}" aria-expanded="${active}" aria-controls="${esc(item.id)}-detail"${busy?' disabled':''}>
          <span class="draft-adjustment-number" aria-hidden="true">${index+1}</span>
          <span class="draft-adjustment-copy"><span>${esc(item.requestLabel)}</span><strong>${esc(heading)}</strong>
            ${item.requestTitle&&item.requestTitle!==item.requestLabel?`<small>${esc(item.requestTitle)}</small>`:''}</span>
          <span class="draft-adjustment-chevron" aria-hidden="true">${icon('chevron-down')}</span>
        </button>
        <div class="draft-adjustment-body" id="${esc(item.id)}-detail"${active?'':' hidden'}>
          ${sameExplanation||item.needs.length?'':`<p class="draft-adjustment-description">${esc(item.description)}</p>`}
          ${item.needs.length?`<p class="draft-adjustment-needs-label">Qué hace falta</p>
            <ul class="draft-adjustment-needs">${item.needs.map(need=>`<li>${esc(need)}</li>`).join('')}</ul>`:''}
          ${located?`<p class="draft-adjustment-location">Párrafo ${item.paragraphIndex+1}</p><blockquote class="draft-adjustment-excerpt">${esc(excerpt)}</blockquote>`
            :item.kind==='issue'?'<p class="draft-adjustment-location">Revisión de la respuesta completa</p>':''}
          <div class="draft-adjustment-actions">
            <button type="button" class="primary" data-review-adjustment="${esc(item.id)}"${busy?' disabled':''}>${action}</button>
            ${located?`<button type="button" class="text-button" data-view-fragment="${esc(item.id)}"${busy||dirty?' disabled':''}>Ver fragmento</button>`:''}
          </div>
        </div>
      </li>`;
    }).join('')}</ol>
    ${items.length>1?`<nav class="draft-adjustment-nav" aria-label="Recorrer ajustes">
      <button type="button" data-adjustment-prev${busy||selected===0?' disabled':''}>${icon('arrow-left')} Anterior</button>
      <span>${selected+1} de ${items.length}</span>
      <button type="button" data-adjustment-next${busy||selected===items.length-1?' disabled':''}>Siguiente ${icon('arrow-right')}</button>
    </nav>`:''}`:''}
  </section>`;
}
