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
    unique.set(s.chunk_id,{value:'source:'+s.chunk_id,text:s.quote,label:s.title,
      location:`${s.location_kind==='section'?'Sección':'Página'} ${s.page} · líneas ${s.line_start||1}–${s.line_end||1}`,
      url:`/api/sources/${encodeURIComponent(s.source_id)}/original?case_id=${encodeURIComponent(row.case_id)}#page=${Number(s.page)||1}`,
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
  if(!options.length)return '<p>No hay pasajes disponibles. Puedes agregar evidencia para este punto.</p>';
  const best=options[0]?.priority||0;
  const related=options.filter(o=>o.priority>0&&o.priority>=best-.2).slice(0,3);
  const first=related.length?related:options.slice(0,2);
  const other=options.filter(o=>!first.includes(o));
  const card=(o,i)=>`<article class="pending-support-card" data-support-text="${esc(clean(o.label+' '+o.text))}"><label class="pending-support-choice"><input type="radio" name="pending-support" value="${esc(o.value)}" required><span><strong>${esc(o.label)}</strong><small>${esc(o.location)}</small></span></label><p class="pending-support-hint">${esc(o.hint)}</p><blockquote tabindex="0" aria-label="Texto del pasaje ${i+1}">${esc(o.excerpt||o.text)}</blockquote>${o.excerpt?`<details><summary>Ver pasaje completo</summary><blockquote tabindex="0">${esc(o.text)}</blockquote></details>`:''}${o.url?`<a href="${esc(o.url)}" target="_blank" rel="noopener">Abrir original en esta página ↗</a>`:''}</article>`;
  return `<fieldset class="pending-support-picker"><legend>Revisa el texto y selecciona el respaldo</legend><p class="library-note">Son pasajes candidatos. Selecciónalo solo si el texto permite resolver este punto.</p>${first.map(card).join('')}${other.length?`<details class="pending-other-sources"><summary>Ver otras fuentes (${other.length} pasajes)</summary><label class="field">Buscar por documento o contenido<input type="search" id="pending-support-search" placeholder="Palabra, fecha o nombre del documento"></label><div>${other.map(card).join('')}</div><p id="pending-support-empty" hidden>No hay coincidencias.</p></details>`:''}</fieldset>`;
}

export function bindSupportPicker(form){
  const search=form.querySelector('#pending-support-search');
  if(search)search.oninput=()=>{
    const query=clean(search.value).trim();let count=0;
    form.querySelectorAll('.pending-other-sources .pending-support-card').forEach(card=>{
      card.hidden=!card.dataset.supportText.includes(query);if(!card.hidden)count++;
    });
    form.querySelector('#pending-support-empty').hidden=count>0;
  };
}
