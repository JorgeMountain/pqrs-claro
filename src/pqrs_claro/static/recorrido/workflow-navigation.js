export function reviewShortcut(){
  return '<div class="workflow-shortcuts"><button type="button" class="text-button" data-action="live-stage-actions">Ir a revisión y acciones ↓</button></div>';
}

// Navigation only: no confirmation, persistence, or new model requests.
export function focusStageReview(root){
  const target=root.querySelector('.pre-confirm, .expediente-confirmation, .response-reading, .draft-confirmation')||root.querySelector('.stage-actions, .expediente-waiting');
  if(!target)return false;
  target.tabIndex=-1;
  target.focus({preventScroll:true});
  target.scrollIntoView({block:'start'});
  return true;
}

export function focusResponse(root,requestId){
  const response=[...root.querySelectorAll('[data-response-id]')].find(row=>row.dataset.responseId===requestId);
  const summary=response?.querySelector('summary');
  if(!summary)return false;
  response.open=true;
  summary.focus({preventScroll:true});
  summary.scrollIntoView({block:'start'});
  return true;
}
