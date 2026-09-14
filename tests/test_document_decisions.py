import json
from types import SimpleNamespace

import pytest
from test_draft_service_api import draft_app, prepared_case
from test_source_sufficiency import source, selection, request
from pqrs_claro.document_decisions import canonical_document_decision
from pqrs_claro.evidence_contract import normalize_item
from pqrs_claro.source_assessment import OpenAISourceAssessor, _DeclaredCheck
from pqrs_claro.source_sufficiency import metadata_check_required


@pytest.mark.parametrize('corrected',[True,False])
def test_optional_check_retries_once_without_turning_citation_failure_into_human_gap(corrected):
    candidate=source();good=selection()
    good.supports[0].chunk_id='C1';good.coverage[0].citations[0].chunk_id='C1'
    good.declared_checks=[_DeclaredCheck(chunk_id='C1',fact='Lo declarado en el antecedente.',
        declaration_quote=candidate['quote'],basis='Contenido del antecedente.')]
    bad=good.model_copy(deep=True);bad.declared_checks[0].declaration_quote='Texto que no está en el documento.'
    calls=[]
    def parse(**kwargs):
        calls.append(json.loads(kwargs['input']))
        return SimpleNamespace(status='completed',output_parsed=good if corrected and len(calls)==2 else bad)
    assessor=OpenAISourceAssessor('test-not-real','test')
    assessor.client=SimpleNamespace(responses=SimpleNamespace(parse=parse))
    result=assessor.assess(request(),[candidate])
    assert len(calls)==2 and calls[0]['candidates']==calls[1]['candidates']
    assert result['supports'] and not result['missing']
    assert 'analysis_error' not in result['evidence_states']
    assert bool(result['verifications'])==corrected
    assert bool(result['analysis_notices'])!=corrected


def test_partial_coverage_does_not_reopen_metadata_for_an_attributed_claim():
    s=source();coverage=dict(coverage_complete=False,attribution_only_allowed=True,
                            source_uses={s['source_id']:['attributed_content']})
    assert not metadata_check_required(s,coverage,'issued_version')
    assert not metadata_check_required(s,coverage,'provenance')
    assert metadata_check_required(s,coverage,'transcription')
    assert metadata_check_required({**s,'source_id':'uncovered'},coverage,'issued_version')
    assert metadata_check_required(s,{**coverage,'attribution_only_allowed':False},'issued_version')


def test_metadata_scope_does_not_merge_files_with_the_same_office_number():
    a={**source(),'chunk_id':'a:1','source_id':'a','title':'Oficio 00988-2026'}
    b={**a,'chunk_id':'b:1','source_id':'b','sha256':'different'}
    pending=normalize_item(request(),dict(kind='clarification',description='Revisar el Oficio 00988-2026.',
        reason_code='issued_version',linked_chunk_ids=['a:1'],linked_source_ids=['a','b']),[a,b])
    assert pending['linked_source_ids']==['a']
    assert [s['source_id'] for s in pending['source_versions']]==['a']


@pytest.mark.parametrize('choice',['issued','draft','provenance_reviewed'])
def test_quick_decision_records_exact_version_without_extra_evidence(draft_app,choice):
    app,client,_,_=draft_app;case,_=prepared_case(app,count=1)
    app.state.reviews.preparation=SimpleNamespace(decision_saved=lambda case_id: None) # no AI
    run=app.state.library.latest_run(case['id']);s=run['results'][0]['supports'][0]
    reason='provenance' if choice=='provenance_reviewed' else 'issued_version'
    run['results'][0]['missing']=[dict(kind='clarification',description='Comprobar este archivo.',
        reason_code=reason,basis='metadata_only',linked_source_ids=[s['source_id']],linked_chunk_ids=[s['chunk_id']])]
    app.state.library.save_run(run)
    app.state.reviews.start(case['id'],case['version'],before_draft=True)
    row=app.state.reviews.get(case['id'])['requests'][0];p=row['pending'][0]
    url=f"/api/cases/{case['id']}/review/requests/P1"
    body=dict(revision=row['revision'],edited_by='Persona de prueba',paragraphs=[],pending_resolutions=[dict(
        pending_id=p['id'],action='resolved',document_decision=choice,document_source_id=s['source_id'])])
    result=client.put(url,json=body)
    assert result.status_code==200,result.text
    saved=result.json();decision=saved['pending'][0]['resolution']
    assert decision['document_decision']==choice and decision['by']=='Persona de prueba'
    assert decision['cited_chunk_ids']==[s['chunk_id']]
    assert decision['document_version']['source_id']==s['source_id']
    assert not saved['approval'] and not saved['paragraphs']
    assert client.put(url,json=body).status_code==409


def test_quick_decision_rejects_wrong_document_and_known_draft():
    s={**source(),'title':'Oficio XXXX-2026','document_status':'draft'}
    row={'available_supports':[s]};p=dict(reason_code='issued_version',linked_chunk_ids=[s['chunk_id']])
    d=dict(document_decision='issued',document_source_id=s['source_id'])
    with pytest.raises(ValueError,match='borrador'):canonical_document_decision(row,p,d)
    with pytest.raises(ValueError,match='archivo exacto'):
        canonical_document_decision(row,p,{**d,'document_source_id':'other'})
    with pytest.raises(ValueError,match='solo corresponde'):
        canonical_document_decision(row,{**p,'reason_code':'fact_confirmation'},d)
