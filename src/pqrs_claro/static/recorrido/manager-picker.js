import {esc} from './views.js';
import {icon} from './inbox-icons.js?v=managers1';

export function createManagerPicker({select,onAdd}){
  const host=document.querySelector('.inbox-identity');
  const trigger=host.querySelector('[data-manager-toggle]');
  const popup=host.querySelector('#manager-picker');
  const list=host.querySelector('[data-manager-list]');
  let signature='';
  host.querySelectorAll('[data-manager-icon]').forEach(el=>el.innerHTML=icon(el.dataset.managerIcon));
  const options=()=>[...list.querySelectorAll('[role=option]')];
  function close(restoreFocus=false){
    popup.hidden=true;trigger.setAttribute('aria-expanded','false');
    if(restoreFocus)trigger.focus({preventScroll:true});
  }
  function focusOption(option){
    options().forEach(el=>el.tabIndex=el===option?0:-1);
    option?.focus({preventScroll:true});option?.scrollIntoView({block:'nearest'});
  }
  function open(last=false){
    popup.hidden=false;trigger.setAttribute('aria-expanded','true');
    const items=options();
    focusOption(last?items.at(-1):items.find(el=>el.getAttribute('aria-selected')==='true')||items[0]);
    if(!items.length)popup.querySelector('[data-manager-add]').focus();
  }
  trigger.addEventListener('click',()=>popup.hidden?open():close(true));
  trigger.addEventListener('keydown',event=>{
    if(!['ArrowDown','ArrowUp'].includes(event.key))return;
    event.preventDefault();open(event.key==='ArrowUp');
  });
  host.addEventListener('click',event=>{
    const option=event.target.closest('[data-manager-id]');
    if(option){
      select.value=option.dataset.managerId;
      select.dispatchEvent(new Event('change',{bubbles:true}));
      close(true);
    }else if(event.target.closest('[data-manager-add]')){
      close(true);onAdd();
    }
  });
  host.addEventListener('keydown',event=>{
    if(popup.hidden)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
    const option=event.target.closest('[role=option]');
    if(!option||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
    event.preventDefault();
    const items=options(),index=items.indexOf(option);
    const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;
    focusOption(items[next]);
  });
  document.addEventListener('pointerdown',event=>{if(!host.contains(event.target))close();});
  host.addEventListener('focusout',event=>{if(!host.contains(event.relatedTarget))close();});
  function sync(managers,selected){
    const manager=managers.find(m=>m.id===selected);
    host.querySelector('[data-manager-name]').textContent=manager?.name||'Selecciona tu gestor';
    trigger.setAttribute('aria-label',`Cambiar gestor: ${manager?.name||'sin seleccionar'}`);
    const current=JSON.stringify([managers.map(m=>[m.id,m.name]),selected]);
    if(current===signature)return;
    signature=current;
    const focused=list.contains(document.activeElement)?document.activeElement.dataset.managerId:null;
    const ordered=[...managers].sort((a,b)=>Number(b.id===selected)-Number(a.id===selected));
    list.innerHTML=ordered.map((m,index)=>{
      const active=m.id===selected;
      const color=active?'selected':managers.indexOf(m)%2?'violet':'sage';
      return `<button type="button" role="option" aria-selected="${active}" tabindex="${active||(!manager&&index===0)?0:-1}" class="manager-option" data-manager-id="${esc(m.id)}"><span class="manager-avatar ${color}" aria-hidden="true">${esc(m.name.slice(0,1).toUpperCase())}</span><span class="manager-option-copy"><span>${esc(m.name)}</span>${active?'<small>Seleccionado</small>':''}</span>${active?`<span class="manager-selected-check">${icon('check')}</span>`:''}</button>`;
    }).join('')||'<p class="manager-empty">Todavía no hay gestores. Añade el primero.</p>';
    if(focused&&!popup.hidden)focusOption(options().find(el=>el.dataset.managerId===focused)||options()[0]);
  }
  return {sync,close};
}
