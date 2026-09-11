import {esc} from './views.js';

// Advance only from persisted analysis state, never from elapsed time.
export function analysisProgress(current){
  const reading=current.status==='reading';
  const identifying=current.status==='identifying';
  const failed=current.status==='error';
  const readComplete=identifying||(failed&&Boolean(current.pages?.length));
  const rows=[
    ['Original conservado','complete'],
    ['Lectura por página',reading?'current':readComplete?'complete':''],
    ['Identificación con IA',identifying?'current':''],
    ['Tu revisión',''],
  ];
  const title=failed?'El análisis se detuvo':reading?'Leyendo el documento':identifying?'Encontrando las solicitudes':'Documento guardado';
  const description=failed?(current.error||'No se pudo completar el análisis. Puedes volver a intentarlo.'):
    reading?'Estamos extrayendo el texto de cada página y comprobando su calidad.':
    identifying?'La IA está relacionando cada solicitud con su fragmento de origen.':
    'El original está conservado. El siguiente paso es leer sus páginas.';
  return `<div class="analysis-layout" data-analysis-case="${esc(current.id)}"><section class="analysis-progress" aria-labelledby="analysis-title">
    <span class="analysis-badge">${failed?"Análisis detenido":reading||identifying?"Análisis en curso":"PDF recibido"}</span>
    <h1 id="analysis-title">${title}</h1>
    <p class="analysis-filename" title="${esc(current.filename)}">${esc(current.filename)}</p>
    <p class="analysis-description" role="${failed?'alert':'status'}">${esc(description)}</p>
    <ol class="analysis-track" aria-label="Avance del análisis">
      ${rows.map(([label,status],index)=>`<li class="analysis-stage ${status}"${status==='current'?' aria-current="step"':''}>
        <span class="analysis-mark" aria-hidden="true">${status==='complete'?'✓':index+1}</span>
        <span>${label}<span class="analysis-sr">${status==='complete'?', completado':status==='current'?', en curso':', pendiente'}</span></span>
      </li>`).join('')}
    </ol>
    ${failed||current.status==='uploaded'?`<button data-action="live-analyze" class="primary">${failed?'Reintentar análisis':'Continuar análisis'}</button>`:''}
    <p class="analysis-hint">El avance se guarda. Puedes volver a este expediente después.</p>
  </section><section class="analysis-document" aria-labelledby="analysis-document-title">
    <div class="analysis-document-head"><div><h2 id="analysis-document-title">Documento cargado</h2><span>Primera página del original</span></div><a href="/api/cases/${encodeURIComponent(current.id)}/original" target="_blank" rel="noopener">Abrir PDF ↗</a></div>
    <div class="analysis-document-scroll" tabindex="0" role="region" aria-label="Vista previa del documento cargado">
      <img src="/api/cases/${encodeURIComponent(current.id)}/pages/1.png" alt="Primera página de ${esc(current.filename)}">
      <p class="analysis-preview-error" role="status" hidden>No se pudo mostrar la vista previa. Puedes consultar el documento con «Abrir PDF».</p>
    </div>
  </section></div>`;
}

// Polling updates the progress card without reloading or moving the PDF preview.
export function renderAnalysis(container,current){
  const layout=container.querySelector('.analysis-layout');
  const template=document.createElement('template');
  template.innerHTML=analysisProgress(current);
  if(layout?.dataset.analysisCase===current.id){
    layout.querySelector('.analysis-progress').replaceWith(template.content.querySelector('.analysis-progress'));
    return;
  }
  container.replaceChildren(template.content);
  const img=container.querySelector('.analysis-document img');
  const failed=()=>{img.hidden=true;container.querySelector('.analysis-preview-error').hidden=false;};
  img.addEventListener('error',failed,{once:true});
  if(img.complete&&!img.naturalWidth)failed();
}
