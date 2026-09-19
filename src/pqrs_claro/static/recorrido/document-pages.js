// Paginación visual: fragmentos de un mismo bloque, sin añadir texto al oficio.
import {hasUdeaLayout,addUdeaLetterhead} from './document-letterhead.js';
export function fragmentText(el){
  return [...el.childNodes].map((child,i)=>{
    if(child.nodeType===Node.TEXT_NODE)return child.textContent;
    if(child.nodeType!==Node.ELEMENT_NODE||child.hasAttribute('data-caret-tail'))return '';
    if(child.tagName==='BR')return '\n';
    const block=['DIV','P'].includes(child.tagName);
    const empty=block&&child.childNodes.length===1&&child.firstChild.nodeName==='BR';
    return (block&&i?'\n':'')+(empty?'':fragmentText(child));
  }).join('').replace(/\r\n/g,'\n');
}

export function selectionPoint(root){
  const selection=getSelection();if(!selection?.rangeCount)return null;
  const range=selection.getRangeAt(0),anchor=selection.anchorNode;
  const el=(anchor.nodeType===Node.ELEMENT_NODE?anchor:anchor.parentElement)?.closest('[data-block]');
  if(!el||!root.contains(el)||!el.contains(range.endContainer))return null;
  const start=range.cloneRange();start.selectNodeContents(el);start.setEnd(range.startContainer,range.startOffset);
  const end=range.cloneRange();end.selectNodeContents(el);end.setEnd(range.endContainer,range.endOffset);
  const offset=Number(el.dataset.offset||0);
  return {block:Number(el.dataset.block),start:offset+fragmentText(start.cloneContents()).length,end:offset+fragmentText(end.cloneContents()).length};
}

export function focusPoint(root,point){
  if(!point)return;
  const fragments=[...root.querySelectorAll(`[data-block="${point.block}"]`)];
  const find=offset=>fragments.find(el=>offset<Number(el.dataset.offset)+el.textContent.length)||fragments.at(-1);
  const first=find(point.start),last=find(point.end);if(!first||!last)return;
  const locate=(el,offset)=>{
    const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let node;
    let left=Math.max(0,offset-Number(el.dataset.offset||0));
    while((node=walker.nextNode())){if(left<=node.length)return [node,left];left-=node.length;}
    if(!el.firstChild)el.append(document.createTextNode(''));
    return [el,el.childNodes.length];
  };
  first.focus({preventScroll:true});
  const range=document.createRange();range.setStart(...locate(first,point.start));range.setEnd(...locate(last,point.end));
  const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
  const canvas=root.querySelector('.document-canvas'),rect=range.getBoundingClientRect(),viewport=canvas.getBoundingClientRect();
  if(rect.bottom>viewport.bottom-20)canvas.scrollTop+=rect.bottom-viewport.bottom+28;
  else if(rect.top<viewport.top+12)canvas.scrollTop+=rect.top-viewport.top-20;
}

export function paginate(root,blocks,makeBlock,letterhead){
  const pages=root.querySelector('.oficio-pages');pages.replaceChildren();
  let body;
  function page(){
    const sheet=document.createElement('article');sheet.className='oficio-sheet'+(letterhead?' with-letterhead':'');
    sheet.setAttribute('aria-label',`Página ${pages.children.length+1} del oficio`);
    body=document.createElement('div');body.className='oficio-page-body';
    if(hasUdeaLayout(letterhead))addUdeaLetterhead(sheet);
    else body.innerHTML='<div class="oficio-letterhead"><img src="/logo.png" alt="Universidad de Antioquia · Facultad de Ingeniería" width="260" height="78"></div>';
    sheet.append(body);pages.append(sheet);
    const number=document.createElement('span');number.className='oficio-page-number';number.setAttribute('aria-hidden','true');sheet.append(number);
  }
  const fits=()=>body.scrollHeight<=body.clientHeight+1;
  function setText(el,text){
    el.textContent=text;
    if(text.endsWith('\n')){const tail=document.createElement('br');tail.dataset.caretTail='';el.append(tail);}
  }
  page();
  // Las respuestas pueden terminar de cargar con esta sección oculta.
  // Esperar a que exista una caja medible antes de dividir el contenido.
  if(!body.clientHeight){pages.dataset.needsPagination='true';return;}
  delete pages.dataset.needsPagination;
  for(let index=0;index<blocks.length;index++){
    const template=document.createElement('template');template.innerHTML=makeBlock(blocks[index],index);
    const original=template.content.firstElementChild;
    let rest=original.textContent,offset=0;
    do{
      const el=original.cloneNode(false);el.dataset.offset=String(offset);
      if(offset){el.classList.add('oficio-continuation');el.removeAttribute('data-placeholder');}
      setText(el,rest);body.append(el);
      if(fits())break;
      let lo=0,hi=rest.length;
      while(lo<hi){const mid=Math.ceil((lo+hi)/2);setText(el,rest.slice(0,mid));if(fits())lo=mid;else hi=mid-1;}
      let cut=lo;
      // Mantener palabras completas y pares sustitutos Unicode.
      if(cut&&/[\uD800-\uDBFF]/.test(rest[cut-1]))cut--;
      const boundary=Math.max(rest.lastIndexOf(' ',cut-1),rest.lastIndexOf('\n',cut-1))+1;
      if(boundary>cut*.75)cut=boundary;
      if(!cut){el.remove();page();continue;}
      setText(el,rest.slice(0,cut));rest=rest.slice(cut);offset+=cut;
      page();
    }while(rest.length);
  }
  const total=pages.children.length;
  [...pages.children].forEach((sheet,i)=>sheet.querySelector('.oficio-page-number').textContent=`${i+1} / ${total}`);
  root.querySelector('[data-page-count]').textContent=`${total} ${total===1?'página':'páginas'}`;
}
