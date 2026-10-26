import {esc} from './views.js';

const clean=text=>String(text||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
const ignored=new Set('para como esta este sobre documento fuente pagina version solicitud confirmar contrastar transcripcion original previstas fechas correspondiente convocatoria'.split(' '));
const words=text=>[...new Set(clean(text).match(/[a-z]{4,}/g)||[])].filter(w=>!ignored.has(w));

function dateContext(description,quote){
  if(!/\b(fechas?|calendario|cuando)\b/.test(clean(description)))return null;
  const terms=words(description).filter(w=>!['presentacion','solicita','informar','periodo'].includes(w));
  const text=clean(quote);let best=null;
  const dates=text.matchAll(/\b\d{1,2}\s+(?:y\s+\d{1,2}\s+)?de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\b|\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}\b/g);
  for(const date of dates){
    const start=Math.max(0,date.index-150),end=date.index+date[0].length+150;
    for(const word of text.slice(start,end).matchAll(/[a-z]{4,}/g)){
      if(!terms.some(term=>term===word[0]))continue;
      const wordStart=start+word.index,wordEnd=wordStart+word[0].length,dateEnd=date.index+date[0].length;
      const gap=wordEnd<=date.index?text.slice(wordEnd,date.index):wordStart>=dateEnd?text.slice(dateEnd,wordStart):'';
      const distance=gap.replace(/\s+/g,' ').trim().length;
      if(!best||distance<best.distance)best={distance,start:Math.max(0,date.index-100),end:Math.min(quote.length,date.index+date[0].length+120)};
    }
  }
  return best;
}

export function supportOptions(row,p){
  const terms=words(p.description),linked=new Set(p.linked_chunk_ids||[]);
  const exact=['transcription','provenance','issued_version'].includes(p.reason_code);
  const unique=new Map();
  for(const s of row.available_supports||[]){
    if(unique.has(s.chunk_id))continue;
    const text=clean(s.quote),matches=terms.filter(w=>text.includes(w));
    const dated=!exact?dateContext(p.description,s.quote):null;
    const overlap=matches.length/Math.max(1,terms.length);
    const score=dated?3+1/(1+dated.distance)+.005*overlap:overlap;
    const page=Number(s.page),hasPage=Number.isInteger(page)&&page>0;
    const lines=Number.isInteger(s.line_start)&&Number.isInteger(s.line_end)&&s.line_end>=s.line_start?` · líneas ${s.line_start}–${s.line_end}`:'';
    unique.set(s.chunk_id,{value:'source:'+s.chunk_id,text:s.quote,label:s.title||s.filename||'Documento sin título',
      location:(hasPage?`${s.location_kind==='section'?'Sección':'Página'} ${page}`:'Ubicación no indicada')+lines,
      url:`/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${encodeURIComponent(row.case_id)}${hasPage&&s.location_kind!=='section'?'#page='+page:''}`,
      excerpt:dated?s.quote.slice(dated.start,dated.end):null,
      priority:exact&&linked.has(s.chunk_id)?2:score,
      hint:exact&&linked.has(s.chunk_id)?'Pasaje señalado en este punto':dated?'Contiene una fecha cerca del tema consultado':matches.length?'Coincide con: '+matches.slice(0,3).join(', '):'Otro pasaje disponible'});
  }
  if(p.kind!=='document'&&!row.pre_draft)for(const f of row.facts||[]){
    unique.set('fact:'+f.id,{value:'fact:'+f.id,label:`Aporte de ${f.author}`,text:f.text,
      location:f.observed_at,hint:'Información aportada',priority:0,url:null});
  }
  return [...unique.values()].sort((a,b)=>b.priority-a.priority);
}

