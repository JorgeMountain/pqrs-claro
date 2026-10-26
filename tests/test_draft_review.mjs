import test from 'node:test';
import assert from 'node:assert/strict';
import {deriveDraftReview,draftReviewMarkup} from '../src/pqrs_claro/static/recorrido/draft-review.js';

const paragraph=text=>({text,cited_chunk_ids:[],cited_fact_ids:[]});
const issue=(description,paragraph_index,code='content')=>({code,description,paragraph_index});
const row=(id,values={})=>({request_id:id,label:`Petición ${id}`,title:`Respuesta ${id}`,
  status:'needs_changes',stale:false,paragraphs:[paragraph('Primer párrafo.'),paragraph('Segundo párrafo.')],
  assessment:{status:'needs_changes',issues:[]},...values});
const block=(ri,pi,id,text,values={})=>({kind:'response',text,
  bookmark:`response_${ri}_${pi}`,bookmarks:[`response_${ri}_${pi}`],request_ids:[id],...values});
function freeze(value){
  if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}
  return value;
}

test('conserva todos los hallazgos, sus identidades y el texto del bloque sin mutar el expediente',()=>{
  const work=freeze({requests:[
    row('A',{assessment:{issues:[issue('Falta precisar el canal.',0),issue('El alcance no coincide.',0)]}}),
    row('B',{assessment:{issues:[{...issue('Revisar la atribución.',1),severity:'warning'}]}}),
  ],blocks:[block(0,0,'A','Texto actual de la primera respuesta.'),block(1,1,'B','Texto actual de la segunda respuesta.')]});
  const review=deriveDraftReview(work);
  assert.equal(review.items.length,3);
  assert.equal(new Set(review.items.map(i=>i.id)).size,3);
  assert.deepEqual(review.items.map(i=>i.requestId),['A','A','B']);
  assert.deepEqual(review.items.map(i=>i.blockIndices),[[0],[0],[1]]);
  assert.equal(review.items[0].excerpt,work.blocks[0].text);
  assert.equal(review.items[2].severity,'warning');
  const refreshed=structuredClone(work);
  refreshed.requests[0].assessment.issues.reverse();
  const updated=deriveDraftReview(refreshed);
  for(const item of review.items)assert.equal(updated.items.find(i=>i.description===item.description).id,item.id);
  assert.equal(review.canGenerate,false);
});

test('los párrafos globales, inválidos o coercibles nunca apuntan al primer párrafo',()=>{
  const indices=[null,undefined,'',false,'0',-1,0.5,2,NaN];
  const review=deriveDraftReview({requests:[row('A',{assessment:{issues:indices.map((p,i)=>issue(`Hallazgo ${i}`,p))}})],
    blocks:[block(0,0,'A','No debe seleccionarse.') ]});
  assert.equal(review.items.length,indices.length);
  for(const item of review.items){
    assert.equal(item.paragraphIndex,null);
    assert.deepEqual(item.blockIndices,[]);
    assert.equal(item.excerpt,'');
  }
  const html=draftReviewMarkup(review);
  assert.doesNotMatch(html,/data-view-fragment/);
  assert.match(html,/Revisión de la respuesta completa/);
  assert.equal((html.match(/data-review-adjustment=/g)||[]).length,indices.length);
});

test('localiza únicamente marcadores exactos con la petición correcta, incluidos contextos compartidos',()=>{
  const work={requests:[
    row('A',{assessment:{issues:[issue('Contexto de A',1)]}}),
    row('B',{assessment:{issues:[issue('Contexto de B',0)]}}),
  ],blocks:[
    block(0,1,'otra','No pertenece a A'),
    block(0,0,'A','Otro párrafo'),
    block(0,1,'A','Contexto compartido',{kind:'context',bookmarks:['response_0_1','response_1_0'],request_ids:['A','B']}),
    block(0,1,'A','Texto antiguo con marcador incompatible',{bookmarks:['response_0_01']}),
    block(0,1,'A','Marcador singular válido',{bookmarks:[]}),
    block(0,1,'A','Sin identidad de petición',{request_ids:undefined}),
  ]};
  const review=deriveDraftReview(work);
  assert.deepEqual(review.items[0].blockIndices,[2,4]);
  assert.deepEqual(review.items[1].blockIndices,[2]);
  assert.equal(review.items[0].excerpt,'Contexto compartido\n\nMarcador singular válido');
});

