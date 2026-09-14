// Herramientas de texto: el contenido sigue usando el contrato del oficio.
const copy=v=>structuredClone(v);
const button=(action,label,icon)=>`<button type="button" data-tool="${action}" title="${label}" aria-label="${label}">${icon?`<span aria-hidden="true">${icon}</span>`:''}<span>${label}</span></button>`;
export const toolsMarkup=()=>`<div class="document-tools" role="region" aria-label="Herramientas del documento">
  <div class="tool-group">${button('undo','Deshacer','↶')}${button('redo','Rehacer','↷')}${button('save','Guardar','✓')}</div>
  <div class="tool-group">${button('find','Buscar y reemplazar','⌕')}${button('add','Añadir párrafo','+')}${button('remove','Quitar párrafo','−')}</div>
  <div class="tool-group tool-view"><button type="button" data-tool="out" aria-label="Reducir zoom" title="Reducir zoom">−</button><label class="zoom-control"><span class="tool-sr">Zoom del documento</span><select data-zoom><option value="fit">Ajustar al ancho</option>${[50,75,90,100,110,125,150,175,200].map(n=>`<option value="${n}">${n}%</option>`).join('')}</select></label><button type="button" data-tool="in" aria-label="Aumentar zoom" title="Aumentar zoom">+</button>${button('full','Pantalla completa','⛶')}</div>
  <div class="document-find" hidden><label>Buscar en el texto editable<input type="search" data-find autocomplete="off"></label><label>Reemplazar por<input data-replacement autocomplete="off"></label><div class="find-actions">${button('previous','Anterior','↑')}${button('next','Siguiente','↓')}${button('replace','Reemplazar')}${button('all','Reemplazar todos')}${button('close-find','Cerrar búsqueda','×')}</div><span data-find-count role="status"></span></div>
  </div><div class="document-tool-status"><span data-word-count></span><span data-selection-label>Selecciona un párrafo para editarlo</span><details><summary>Atajos</summary><p>Ctrl + Z: deshacer · Ctrl + Y: rehacer · Ctrl + F: buscar · Ctrl + S: guardar. En Mac, usa ⌘. El zoom cambia solo la vista.</p></details></div>`;

