import {esc} from './views.js';
import {sourcePassageViewer} from './source-passage-viewer.js';

// Only references saved on the displayed paragraphs establish an actual citation.
export function responseSources(item){
  const citations=new Map(),factIds=new Set();
  if(!item.stale)item.paragraphs.forEach((p,index)=>{
    for(const id of new Set(p.cited_chunk_ids||[])){
      if(!citations.has(id))citations.set(id,[]);
      citations.get(id).push(index+1);
    }
    for(const id of p.cited_fact_ids||[])factIds.add(id);
  });
  const passages=new Map();
  function add(s,key){
    if(s.source_id&&key&&!passages.has(key))passages.set(key,{key,support:s,paragraphs:citations.get(key)||[]});
  }
  // Prefer the saved quotation over longer candidate text from the same chunk.
  for(const s of item.finding?.supports||[]){
    add(s,s.chunk_id||`legacy-${s.source_id}-${s.page}-${passages.size}`);
  }
  if(!item.stale)for(const s of item.row?.available_supports||[]){
    if(citations.has(s.chunk_id))add(s,s.chunk_id);
  }
  const documents=new Map();
  const ordered=[...passages.values()].sort((a,b)=>Number(Boolean(b.paragraphs.length))-Number(Boolean(a.paragraphs.length)));
  for(const entry of ordered){
    const id=entry.support.source_id;
    if(!documents.has(id))documents.set(id,[]);
    documents.get(id).push(entry);
  }
  const facts=(item.row?.facts||[]).filter(f=>factIds.has(f.id));
  const missing=[...citations.keys()].some(id=>!passages.has(id))||facts.length<factIds.size;
  return {documents,passages,facts,missing};
}

function location(s){
  const unit=s.location_kind==='section'?'Sección':'Página';
  const parts=[];
  if(Number(s.page)>0)parts.push(`${unit} ${s.page}`);
  if(s.line_start&&s.line_end)parts.push(s.line_start===s.line_end?`Línea ${s.line_start}`:`Líneas ${s.line_start}–${s.line_end}`);
  if(s.version!=null)parts.push(`Versión ${s.version}`);
  return parts.join(' · ');
}

function documentTitle(s){return s.title||s.filename||'Documento fuente';}

export function responseSourcePanel(caseId,item,selectedKey,sourceNotice){
  const {documents,passages,facts,missing}=item.sources;
  const groups=[...documents.values()];
  const active=passages.get(selectedKey)||groups[0]?.[0];
  const factList=facts.length?`<section class="fiaga-cited-facts"><h3>Aportes citados en la respuesta</h3>${facts.map(f=>`<blockquote>${esc(f.text)}</blockquote><p>${esc(f.author||'')}</p>`).join('')}</section>`:'';
  const warning=missing?'<p class="redaction-inline-note" role="status">Una referencia guardada ya no está disponible para su consulta.</p>':'';
  if(!active){
    const message=item.source.phase==='complete'&&item.paragraphs.length?'Esta respuesta no tiene un documento de respaldo disponible.':sourceNotice;
    return `<section class="redaction-sources"><h3>Fuentes de la respuesta</h3>${warning}<p class="redaction-inline-note" role="${item.source.phase==='error'?'alert':'status'}">${esc(message)}</p>${factList}</section>`;
  }
  const {support,paragraphs}=active,group=documents.get(support.source_id);
  const docPicker=groups.length===1?`<h3 class="fiaga-source-name">${esc(documentTitle(support))}</h3>`:
    `<label class="fiaga-source-picker">Documento fuente<select data-redaction-document data-workflow-focus="source-document">${groups.map(entries=>{
      const first=entries[0],s=first.support;
      return `<option value="${esc(first.key)}"${s.source_id===support.source_id?' selected':''}>${esc(documentTitle(s))} · ${first.paragraphs.length?'Citado':'Consultado'}</option>`;
    }).join('')}</select></label>`;
  const passagePicker=group.length===1?`<p class="redaction-source-location">${esc(location(support))}</p>`:
    `<label class="fiaga-source-picker">Pasaje del documento<select data-redaction-passage data-workflow-focus="source-passage">${group.map((entry,i)=>{
      const place=location(entry.support);
      return `<option value="${esc(entry.key)}"${entry===active?' selected':''}>Pasaje ${i+1}${place?' · '+esc(place):''} · ${entry.paragraphs.length?'Citado':'Consultado'}</option>`;
    }).join('')}</select></label>`;
  const attribution=paragraphs.length
    ?(paragraphs.length===1?'Citado en el párrafo ':'Citado en los párrafos ')+paragraphs.join(', ')+'.'
    :item.paragraphs.length?'Consultado durante la búsqueda. La respuesta no cita este pasaje.':'Pasaje encontrado durante la búsqueda.';
  return `<section class="redaction-sources fiaga-source-panel" aria-label="Fuentes de la petición ${item.index+1}">
    ${docPicker}${passagePicker}<p class="fiaga-source-attribution">${esc(attribution)}</p>
    ${sourcePassageViewer(caseId,support,paragraphs.map(number=>item.paragraphs[number-1].text))}${warning}${factList}
  </section>`;
}
