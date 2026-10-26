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
export function deriveDraftReview(work={}){
  const rows=list(work?.requests),items=[],identities=new Map();
  let checking=0,unprepared=0,ready=0;
  rows.forEach((row,requestIndex)=>{
    const requestId=text(row.request_id),label=requestLabel(row.label,requestIndex);
    const paragraphs=list(row.paragraphs);
    const hasText=paragraphs.length>0&&paragraphs.every(paragraph=>text(paragraph?.text));
    const add=(kind,title,description,issue={})=>{
      const position=location(work,row,requestIndex,issue.paragraph_index);
      const identity=JSON.stringify([requestId||`missing-${requestIndex}`,kind,text(issue.code),description,position.paragraphIndex]);
      const count=(identities.get(identity)||0)+1;identities.set(identity,count);
      items.push({id:`adjustment-${fingerprint(identity)}-${count}`,requestId,requestLabel:label,
        title,description,...position,kind,...(text(issue.severity)?{severity:text(issue.severity)}:{})});
    };
    if(!hasText){
      unprepared++;
      add('unprepared','Respuesta pendiente de preparar','Prepara esta respuesta en Redacción antes de generar el oficio.');
    }
    if(row.stale||row.status==='stale'){
      add('stale','Respuesta desactualizada',text(row.error)||'Las fuentes o la solicitud cambiaron. Actualiza esta respuesta en Redacción; el texto se conserva.');
      return;
    }
    if(row.status==='checking'){checking++;return;}
    if(!hasText)return;
    const issues=list(row.assessment?.issues).filter(issue=>issue&&text(issue.description));
    if(issues.length){
      for(const issue of issues){
        const description=text(issue.description);
        add('issue',shortTitle(description),description,issue);
      }
      return;
    }
    if(finished.has(row.status)){ready++;return;}
    if(row.status==='error'){
      add('error','No se pudo completar la comprobación',text(row.error)||'Guarda de nuevo para reintentar la comprobación de esta respuesta.');
    }else if(row.status==='needs_evidence'){
      add('issue','Respaldo pendiente de revisar','Revisa los respaldos y los pendientes de esta respuesta en Redacción.');
    }else if(row.status==='needs_changes'){
      add('issue','Esta respuesta necesita un ajuste','La comprobación solicita cambios, pero no indica un fragmento concreto. Revisa la respuesta en Redacción.');
    }else{
      add('unchecked','Comprobación pendiente','Guarda el borrador para comprobar esta respuesta. Guardar todavía no confirma que los ajustes estén resueltos.');
    }
  });
  return {items,checking,unprepared,ready,canGenerate:rows.length>0&&ready===rows.length&&items.length===0&&checking===0};
}

function reviewStatus(review,dirty){
  if(dirty)return '<p class="draft-review-status is-dirty" role="status">Hay cambios sin guardar. La nueva versión aún no está comprobada.</p>';
  if(review.checking)return `<p class="draft-review-status is-checking" role="status"><span class="source-spinner" aria-hidden="true"></span> Comprobando ${review.checking} ${review.checking===1?'respuesta':'respuestas'}… Los ajustes se actualizarán al terminar.</p>`;
  if(review.items.length)return '';
  if(review.canGenerate)return '<p class="draft-review-empty is-ready" role="status">El contenido guardado pasó las comprobaciones. Puedes generar el oficio.</p>';
  return '<p class="draft-review-empty is-unprepared" role="status">Todavía no hay respuestas preparadas. Vuelve a Redacción para preparar el borrador.</p>';
}

/** Markup only; the document controller owns navigation, saving and highlighting. */
export function draftReviewMarkup(review,{selectedId,dirty=false,busy=false}={}){
  const items=list(review?.items),value={...review,items};
  const selected=Math.max(0,items.findIndex(item=>item.id===selectedId));
  return `<section class="draft-adjustments" aria-label="Ajustes del borrador">
    <div class="draft-adjustment-summary"><h3>Ajustes por revisar</h3><span class="draft-adjustment-count" aria-label="${items.length} ${items.length===1?'ajuste pendiente':'ajustes pendientes'}">${items.length}</span></div>
    ${reviewStatus(value,dirty)}
    ${items.length?`<ol class="draft-adjustment-list">${items.map((item,index)=>{
      const active=index===selected,located=Number.isInteger(item.paragraphIndex)&&item.blockIndices.length>0;
      const action=item.kind==='unprepared'?'Preparar respuesta':item.kind==='stale'?'Actualizar respuesta':'Revisar ajuste';
      const sameExplanation=item.title===shortTitle(item.description);
      const heading=active&&sameExplanation?item.description:item.title;
      const excerpt=shorten(text(item.excerpt).replace(/\s+/g,' '),180);
      return `<li class="draft-review-item${active?' is-active':''} kind-${esc(item.kind)}">
        <button type="button" class="draft-adjustment-toggle" data-select-adjustment="${esc(item.id)}" aria-expanded="${active}" aria-controls="${esc(item.id)}-detail"${busy?' disabled':''}>
          <span class="draft-adjustment-number" aria-hidden="true">${index+1}</span>
          <span class="draft-adjustment-copy"><span>${esc(item.requestLabel)}</span><strong>${esc(heading)}</strong></span>
          <span class="draft-adjustment-chevron" aria-hidden="true">${icon('chevron-down')}</span>
        </button>
        <div class="draft-adjustment-body" id="${esc(item.id)}-detail"${active?'':' hidden'}>
          ${sameExplanation?'':`<p class="draft-adjustment-description">${esc(item.description)}</p>`}
          ${located?`<p class="draft-adjustment-location">Párrafo ${item.paragraphIndex+1}</p><blockquote class="draft-adjustment-excerpt">${esc(excerpt)}</blockquote>`:'<p class="draft-adjustment-location">Revisión de la respuesta completa</p>'}
          <div class="draft-adjustment-actions">
            <button type="button" class="primary" data-review-adjustment="${esc(item.id)}"${busy?' disabled':''}>${action}</button>
            ${located?`<button type="button" class="text-button" data-view-fragment="${esc(item.id)}"${busy||dirty?' disabled':''}>Ver fragmento</button>`:''}
          </div>
        </div>
      </li>`;
    }).join('')}</ol>
    <nav class="draft-adjustment-nav" aria-label="Recorrer ajustes">
      <button type="button" data-adjustment-prev${busy||selected===0?' disabled':''}>${icon('arrow-left')} Anterior</button>
      <span>${selected+1} de ${items.length}</span>
      <button type="button" data-adjustment-next${busy||selected===items.length-1?' disabled':''}>Siguiente ${icon('arrow-right')}</button>
    </nav>`:''}
  </section>`;
}