export function createDocumentTools(s,{renderSheet,changed,updateText,paragraph,save}){
  const root=s.node,stage=root.querySelector('.document-stage'),canvas=root.querySelector('.document-canvas');
  const history=s.editHistory??={past:[],future:[]};
  let selected=null,lastInput=0,lastTarget=null,matchIndex=-1,matches=[];
  let previousOverflow='';
  function expand(enabled){
    if(enabled)previousOverflow=document.body.style.overflow;
    document.body.style.overflow=enabled?'hidden':previousOverflow;
    stage.classList.toggle('document-expanded',enabled);
    const button=root.querySelector('[data-tool="full"]'),label=enabled?'Salir de pantalla completa':'Pantalla completa';
    button.setAttribute('aria-pressed',String(enabled));button.setAttribute('aria-label',label);button.title=label;button.lastElementChild.textContent=label;
    applyZoom();
  }
  const snapshot=()=>copy({metadata:s.work.metadata,blocks:s.work.blocks,paragraphs:s.work.requests.map(r=>r.paragraphs),attachments:s.work.attachment_source_ids});
  function record(target=null){
    const now=Date.now();
    if(!target||target!==lastTarget||now-lastInput>700){history.past.push(snapshot());if(history.past.length>80)history.past.shift();}
    lastInput=now;lastTarget=target;history.future=[];
  }
  function restore(value){
    Object.assign(s.work,{metadata:copy(value.metadata),blocks:copy(value.blocks),attachment_source_ids:copy(value.attachments)});
    s.work.requests.forEach((r,i)=>r.paragraphs=copy(value.paragraphs[i]));
    root.querySelectorAll('[data-meta]').forEach(e=>e.value=s.work.metadata[e.dataset.meta]||'');
    root.querySelectorAll('[data-attachment]').forEach(e=>e.checked=s.work.attachment_source_ids.includes(e.dataset.attachment));
    renderSheet();changed();refresh();
  }
  function travel(redo){
    const from=redo?history.future:history.past,to=redo?history.past:history.future;
    if(s.busy||!from.length)return;to.push(snapshot());restore(from.pop());lastTarget=null;
    const el=root.querySelector(`[data-block="${selected}"]`);
    if(el){el.focus();const range=document.createRange();range.selectNodeContents(el);range.collapse(false);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);}
  }
  const editables=()=>[...root.querySelectorAll('[data-block]')];
  function refresh(){
    const text=root.querySelector('.oficio-sheet').innerText.trim();
    root.querySelector('[data-word-count]').textContent=`${text?text.split(/\s+/u).length:0} palabras · ${text.length.toLocaleString('es-CO')} caracteres`;
    root.querySelector('[data-tool="undo"]').disabled=s.busy||!history.past.length;
    root.querySelector('[data-tool="redo"]').disabled=s.busy||!history.future.length;
    root.querySelector('[data-tool="save"]').disabled=s.busy||s.work.requests.some(r=>r.status==='checking');
    const block=s.work.blocks[selected],marks=block?.bookmarks||[],single=marks.length===1;
    const [,ri,pi]=single?marks[0].split('_').map((v,i)=>i?Number(v):v):[];
    const row=s.work.requests[ri],p=row?.paragraphs[pi];
    root.querySelector('[data-tool="add"]').disabled=s.busy||!p||row.paragraphs.length>=30;
    root.querySelector('[data-tool="remove"]').disabled=s.busy||!p||row.paragraphs.length<=1||row.paragraphs.filter(x=>x.office_section==='response').length===1&&p.office_section==='response';
    root.querySelectorAll('[data-tool="replace"],[data-tool="all"]').forEach(e=>e.disabled=s.busy);
    root.querySelector('[data-selection-label]').textContent=block?block.request_ids?.length?`Respuesta · ${block.request_ids.join(', ')}`:'Datos del oficio':'Selecciona un párrafo para editarlo';
  }
  function bindSheet(){
    editables().forEach(e=>{
      e.addEventListener('focus',()=>{selected=Number(e.dataset.block);refresh();});
      e.addEventListener('beforeinput',event=>{
        if(event.inputType==='historyUndo'||event.inputType==='historyRedo'){event.preventDefault();travel(event.inputType==='historyRedo');}
        else record(e.dataset.block);
      });
    });
    applyZoom();refresh();
  }
  function applyZoom(){
    const picker=root.querySelector('[data-zoom]');
    if(s.zoomMode&&![...picker.options].some(o=>o.value===s.zoomMode))picker.add(new Option(`${s.zoomMode}%`,s.zoomMode));
    picker.value=s.zoomMode||'fit';
    const width=Math.max(150,canvas.clientWidth-36);
    const zoom=s.zoomMode&&s.zoomMode!=='fit'?Number(s.zoomMode)/100:Math.min(1.25,width/816);
    root.querySelector('.oficio-sheet').style.zoom=zoom;
    picker.title=`Zoom actual: ${Math.round(zoom*100)}%`;
    s.zoom=zoom;
  }
  function scan(){
    const needle=root.querySelector('[data-find]').value.toLocaleLowerCase('es');matches=[];
    if(needle)for(const el of editables()){
      const text=el.innerText.toLocaleLowerCase('es');let at=0;
      while((at=text.indexOf(needle,at))!==-1){matches.push({block:Number(el.dataset.block),at,length:needle.length});at+=needle.length;}
    }
    root.querySelector('[data-find-count]').textContent=needle?`${matches.length} coincidencias en el texto editable`:'';
    return matches;
  }
  function showMatch(direction=1){
    scan();if(!matches.length)return;
    matchIndex=(matchIndex+direction+matches.length)%matches.length;
    const match=matches[matchIndex],el=root.querySelector(`[data-block="${match.block}"]`);
    editables().forEach(e=>e.classList.toggle('search-current',e===el));
    selected=match.block;el.scrollIntoView({block:'center',inline:'nearest'});
    // Texto plano renderizado: seleccionar la coincidencia sin insertar HTML.
    if(el.childNodes.length===1&&el.firstChild.nodeType===Node.TEXT_NODE){
      const range=document.createRange();range.setStart(el.firstChild,match.at);range.setEnd(el.firstChild,match.at+match.length);
      const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
    }
    root.querySelector('[data-find-count]').textContent=`${matchIndex+1} de ${matches.length} coincidencias`;refresh();
  }
  function replace(all){
    if(s.busy)return;scan();if(!matches.length)return;
    record();const replacement=root.querySelector('[data-replacement]').value;
    const chosen=all?matches:[matches[Math.max(0,Math.min(matchIndex,matches.length-1))]];
    for(const index of new Set(chosen.map(m=>m.block))){
      let text=root.querySelector(`[data-block="${index}"]`).innerText;
      for(const m of chosen.filter(m=>m.block===index).reverse())text=text.slice(0,m.at)+replacement+text.slice(m.at+m.length);
      updateText(index,text);
    }
    renderSheet();changed();matchIndex=-1;scan();refresh();
  }
  root.querySelector('[data-find]').oninput=()=>{matchIndex=-1;scan();};
  root.querySelector('[data-find]').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();showMatch(e.shiftKey?-1:1);}};
  root.querySelector('[data-zoom]').onchange=e=>{s.zoomMode=e.target.value;applyZoom();};
  root.querySelectorAll('[data-tool]').forEach(button=>button.onclick=async()=>{
    const action=button.dataset.tool;
    if(action==='undo'||action==='redo')travel(action==='redo');
    else if(action==='save')save();
    else if(action==='find'){root.querySelector('.document-find').hidden=false;root.querySelector('[data-find]').focus();}
    else if(action==='close-find'){root.querySelector('.document-find').hidden=true;editables().forEach(e=>e.classList.remove('search-current'));root.querySelector('[data-tool="find"]').focus();}
    else if(action==='next'||action==='previous')showMatch(action==='next'?1:-1);
    else if(action==='replace'||action==='all')replace(action==='all');
    else if(action==='in'||action==='out'){
      const zoom=Math.min(200,Math.max(50,Math.round(s.zoom*100/10)*10+(action==='in'?10:-10)));
      const select=root.querySelector('[data-zoom]');if(![...select.options].some(o=>o.value===String(zoom)))select.add(new Option(`${zoom}%`,zoom));
      s.zoomMode=String(zoom);applyZoom();
    }else if(action==='full'){
      expand(!stage.classList.contains('document-expanded'));
    }else if((action==='add'||action==='remove')&&!s.busy){record();selected=paragraph(selected,action);renderSheet();changed();refresh();root.querySelector(`[data-block="${selected}"]`)?.focus();}
  });
  root.onkeydown=e=>{
    if(e.key==='Escape'&&stage.classList.contains('document-expanded')){expand(false);root.querySelector('[data-tool="full"]').focus();}
    if(e.key==='Tab'&&stage.classList.contains('document-expanded')){
      const items=[...stage.querySelectorAll('button:not(:disabled),input:not(:disabled),select,[tabindex="0"],[contenteditable="plaintext-only"]')].filter(el=>el.getClientRects().length);
      const first=items[0],last=items.at(-1);
      if(e.shiftKey&&e.target===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&e.target===last){e.preventDefault();first.focus();}
    }
    if(!(e.ctrlKey||e.metaKey)||e.altKey)return;
    const key=e.key.toLowerCase(),inText=e.target.closest('[data-block]');
    if(key==='s'){e.preventDefault();save();}
    else if(key==='f'){e.preventDefault();root.querySelector('[data-tool="find"]').click();}
    else if(inText&&(key==='z'||key==='y')){e.preventDefault();travel(key==='y'||e.shiftKey);}
  };
  const observer=new ResizeObserver(applyZoom);observer.observe(canvas);
  const fullChange=()=>{const full=document.fullscreenElement===stage;root.querySelector('[data-tool="full"]').setAttribute('aria-pressed',String(full));applyZoom();};
  document.addEventListener('fullscreenchange',fullChange);
  bindSheet();
  return {record,refresh,bindSheet,destroy(){if(stage.classList.contains('document-expanded'))expand(false);observer.disconnect();document.removeEventListener('fullscreenchange',fullChange);}};
}
