// Reception only saves/assigns. Identification starts exclusively from preanalysis.
export async function receiveDocument(item, {mode, manager, metadata, upload, request, saved=()=>{}}){
  if(mode==='analyze'&&!manager)throw new Error('Selecciona tu gestor antes de iniciar el análisis.');
  if(!item.caseId){
    const created=await upload(item.file,metadata);
    item.caseId=created.id;
    await saved(created.id);
  }
  if(mode==='save')return item.caseId;
  let record=await request(`/api/cases/${item.caseId}/management`);
  if(record.state==='closed')throw new Error('El expediente está finalizado. Reabre su gestión para analizarlo.');
  if(!record.owner_id)record=await request(`/api/cases/${item.caseId}/management`,{revision:record.revision,actor_id:manager,action:'claim'});
  if(record.owner_id!==manager)throw new Error('Otro gestor tomó este expediente. Consulta el pool antes de continuar.');
  return item.caseId;
}
