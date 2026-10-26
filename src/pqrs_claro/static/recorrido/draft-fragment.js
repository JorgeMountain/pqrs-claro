// A visual range only: never inserts markup into editable text or export data.
export function createDraftFragment(root){
  let current=null;
  const registry=()=>globalThis.CSS?.highlights;
  const bar=()=>root.querySelector('[data-fragment-bar]');
  function clear(){
    registry()?.delete('draft-fragment');
    current=null;
    const strip=bar();if(strip)strip.hidden=true;
  }
  function show(item,number){
    clear();
    const elements=(item?.blockIndices||[]).flatMap(index=>Number.isInteger(index)?[...root.querySelectorAll(`[data-block="${index}"]`)]:[]);
    if(!elements.length)return false;
    const ranges=elements.map(el=>{const range=document.createRange();range.selectNodeContents(el);return range;});
    if(registry()&&globalThis.Highlight)registry().set('draft-fragment',new Highlight(...ranges));
    const canvas=root.querySelector('.document-canvas'),first=elements[0];
    const rect=first.getBoundingClientRect(),viewport=canvas.getBoundingClientRect();
    if(rect.top<viewport.top+8||rect.bottom>viewport.bottom-48)canvas.scrollTop+=rect.top-viewport.top-Math.max(24,viewport.height/3);
    // Keep keyboard focus on the action, not inside contenteditable.
    const strip=bar();strip.hidden=false;
    root.querySelector('[data-fragment-label]').textContent=`${registry()&&globalThis.Highlight?'Fragmento':'Ubicación'} del ajuste ${number}`;
    current=item.id;
    return true;
  }
  return {show,clear,get selected(){return current;}};
}