test('un índice válido sin marcador no ofrece localizar un fragmento inventado',()=>{
  const review=deriveDraftReview({requests:[row('A',{assessment:{issues:[issue('Revisar el segundo párrafo.',1)]}})],
    blocks:[{kind:'heading',text:'Petición A',request_ids:['A']}]});
  assert.equal(review.items[0].paragraphIndex,1);
  assert.deepEqual(review.items[0].blockIndices,[]);
  const html=draftReviewMarkup(review);
  assert.doesNotMatch(html,/data-view-fragment|Párrafo 2 de/);
  assert.match(html,/data-review-adjustment/);
});

test('separa faltantes, fuentes cambiadas, comprobación en curso y errores sin dar ubicaciones falsas',()=>{
  const review=deriveDraftReview({requests:[
    row('vacía',{paragraphs:[],status:'editing'}),
    row('blanco',{paragraphs:[paragraph('  ')],status:'editing'}),
    row('stale',{status:'ready',stale:true,error:'La fuente cambió.',assessment:{issues:[issue('Hallazgo obsoleto',0)]}}),
    row('en-curso',{status:'checking',assessment:null}),
    row('error',{status:'error',error:'La conexión se interrumpió.',assessment:null}),
    row('sin-comprobar',{status:'editing',assessment:null}),
  ],blocks:[]});
  assert.equal(review.unprepared,2);
  assert.equal(review.checking,1);
  assert.equal(review.ready,0);
  assert.equal(review.canGenerate,false);
  assert.deepEqual(review.items.map(i=>i.kind),['unprepared','unprepared','stale','error','unchecked']);
  assert.equal(review.items[2].description,'La fuente cambió.');
  assert.equal(review.items[3].description,'La conexión se interrumpió.');
  assert.ok(review.items.every(i=>i.paragraphIndex===null&&i.blockIndices.length===0));
  const html=draftReviewMarkup(review);
  assert.match(html,/Comprobando 1 respuesta/);
  assert.match(html,/La fuente cambió/);
  assert.doesNotMatch(html,/Hallazgo obsoleto/);
});

test('los estados que requieren cambios o evidencia siguen bloqueados aunque falte una explicación',()=>{
  const review=deriveDraftReview({requests:[row('A'),row('B',{status:'needs_evidence'})]});
  assert.equal(review.items.length,2);
  assert.equal(review.canGenerate,false);
  assert.equal(review.items[0].title,'Esta respuesta necesita un ajuste');
  assert.equal(review.items[1].title,'Respaldo pendiente de revisar');
  assert.ok(review.items.every(i=>i.paragraphIndex===null));
});

test('solo permite generar con todas las respuestas listas, vigentes y sin hallazgos',()=>{
  const work={requests:[row('A',{status:'ready',assessment:{status:'passed',issues:[]}}),
    row('B',{status:'approved',assessment:{status:'passed',issues:[]}})]};
  assert.deepEqual(deriveDraftReview(work),{items:[],checking:0,unprepared:0,ready:2,canGenerate:true});
  assert.equal(deriveDraftReview({requests:[]}).canGenerate,false);
  assert.equal(deriveDraftReview(null).canGenerate,false);
  work.requests[0].assessment.issues=[issue('Hallazgo todavía presente',null)];
  assert.equal(deriveDraftReview(work).canGenerate,false);
});

test('guardar cambios no cuenta ajustes como resueltos ni promete una versión comprobada',()=>{
  const review=deriveDraftReview({requests:[row('A',{status:'ready',assessment:{issues:[]}})]});
  const clean=draftReviewMarkup(review),dirty=draftReviewMarkup(review,{dirty:true});
  assert.match(clean,/pasó las comprobaciones/);
  assert.match(dirty,/Hay cambios sin guardar/);
  assert.doesNotMatch(dirty,/pasó las comprobaciones|Puedes generar|resueltos de/);
  assert.match(draftReviewMarkup(deriveDraftReview({})),/Todavía no hay respuestas preparadas/);
});

