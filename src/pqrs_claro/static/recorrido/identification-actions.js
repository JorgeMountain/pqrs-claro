import {esc} from './views.js';

// The existing identification endpoint preserves revisions and checks the version.
export function createIdentificationActions({api,open,close,notice,getCase,onSaved}){
  let undo=null;
  function banner(){
    const current=getCase();
    if(!undo||current?.id!==undo.caseId||current.version!==undo.version||current.status!=='needs_review')return '';
    return `<div class="identification-undo" role="status"><span>Se descartó «${esc(undo.title)}». El documento original se conserva.</span><button data-action="live-undo-discard">Deshacer</button></div>`;
  }
  function discard(index){
    const current=getCase();
    if(current?.status!=='needs_review')return;
    const row=current.identification.requests[index];
    if(!row)return;
    const caseId=current.id,version=current.version,before=structuredClone(current.identification);
    if(before.requests.length===1){
      open('No se puede dejar la petición vacía','<p>Esta es la única solicitud identificada. Puedes corregirla con «Editar». Para confirmar la petición debe quedar al menos una solicitud.</p>');
      return;
    }
    open('Descartar como solicitud',`<p><strong>${esc(row.title)}</strong></p><p>Se retirará de las solicitudes que vas a confirmar y no se preparará una respuesta para este fragmento. El texto seguirá en el documento original.</p><div class="actionbar"><button id="discard-cancel" type="button">Cancelar</button><button id="discard-confirm" type="button" class="primary">No es una solicitud · descartar</button></div><p id="discard-error" role="alert"></p>`);
    document.querySelector('#discard-cancel').onclick=close;
    const button=document.querySelector('#discard-confirm'),error=document.querySelector('#discard-error');
    button.onclick=async()=>{
      button.disabled=true;
      try{
        if(getCase()?.id!==caseId)throw new Error('El expediente cambió. Abre de nuevo la solicitud.');
        const identification=structuredClone(before);
        identification.requests=identification.requests.filter(r=>r.id!==row.id).map(r=>r.parent_id===row.id?{...r,parent_id:row.parent_id||null}:r);
        const saved=await api(`/api/cases/${caseId}/identification`,{version,identification},'PUT');
        undo={caseId,version:saved.version,identification:before,title:row.title};
        close();await onSaved(caseId);notice('Solicitud descartada. Puedes deshacerlo antes de continuar.');
        document.querySelector('[data-action="live-undo-discard"]')?.focus();
      }catch(e){if(error.isConnected){error.textContent=e.message;button.disabled=false;}else notice(e.message);}
    };
  }
  async function restore(){
    const current=getCase(),snapshot=undo;
    if(!snapshot||current?.id!==snapshot.caseId||current.version!==snapshot.version||current.status!=='needs_review')throw new Error('La revisión cambió. No se puede deshacer esta acción sobre otra versión.');
    await api(`/api/cases/${snapshot.caseId}/identification`,{version:snapshot.version,identification:snapshot.identification},'PUT');
    undo=null;await onSaved(snapshot.caseId);notice('Solicitud restaurada.');
  }
  return {discard,restore,banner};
}
