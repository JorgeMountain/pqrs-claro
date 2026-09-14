// Identificación declarada en este navegador; no equivale a autenticación institucional.
const key='gestion-peticiones-responsable-v1';
let value='';
try{value=sessionStorage.getItem(key)||'';}catch{}
export const sessionActor=()=>value;
export function rememberActor(name){
  value=String(name||'').trim().slice(0,240);
  try{sessionStorage.setItem(key,value);}catch{}
}
export function bindActor(form,selector='[name="author"],#pending-actor,#response-actor,#proposal-actor,#office-actor'){
  const input=form?.querySelector(selector);if(!input)return;
  const label=input.closest('label');if(!label)return;
  const text=[...label.childNodes].find(n=>n.nodeType===3);
  if(text)text.textContent='Responsable de esta sesión';
  input.value=value||input.value;
  const summary=document.createElement('p');summary.className='session-actor';
  const name=document.createElement('span'),change=document.createElement('button');
  change.type='button';change.className='text-button';change.textContent='Cambiar';summary.append(name,' · ',change);label.after(summary);
  const sync=()=>{const saved=Boolean(value);label.hidden=saved;summary.hidden=!saved;name.textContent='Responsable: '+value;};
  change.onclick=()=>{label.hidden=false;summary.hidden=true;input.focus();};
  input.addEventListener('change',()=>{if(input.value.trim()){rememberActor(input.value);sync();}});
  form.addEventListener('submit',()=>rememberActor(input.value),{capture:true});
  sync();
}