test('muestra toda la lista, expande la selección y habilita la navegación con límites',()=>{
  const review=deriveDraftReview({requests:[row('A',{assessment:{issues:[issue('Primero',null),issue('Segundo',null),issue('Tercero',null)]}})]});
  const html=draftReviewMarkup(review,{selectedId:review.items[1].id});
  assert.equal((html.match(/data-select-adjustment=/g)||[]).length,3);
  assert.equal((html.match(/aria-expanded="true"/g)||[]).length,1);
  assert.match(html,new RegExp(`data-select-adjustment="${review.items[1].id}" aria-expanded="true"`));
  assert.match(html,/<span>2 de 3<\/span>/);
  assert.doesNotMatch(html,/data-adjustment-(prev|next) disabled/);
  assert.match(draftReviewMarkup(review),/data-adjustment-prev disabled/);
  assert.match(draftReviewMarkup(review,{selectedId:review.items[2].id}),/data-adjustment-next disabled/);
  const busy=draftReviewMarkup(review,{selectedId:review.items[1].id,busy:true});
  assert.match(busy,/data-adjustment-prev disabled/);
  assert.match(busy,/data-adjustment-next disabled/);
});

test('escapa todo texto externo y evita localizar hallazgos de una versión editada sin guardar',()=>{
  const attack='<img src=x onerror="alert(1)"> & \'<script>hola</script>';
  const review=deriveDraftReview({requests:[row(attack,{label:attack,assessment:{issues:[issue(attack,0)]}})],
    blocks:[block(0,0,attack,attack)]});
  const html=draftReviewMarkup(review);
  assert.doesNotMatch(html,/<img|<script|onerror="/);
  assert.match(html,/&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
  assert.match(html,/data-view-fragment=/);
  assert.match(draftReviewMarkup(review,{dirty:true}),/data-view-fragment="[^"]+" disabled/);
});

test('la tarjeta seleccionada no repite la explicación ni el ordinal de la petición',()=>{
  const description='Aclara el canal institucional donde se inicia el trámite.';
  const review=deriveDraftReview({requests:[row('A',{label:'1',assessment:{issues:[issue(description,0)]}})],
    blocks:[block(0,0,'A','El trámite puede iniciarse en el portal institucional.')]});
  const html=draftReviewMarkup(review);
  assert.equal(review.items[0].requestLabel,'Petición 1');
  assert.equal(html.split(description).length-1,1);
  assert.match(html,/<span>Petición 1<\/span>/);
  assert.doesNotMatch(html,/class="draft-adjustment-description"|Guarda después de editar/);
  assert.match(html,/Párrafo 1<\/p>/);
});

test('una explicación larga se conserva completa una vez al seleccionarla y breve al colapsarla',()=>{
  const description='Revisa que el procedimiento descrito corresponda al tipo de certificado solicitado y al programa académico. La fuente consultada solo describe una modalidad y no confirma el canal de las demás.';
  const review=deriveDraftReview({requests:[row('A',{assessment:{issues:[issue(description,null),issue('Segundo ajuste.',null)]}})]});
  const expanded=draftReviewMarkup(review);
  assert.equal(expanded.split(description).length-1,1);
  assert.doesNotMatch(expanded,/class="draft-adjustment-description"/);
  const collapsed=draftReviewMarkup(review,{selectedId:review.items[1].id});
  assert.ok(collapsed.includes(review.items[0].title));
  assert.ok(!collapsed.includes(description));
  // A distinct state title still needs its explanation.
  assert.match(draftReviewMarkup(deriveDraftReview({requests:[row('B',{stale:true,error:'La fuente cambió.'})]})),/class="draft-adjustment-description">La fuente cambió\./);
});

test('el fragmento visible es breve sin cambiar el original ni las coordenadas para resaltarlo',()=>{
  const excerpt='El trámite de constancia académica puede iniciarse en el portal institucional. '+
    'La persona solicitante debe consultar el canal de atención de la Facultad antes de presentar su solicitud. '+
    'Este resto se consulta directamente en el documento original y no necesita ocupar todo el panel.';
  const review=deriveDraftReview({requests:[row('A',{assessment:{issues:[issue('Aclara el canal.',0)]}})],
    blocks:[block(0,0,'A',excerpt)]});
  const html=draftReviewMarkup(review),visible=html.match(/<blockquote class="draft-adjustment-excerpt">([^<]+)<\/blockquote>/)[1];
  assert.ok(visible.length<=180);
  assert.ok(visible.endsWith('…'));
  assert.equal(review.items[0].excerpt,excerpt);
  assert.deepEqual(review.items[0].blockIndices,[0]);
  assert.match(html,/data-view-fragment=/);
});