export function supportPicker(options){
  if(!options.length)return '<div class="pending-support-empty" role="status"><strong>No hay respaldos disponibles para elegir</strong><p>Usa «Agregar evidencia» para incorporar un documento. Después podrás revisar su contenido y seleccionarlo aquí.</p></div>';
  const card=(o,i)=>{
    const text=String(o.text||''),sample=String(o.excerpt||text);
    const shortened=sample.length>480;
    const preview=shortened?sample.slice(0,480).replace(/\s+\S*$/,'')+'…':sample;
    const fullText=shortened||Boolean(o.excerpt&&o.excerpt!==text);
    return `<article class="pending-support-card" data-support-text="${esc(clean(o.label+' '+o.location+' '+text))}"${i>=3?' hidden':''}><label class="pending-support-choice"><input type="radio" name="pending-support" value="${esc(o.value)}"${i<3?' required':''}><span><strong>${esc(o.label)}</strong><small>${esc(o.location)}</small></span><span class="pending-support-selected" aria-hidden="true">Seleccionado</span></label><p class="pending-support-hint">${esc(o.hint)}</p><blockquote>${esc(preview||'Este respaldo no contiene un fragmento de texto disponible.')}</blockquote>${fullText?`<details class="pending-support-full"><summary>Leer fragmento completo</summary><blockquote>${esc(text)}</blockquote></details>`:''}${o.url?`<a class="pending-support-original" href="${esc(o.url)}" target="_blank" rel="noopener">Ver documento original ↗</a>`:''}</article>`;
  };
  return `<fieldset class="pending-support-picker"><legend>Elige el respaldo que revisaste</legend><p class="pending-support-intro">Estos fragmentos son candidatos. Selecciona uno solo si su contenido respalda este punto.</p>${options.length>1?'<div class="pending-support-filter"><label>Filtrar respaldos<input type="search" data-support-search placeholder="Documento, palabra o fecha" autocomplete="off"></label><button type="button" data-support-clear hidden>Limpiar filtro</button></div>':''}<div class="pending-support-status" role="status" aria-live="polite" aria-atomic="true"><span data-support-results>${Math.min(3,options.length)} de ${options.length} ${options.length===1?'respaldo':'respaldos'}</span><span data-support-selection>Sin seleccionar</span></div><p class="pending-support-filter-note" data-support-filter-note hidden></p><div class="pending-support-list" role="group" aria-label="Fragmentos disponibles como respaldo" tabindex="0">${options.map(card).join('')}</div><button type="button" class="pending-support-more" data-support-more${options.length<=3?' hidden':''}>Ver más respaldos (${Math.max(0,options.length-3)})</button><div class="pending-support-empty" data-support-empty hidden><strong>No hay coincidencias con este filtro</strong><p>Prueba con otra palabra o limpia el filtro para ver todos los respaldos.</p></div></fieldset>`;
}

export function bindSupportPicker(form){
  for(const picker of form.querySelectorAll('.pending-support-picker')){
    const search=picker.querySelector('[data-support-search]');
    const clear=picker.querySelector('[data-support-clear]');
    const more=picker.querySelector('[data-support-more]');
    const cards=[...picker.querySelectorAll('.pending-support-card')];
    let shown=3;
    const refresh=()=>{
      const query=clean(search?.value).trim(),terms=query.split(/\s+/).filter(Boolean);
      let count=0,selected=false,selectedHidden=false,selectedFiltered=false;
      for(const card of cards){
        const input=card.querySelector('input[name="pending-support"]');
        const matches=terms.every(term=>card.dataset.supportText.includes(term));
        if(matches)count++;
        card.hidden=!matches||count>shown;
        // The controller still requires a valid selected option. Avoid native
        // validation trying to focus an invisible radio when a filter has no hits.
        input.required=!card.hidden;
        if(input.checked){selected=true;selectedHidden=card.hidden;selectedFiltered=!matches;}
      }
      picker.querySelector('[data-support-results]').textContent=query?`${Math.min(shown,count)} de ${count} ${count===1?'coincidencia':'coincidencias'}`:`${Math.min(shown,count)} de ${cards.length} ${cards.length===1?'respaldo':'respaldos'}`;
      picker.querySelector('[data-support-selection]').textContent=selected?'1 respaldo seleccionado':'Sin seleccionar';
      picker.querySelector('[data-support-selection]').classList.toggle('has-selection',selected);
      picker.querySelector('[data-support-empty]').hidden=count>0;
      picker.querySelector('.pending-support-list').hidden=count===0;
      const note=picker.querySelector('[data-support-filter-note]');
      note.hidden=!selectedHidden;
      note.textContent=selectedFiltered?'El respaldo seleccionado está fuera del filtro. Limpia el filtro para volver a verlo.':'Tu selección se conserva. Usa «Ver más respaldos» para volver a verla.';
      more.hidden=count<=shown;
      more.textContent=`Ver más respaldos (${Math.max(0,count-shown)})`;
      if(clear)clear.hidden=!query;
    };
    if(search)search.oninput=()=>{shown=3;refresh();};
    if(clear)clear.onclick=()=>{search.value='';shown=3;refresh();search.focus();};
    more.onclick=()=>{const firstNew=shown;shown+=3;refresh();cards.filter(card=>!card.hidden)[firstNew]?.querySelector('input').focus();};
    picker.onchange=refresh;
    refresh();
  }
}
