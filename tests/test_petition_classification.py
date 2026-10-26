# ruff: noqa: F811
"""Type-only classification preserves prior checks and the human review gate."""

import copy
from types import SimpleNamespace

import pytest
from test_initial_review import analyze, decision, fiaga, wait_intake  # noqa: F401
from test_jev_intake import payload  # noqa: F401
from test_source_service_api import pdf_bytes  # noqa: F401

from pqrs_claro.config import Settings
from pqrs_claro.intake_engine import materialize
from pqrs_claro.models import DomainError
from pqrs_claro.petition_classification import (
    CLASSIFICATION_SCOPE,
    Classification,
    OpenAIPetitionClassifier,
    PetitionClassificationEngine,
)


def test_types_preserve_preanalysis_without_repeating_checks(payload):
    payload['scope'] = {'library_search': 'not_requested'}
    payload['preanalysis'] = {'checks': {
        'requester': {'state': 'attention', 'summary': 'Falta contacto.', 'refs': []},
        'respect': {'state': 'pass', 'summary': 'Lenguaje respetuoso.', 'refs': []},
        'integrity': {'state': 'pass', 'summary': 'Documento legible.', 'refs': []},
    }, 'approval': {'actor_id': 'gestor-1', 'notes': {'requester': 'Se revisó el original.'}}}
    before = copy.deepcopy(payload)
    classifier = SimpleNamespace(classify=lambda _: {
        'P1': {'choice': 'information'}, 'P2': {'choice': 'documents'}})
    engine = PetitionClassificationEngine(Settings(), classifier=classifier)
    report = materialize(engine.assess(payload), payload)
    assert payload == before
    assert [r['petition_type'] for r in report['requests']] == ['information', 'documents']
    assert report['document']['checks'][0]['state'] == 'attention'
    assert report['document']['checks'][0]['summary'] == 'Falta contacto.'
    assert not report['history_available']
    for row in report['requests']:
        assert row['checks'][0]['state'] == 'unavailable'
        assert row['checks'][0]['pending'] == []
        assert 'no consultados' in row['checks'][0]['summary']
        assert row['draft'] is None


@pytest.mark.parametrize('ids', [['P1', 'P2'], ['P1'], ['P1', 'P1']])
def test_openai_receives_only_original_petitions_and_requires_exact_coverage(payload, ids):
    seen = []

    def parse(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(status='completed', output_parsed=Classification(requests=[
            {'request_id': rid, 'petition_type': 'information'} for rid in ids]))

    classifier = OpenAIPetitionClassifier.__new__(OpenAIPetitionClassifier)
    classifier.model = 'fake'
    classifier.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    if ids == ['P1', 'P2']:
        assert set(classifier.classify(payload)) == {'P1', 'P2'}
    else:
        with pytest.raises(DomainError, match='exactamente'):
            classifier.classify(payload)
    assert 'Informar los requisitos.' in seen[0]['input']
    assert 'not trusted' not in seen[0]['input']
    assert 'candidates' not in seen[0]['input']
    assert 'preanalysis' not in seen[0]['input']


def test_service_classifies_without_catalog_and_keeps_human_gate(fiaga, pdf_bytes, monkeypatch):
    app, client, _, _ = fiaga
    case, prior = analyze(fiaga, pdf_bytes)
    service = app.state.initial_review
    original = copy.deepcopy(case['identification'])
    seen = []

    def classify(data):
        seen.append(data)
        return {r['id']: {'choice': 'information'} for r in data['identification']['requests']}

    def forbidden(*args, **kwargs):
        pytest.fail('Classification read the source library')

    service.engine = PetitionClassificationEngine(service.settings,
                                                  classifier=SimpleNamespace(classify=classify))
    with monkeypatch.context() as m:
        m.setattr(service.sources, 'catalog', forbidden)
        m.setattr(service.library, 'snapshot', forbidden)
        m.setattr(service.library, 'linked_collections', forbidden)
        prefix = f"/api/cases/{case['id']}/initial-review"
        response = client.post(prefix + '/analyze', json={
            'version': case['version'], 'revision': prior['revision'], 'mode': 'full'})
        assert response.status_code == 202, response.text
        row = wait_intake(app, client, case)
        assert row['status'] == 'needs_review', row
        assert row['analysis_scope'] == CLASSIFICATION_SCOPE
        assert not row['can_prepare'] and row['decisions'] is None
        assert row['consulted_sources'] == []
        assert not row['stale'] and row['next_analysis']['pending'] == []
        assert service.cases.get(case['id'])['identification'] == original
        assert service.cases.get(case['id'])['version'] == case['version']
        assert len(seen) == 1
        assert client.put(prefix + '/decision', json=decision(row)).status_code == 200
        assert client.get(prefix).json()['can_prepare']
    assert not app.state.preparation.active
    assert app.state.library.latest_run(case['id']) is None
