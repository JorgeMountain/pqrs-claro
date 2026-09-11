"""Decisiones previas, avance independiente y concurrencia sin llamadas externas."""
import threading
from copy import deepcopy
from test_draft_service_api import draft_app, prepared_case, wait_drafts, FakeDraftEngine
from test_preparation import wait


def add_gap(app, case):
    run=app.state.library.latest_run(case['id'])
    run['results'][0]['missing']=[dict(kind='clarification',description='Comprobar la aplicabilidad de la norma al período solicitado.',
        affected_claim='Aplicación de la norma al período.',why_unresolved='La fecha de aplicación necesita contraste humano.',
        reason_code='applicability',basis='content_gap')]
    app.state.library.save_run(run)


def test_points_before_draft_confirm_then_automatic_draft_with_decision(draft_app):
    app,client,engine,_=draft_app
    case,_=prepared_case(app)
    app.state.sources.assessor=object() # ready map is reused; no remote work
    add_gap(app,case)
    captured={}
    plan=engine.plan
    def capture(request,finding):
        captured[request['id']]=deepcopy(finding)
        return plan(request,finding)
    engine.plan=capture
    prefix=f"/api/cases/{case['id']}"
    assert client.post(prefix+'/preparation',json={'version':case['version']}).status_code==202
    job=wait(app,client,case['id'])
    assert job['status']=='waiting_review',job
    rows=client.get(prefix+'/review').json()['requests']
    first,second=rows
    assert first['pre_draft'] and not first['paragraphs'] and first['pending']
    assert second['paragraphs'] and not second['approval']
    assert engine.calls[('P1','plan')]==0 and engine.calls[('P2','write')]==1
    gap=next(p for p in first['pending'] if p.get('blocks_approval',True))
    body=dict(revision=first['revision'],edited_by='Revisora de prueba',paragraphs=[],pending_resolutions=[dict(
        pending_id=gap['id'],action='resolved',note='Se cotejó la norma para el período solicitado.',
        cited_chunk_ids=[first['available_supports'][0]['chunk_id']],cited_fact_ids=[])])
    saved=client.put(prefix+'/review/requests/P1',json=body)
    assert saved.status_code==200,saved.text
    assert wait(app,client,case['id'])['status']=='ready'
    updated=client.get(prefix+'/review').json()['requests']
    assert all(r['paragraphs'] and r['approval'] is None for r in updated)
    assert engine.calls[('P2','write')]==1 and engine.calls[('P1','write')]==1
    decision=captured['P1']['human_decisions'][0]['resolution']
    assert decision['note']==body['pending_resolutions'][0]['note']
    assert decision['by']=='Revisora de prueba'
    assert updated[0]['pending'][0]['resolution']
    assert client.put(prefix+'/review/requests/P1',json=body).status_code==409


def test_three_drafts_overlap_and_results_keep_question_order(draft_app):
    app,client,engine,_=draft_app
    case,_=prepared_case(app,count=5)
    lock=threading.Lock();entered=threading.Event();release=threading.Event()
    active=0;peak=0
    write=engine.write
    def blocked(request,finding,plan):
        nonlocal active,peak
        with lock:
            active+=1;peak=max(peak,active)
            if active==3:entered.set()
        try:
            assert release.wait(8)
            return write(request,finding,plan)
        finally:
            with lock:active-=1
    engine.write=blocked
    app.state.drafts.start(case['id'],case['version'])
    try:
        assert entered.wait(5)
        run=app.state.drafts.get(case['id'])
        assert sum(s=='redactar' for s in run['request_states'].values())==3
        assert run['request_states']['P4']=='queued'
    finally:release.set()
    run=wait_drafts(app,client,case)
    assert peak==3 and run['status']=='ready',run
    assert [r['request_id'] for r in run['results']]==['P1','P2','P3','P4','P5']


def test_reopening_during_generation_does_not_accept_outdated_decision(draft_app):
    app,client,engine,_=draft_app
    case,_=prepared_case(app,count=1)
    app.state.sources.assessor=object()
    add_gap(app,case)
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    row=app.state.reviews.get(case['id'])['requests'][0]
    gap=row['pending'][0]
    saved=app.state.reviews.edit(case['id'],'P1',dict(revision=row['revision'],edited_by='QA',paragraphs=[],
        pending_resolutions=[dict(pending_id=gap['id'],action='not_applicable',note='No corresponde a este período.',cited_chunk_ids=[],cited_fact_ids=[])]))
    engine.block=('P1','write')
    app.state.drafts.start(case['id'],case['version'],ready_only=True)
    try:
        assert engine.entered.wait(5)
        app.state.reviews.edit(case['id'],'P1',dict(revision=saved['revision'],edited_by='QA',paragraphs=[],
            pending_resolutions=[dict(pending_id=gap['id'],action='open',note='',cited_chunk_ids=[],cited_fact_ids=[])]))
    finally:engine.release.set()
    run=wait_drafts(app,client,case)
    assert run['results'][0]['status']=='error'
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    assert not app.state.reviews.get(case['id'])['requests'][0]['paragraphs']


