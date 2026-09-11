export function originalViewer(data,state,esc){
  const pages=data.original_pages || [];
  const selected=Number.isInteger(state.originalSelection)?data.requests[state.originalSelection]:null;
  const page=pages.find(p=>p.number===(state.originalPage||1)) || pages[0];
  const marks=selected?.original_marks?.filter(m=>m.page===page?.number) || [];
  const label=selected?`Solicitud ${selected.label} · ${selected.title}`:'Selecciona «Ver de dónde salió» en una solicitud para resaltar su origen.';
  return `<section id="original-pane" class="original-viewer" aria-labelledby="original-title"><div class="original-head"><h2 id="original-title" tabindex="-1">Documento original</h2><a href="${esc(data.original_url||'files/Peticion_academica_demo.pdf')}" target="_blank" rel="noopener">Abrir PDF ↗</a></div>
    <div class="original-tools"><label>Página <select id="original-page" aria-label="Página del documento original">${pages.map(p=>`<option value="${p.number}" ${p.number===page?.number?'selected':''}>${p.number}</option>`).join('')}</select> de ${pages.length}</label>${selected?'<button class="text-button" data-action="clear-original">Quitar resaltado</button>':''}</div>
    <p id="original-selection" class="original-selection" role="status">${esc(label)}</p>
    <div class="original-scroll" tabindex="0" aria-label="Visor de la página original. Puedes desplazarte para leer el documento.">
      ${page?`<div class="original-sheet"><img id="original-image" src="${esc(page.image)}" width="${page.width*2}" height="${page.height*2}" alt="Página ${page.number} del PDF original de la petición"><svg class="original-marks" viewBox="0 0 ${page.width} ${page.height}" aria-hidden="true">${marks.flatMap(m=>m.rectangles.map(r=>`<rect class="quote-mark" x="${r[0]}" y="${r[1]}" width="${r[2]-r[0]}" height="${r[3]-r[1]}"/>`)).join('')}</svg></div>`:'<p>No está disponible la vista de esta página. Puedes abrir el PDF original.</p>'}
    </div>
    ${selected?`<div class="original-quote"><strong>Texto de origen · solicitud ${esc(selected.label)}</strong><p>${esc(marks.map(m=>m.quote).join('\n') || 'El fragmento seleccionado está en otra página.')}</p><button data-action="back-to-question" data-index="${state.originalSelection}" class="text-button">Volver a esta solicitud ↑</button></div>`:'<p class="original-caption">Página original conservada. El resaltado es una ayuda visual; no modifica el PDF.</p>'}
    <details class="original-transcript"><summary>Leer el texto completo de esta página</summary><p>${esc(page?.text || '')}</p></details>
  </section>`;
}

export function focusOriginal(){
  const panel=document.querySelector('.original-viewer');
  const imageViewport=document.querySelector('.original-scroll');
  const viewport=panel&&getComputedStyle(panel).overflowY==='auto'?panel:imageViewport;
  const mark=document.querySelector('.quote-mark');
  if(!panel||!viewport)return;
  panel.scrollIntoView({block:'nearest',behavior:'instant'});
  document.querySelector('#original-title').focus({preventScroll:true});
  viewport.scrollTop=0;
  if(mark){
    const box=mark.getBoundingClientRect(), parent=viewport.getBoundingClientRect();
    viewport.scrollTop+=box.top-parent.top-viewport.clientHeight*.35;
  }
}

export function bindOriginal(state,onPage){
  document.querySelector('#original-page')?.addEventListener('change',e=>onPage(+e.target.value));
  const img=document.querySelector('#original-image');
  const imageError=()=>{
    document.querySelector('.original-sheet').hidden=true;
    const error=document.createElement('p');error.className='alert';error.setAttribute('role','alert');
    error.textContent='No se pudo mostrar la página. Puedes abrir el PDF original y consultar el texto de origen debajo.';
    document.querySelector('.original-scroll').append(error);
  };
  if(img){img.addEventListener('error',imageError,{once:true});if(img.complete&&!img.naturalWidth)imageError();}
}
