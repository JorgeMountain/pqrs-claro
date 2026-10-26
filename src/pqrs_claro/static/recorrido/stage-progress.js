import {esc} from './views.js';
import {icon} from './inbox-icons.js';
import {initialReady,typeNames} from './initial-review.js?v=reading-space1';

const stages=['Preanálisis','Identificación','Redacción','Borrador'];
const checkKeys=['requester','respect','integrity'];
const validType=value=>Boolean(typeNames[value]&&value!=='undetermined');

// Counts describe saved work, never elapsed time or a presumed human approval.
export function stageProgress({stage,title,message='',count=null,total=null,running=false,completed=[],stageComplete=false,warning=false,historical=false}){
  const known=Number.isInteger(total)&&total>0&&Number.isInteger(count)&&count>=0;
  const value=known?Math.min(count,total):null;
  const description=[title,message].filter(Boolean).join(' · ');
  const fraction=known&&!historical?value/total:0;
  return `<section class="redaction-progress stage-progress stage-progress-${stage}" aria-label="Avance de ${stages[stage]}">
    <div class="redaction-progress-copy" role="status" aria-atomic="true">${running?'<span class="source-spinner" aria-hidden="true"></span>':icon(warning||!stageComplete?'info':'check')}<span><strong>${esc(title)}</strong>${message?`<span class="redaction-progress-message"> · ${esc(message)}</span>`:''}</span></div>
    <div class="redaction-segments" role="progressbar" aria-label="Avance de ${stages[stage]}" aria-valuetext="${esc(description)}"${known&&!historical?` aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${value}"`:''}>${stages.map((name,index)=>{
      const active=index===stage,done=active?stageComplete:Boolean(completed[index]);
      const fill=done?1:active?fraction:0;
      return `<span class="workflow-segment stage-${index}${active?' current':''}${done?' complete':''}${active&&running&&!known?' indeterminate':''}" style="--stage-fill:${Math.round(fill*100)}%" aria-hidden="true"><i></i></span>`;
    }).join('')}</div>
    <span class="redaction-count" aria-hidden="true">${known?`${value}/${total}`:Number.isInteger(total)&&total>0?`…/${total}`:'…'}</span>
  </section>`;
}

export function preanalysisProgress(record={},navigation={}){
  const ready=record.status==='ready',loading=record.status==='loading',running=record.status==='running';
  const failed=Boolean(record.error||record.status==='error');
  const count=ready?checkKeys.filter(key=>['pass','attention'].includes(record.checks?.[key]?.state)).length:0;
  const attention=ready&&checkKeys.some(key=>record.checks?.[key]?.state!=='pass');
  const approved=ready&&Boolean(record.approval);
  const title=failed?'Verificaciones por consultar':loading?'Recuperando las verificaciones guardadas…':running?'Revisando el documento':`${count} de 3 verificaciones realizadas`;
  const message=failed?'No se completaron las verificaciones; revisa el aviso':loading?'El avance se conserva':running?'Comprobando datos, contenido y legibilidad':approved?'Revisión previa confirmada':ready?attention?'Revisa los hallazgos antes de continuar':'Pendiente de tu revisión':'Verificaciones pendientes';
  return stageProgress({stage:0,title,message,count:loading||running||failed?null:count,total:3,running:!failed&&(loading||running),completed:navigation.completed,stageComplete:approved,warning:failed||attention});
}

export function identificationProgress(current,initial={},navigation){
  const requests=current.identification?.requests||current.requests||[];
  const extracting=Boolean(current.analysis_running||['reading','identifying'].includes(current.status)||!current.identification);
  const classifying=initial.status==='running';
  const loading=!extracting&&!initial.status&&!initial.loadError;
  const failed=Boolean(current.error||initial.error||initial.loadError||initial.status==='interrupted');
  const missing=Boolean(initial.loadError&&!initial.report);
  const historical=Boolean(initial.stale||initial.legacy_report);
  const report=new Map((initial.report?.requests||[]).map(row=>[row.request_id,row]));
  const reused=new Set(initial.analysis_work?.reused||[]);
  const count=extracting?null:requests.filter(row=>validType(report.get(row.id)?.petition_type)&&(!classifying||reused.has(row.id))).length;
  const total=requests.length;
  const reviewed=!historical&&initialReady(initial)&&Boolean(initial.can_prepare||initial.status==='routed');
  const title=missing?'No se pudo recuperar la identificación':extracting?'Identificando las peticiones del documento':loading?'Recuperando la identificación guardada…':total?`${count} de ${total} ${total===1?'petición clasificada':'peticiones clasificadas'}`:'Sin peticiones para clasificar';
  const message=failed?'La identificación requiere atención; el avance se conserva':extracting?'El total aparecerá al terminar la lectura':historical?'Resultados anteriores; falta actualizar la identificación':classifying?'Clasificando el tipo de cada petición':loading?'El avance se conserva':reviewed?'Revisión conjunta guardada':initialReady(initial)?count<total?'Hay tipos pendientes de determinar':'Pendiente de tu revisión conjunta':initial.status==='idle'?'Falta clasificar los tipos de petición':'Consultando el avance';
  return stageProgress({stage:1,title,message,count:loading||missing?null:count,total,running:!failed&&(extracting||classifying||loading),completed:navigation?.completed||[current.preanalysis_status==='ready'],stageComplete:reviewed,warning:failed||historical,historical});
}

export function draftProgress(work,model,{total=0,dirty=false,externalChanges=false,busy=false,message='',error='',generated=false,confirmed=false,completed=[],approval=null}={}){
  if(!work)return stageProgress({stage:3,title:error?'No se pudo recuperar el borrador':'Recuperando el borrador guardado…',message:error?'Vuelve a cargar para consultar el avance':'Armando el documento con las respuestas guardadas',running:!error,completed,warning:Boolean(error)});
  const rows=work.requests||[],expected=Math.max(total,rows.length),unsaved=dirty||externalChanges;
  const final=generated&&!unsaved&&!error;
  if(approval&&!final&&!unsaved&&(busy||error)){
    const title=`${approval.count} de ${approval.total} ${approval.total===1?'respuesta aprobada':'respuestas aprobadas'}`;
    const detail=error?'El avance guardado se conserva. Revisa el aviso para continuar.':message;
    return stageProgress({stage:3,title,message:detail,count:approval.count,total:approval.total,running:busy&&!error,completed,stageComplete:false,warning:Boolean(error)});
  }
  const pending=model.items.length;
  const title=final?'Versión final generada':unsaved?'Cambios pendientes de comprobar':expected?`${model.ready} de ${expected} ${expected===1?'respuesta comprobada':'respuestas comprobadas'}`:'Borrador sin respuestas preparadas';
  const detail=error?'La operación requiere atención; revisa el aviso':busy?message||'Actualizando el borrador':unsaved?'Guarda los cambios para actualizar el avance':final?'Word y PDF disponibles':model.checking?`Comprobando ${model.checking} ${model.checking===1?'respuesta':'respuestas'}`:pending?`${pending} ${pending===1?'ajuste pendiente':'ajustes pendientes'}`:!model.canGenerate||model.ready<expected?'Falta preparar las respuestas':confirmed?'Revisión confirmada; falta generar el oficio':'Pendiente de tu revisión final';
  return stageProgress({stage:3,title,message:detail,count:unsaved?null:model.ready,total:expected,running:busy||model.checking>0,completed,stageComplete:final,warning:Boolean(error)||pending>0});
}