def test_analysis_failure_does_not_block_other_valid_questions(draft_app):
    app,client,engine,_=draft_app
    case,_=prepared_case(app)
    run=app.state.library.latest_run(case['id'])
    run['status']='error'
    run['results'][0].update(status='error',evidence_states=['analysis_error'],supports=[],missing=[])
    app.state.library.save_run(run)
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    app.state.drafts.start(case['id'],case['version'],ready_only=True)
    result=wait_drafts(app,client,case)
    assert result['status']=='partial'
    assert [r['request_id'] for r in result['results']]==['P2']
    assert engine.calls[('P1','plan')]==0


def test_predraft_document_cannot_be_confirmed_with_a_norm(draft_app):
    app,client,engine,_=draft_app
    case,_=prepared_case(app,count=1)
    run=app.state.library.latest_run(case['id'])
    run['results'][0]['missing']=[dict(kind='document',description='Localizar la copia del acta solicitada.',
        reason_code='document_search',basis='unavailable_document')]
    app.state.library.save_run(run)
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    row=app.state.reviews.get(case['id'])['requests'][0]
    gap=row['pending'][0]
    response=client.put(f"/api/cases/{case['id']}/review/requests/P1",json=dict(
        revision=row['revision'],edited_by='QA',paragraphs=[],pending_resolutions=[dict(
            pending_id=gap['id'],action='resolved',note='Se seleccionó una norma, no un acta.',
            cited_chunk_ids=[row['available_supports'][0]['chunk_id']],cited_fact_ids=[])]))
    assert response.status_code==422,response.text
    assert not engine.calls


def test_prior_decisions_reach_model_as_attributed_inputs(draft_app):
    from pqrs_claro.draft_engine import _api_context,_supports,_PLAN_INSTRUCTIONS,_WRITE_INSTRUCTIONS,_CHECK_INSTRUCTIONS
    app,_,_,_=draft_app
    case,_=prepared_case(app,count=1)
    add_gap(app,case)
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    row=app.state.reviews.get(case['id'])['requests'][0]
    row['pending'][0]['resolution']=dict(action='not_applicable',note='La condición no corresponde al período consultado.',
        cited_chunk_ids=[],cited_fact_ids=[],by='QA',at='2026-09-11T00:00:00Z')
    finding=app.state.library.latest_run(case['id'])['results'][0]
    reviewed=app.state.drafts._reviewed_finding(finding,row)
    request=case['identification']['requests'][0]
    payload,_=_api_context(request,reviewed,_supports(request,reviewed))
    decision=payload['finding']['human_decisions'][0]
    assert decision['action']=='not_applicable' and decision['by']=='QA'
    assert decision['note']==row['pending'][0]['resolution']['note']
    assert all('human_decisions' in prompt for prompt in [_PLAN_INSTRUCTIONS,_WRITE_INSTRUCTIONS,_CHECK_INSTRUCTIONS])
    assert not any(p.get('blocks_approval',True) for p in payload['existing_pending'] if p.get('resolution',{}).get('status')!='resolved')


def test_decision_changed_after_generation_is_checked_again_before_adoption(draft_app):
    app,client,engine,_=draft_app
    case,_=prepared_case(app,count=1)
    add_gap(app,case)
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    row=app.state.reviews.get(case['id'])['requests'][0]
    gap=row['pending'][0]
    saved=app.state.reviews.edit(case['id'],'P1',dict(revision=row['revision'],edited_by='QA',paragraphs=[],
        pending_resolutions=[dict(pending_id=gap['id'],action='not_applicable',note='No corresponde al período.',cited_chunk_ids=[],cited_fact_ids=[])]))
    app.state.drafts.start(case['id'],case['version'],ready_only=True)
    assert wait_drafts(app,client,case)['results'][0]['draft']['paragraphs']
    app.state.reviews.edit(case['id'],'P1',dict(revision=saved['revision'],edited_by='QA',paragraphs=[],
        pending_resolutions=[dict(pending_id=gap['id'],action='open',note='',cited_chunk_ids=[],cited_fact_ids=[])]))
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    assert not app.state.reviews.get(case['id'])['requests'][0]['paragraphs']


def test_twenty_five_candidate_fragments_remain_non_citable():
    import pytest
    from pqrs_claro.draft_engine import _candidate_inventory
    from pqrs_claro.models import DomainError
    chunks=[dict(chunk_id=f'candidate-{i}',page=1,line_start=i+1,line_end=i+1,quote='Pasaje candidato.',location_kind='page') for i in range(33)]
    document=dict(source_id='source',document_id='document',version=1,title='Candidato',filename='candidato.pdf',category='historical_attachment',location_status='candidate_located',chunks=chunks[:25])
    result=_candidate_inventory({'candidate_documents':[document]})
    assert result[0]['citable'] is False
    document['chunks']=chunks
    with pytest.raises(DomainError,match='treinta y dos'):
        _candidate_inventory({'candidate_documents':[document]})
