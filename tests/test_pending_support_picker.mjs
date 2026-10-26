import test from 'node:test';
import assert from 'node:assert/strict';
import {supportOptions,supportPicker,bindSupportPicker} from '../src/pqrs_claro/static/recorrido/pending-supports.js';

const options=Array.from({length:7},(_,i)=>({value:`source:${i}`,label:`Documento ${i+1}`,
  text:i===5?'Matrícula del semestre 2026':'Información académica de ejemplo.',
  location:`Página ${i+1} · líneas 1–3`,hint:'Otro pasaje disponible',url:`/original/${i}`}));

test('muestra tres respaldos, nunca selecciona uno y conserva todo el contenido accesible',()=>{
  const html=supportPicker(options);
  assert.equal((html.match(/class="pending-support-card"/g)||[]).length,7);
  assert.equal((html.match(/data-support-text="[^"]*" hidden/g)||[]).length,4);
  assert.equal((html.match(/name="pending-support"/g)||[]).length,7);
  assert.doesNotMatch(html,/\bchecked\b/);
  assert.match(html,/Ver más respaldos \(4\)/);
  assert.match(html,/son candidatos/);
  assert.match(html,/aria-live="polite"/);
});

test('escapa títulos y citas; un extracto largo permite consultar el texto íntegro',()=>{
  const text='<script>contenido</script> '+ 'Texto original completo. '.repeat(30);
  const html=supportPicker([{...options[0],label:'<img onerror="alert(1)">',text}]);
  assert.doesNotMatch(html,/<script>|<img /);
  assert.match(html,/&lt;script&gt;contenido&lt;\/script&gt;/);
  assert.match(html,/Leer fragmento completo/);
  assert.match(html,/Texto original completo\. <\/blockquote>/);
  assert.doesNotMatch(html,/data-support-search/);
});

test('no inventa páginas y diferencia las secciones de un documento',()=>{
  const available_supports=[
    {chunk_id:'A',source_id:'s',title:'Documento',quote:'Texto',location_kind:'section',page:2},
    {chunk_id:'B',source_id:'s',filename:'sin-pagina.txt',quote:'Texto'},
  ];
  const rows=supportOptions({case_id:'case',available_supports},{description:'Texto'});
  assert.equal(rows[0].location,'Sección 2');
  assert.doesNotMatch(rows[0].url,/#page=/);
  assert.equal(rows[1].location,'Ubicación no indicada');
  assert.equal(rows[1].label,'sin-pagina.txt');
  assert.doesNotMatch(rows[1].url,/#page=/);
});

function boundPicker(){
  const blank=()=>({hidden:false,textContent:'',value:'',focused:false,
    focus(){this.focused=true;},classList:{toggle(){}}});
  const cards=options.map(o=>{
    const input={...blank(),checked:false,required:false};
    return {...blank(),input,dataset:{supportText:(o.label+' '+o.text).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase()},
      querySelector:()=>input};
  });
  const nodes=Object.fromEntries(['search','clear','more','results','selection','empty','filter-note'].map(key=>[key,blank()]));
  const list=blank();
  const picker={
    querySelectorAll:()=>cards,
    querySelector:selector=>selector==='.pending-support-list'?list:nodes[selector.slice('[data-support-'.length,-1)],
  };
  bindSupportPicker({querySelectorAll:()=>[picker]});
  return {picker,cards,nodes,list};
}

test('el filtro encuentra respaldos fuera de los tres iniciales y no selecciona',()=>{
  const {cards,nodes}=boundPicker();
  assert.equal(cards.filter(c=>!c.hidden).length,3);
  nodes.search.value='matricula 2026';nodes.search.oninput();
  assert.deepEqual(cards.filter(c=>!c.hidden).map(c=>cards.indexOf(c)),[5]);
  assert.equal(nodes.results.textContent,'1 de 1 coincidencia');
  assert.ok(cards.every(c=>!c.input.checked));
  assert.equal(cards[5].input.required,true);
  assert.ok(cards.filter(c=>c.hidden).every(c=>!c.input.required));
});

test('ver más revela tres y dirige el foco sin confirmar ninguno',()=>{
  const {cards,nodes}=boundPicker();
  nodes.more.onclick();
  assert.equal(cards.filter(c=>!c.hidden).length,6);
  assert.equal(cards[3].input.focused,true);
  assert.ok(cards.every(c=>!c.input.checked));
  assert.equal(nodes.more.textContent,'Ver más respaldos (1)');
});

test('el filtro conserva y comunica la selección aunque quede oculta',()=>{
  const {cards,nodes,picker,list}=boundPicker();
  nodes.search.value='matricula';nodes.search.oninput();
  cards[5].input.checked=true;picker.onchange();
  assert.equal(nodes.selection.textContent,'1 respaldo seleccionado');
  nodes.search.value='sin coincidencias';nodes.search.oninput();
  assert.equal(nodes.empty.hidden,false);
  assert.equal(list.hidden,true);
  assert.equal(nodes['filter-note'].hidden,false);
  assert.match(nodes['filter-note'].textContent,/fuera del filtro/);
  assert.equal(cards[5].input.checked,true);
  nodes.clear.onclick();
  assert.equal(nodes.search.focused,true);
  assert.equal(nodes.empty.hidden,true);
  assert.equal(cards[5].input.checked,true);
  nodes.more.onclick();
  assert.equal(cards[5].hidden,false);
  assert.equal(nodes['filter-note'].hidden,true);
});

test('sin respaldos explica cómo incorporar evidencia sin ofrecer una aprobación',()=>{
  const html=supportPicker([]);
  assert.match(html,/No hay respaldos disponibles/);
  assert.match(html,/Agregar evidencia/);
  assert.doesNotMatch(html,/<input|checked/);
});
