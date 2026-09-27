from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from pqrs_claro.intake_engine import OpenAIIntakeEngine
from pqrs_claro.models import DomainError


@pytest.mark.parametrize(('request_count', 'output_limit'), [(1, 4000), (3, 7000), (200, 22000)])
def test_incomplete_provider_json_becomes_controlled_error(request_count, output_limit):
    class Output(BaseModel):
        complete: bool

    def invalid(**kwargs):
        assert kwargs['max_output_tokens'] == output_limit
        try:
            Output.model_validate_json('{')
        except ValidationError as exc:
            raise exc

    engine = object.__new__(OpenAIIntakeEngine)
    engine.model = 'test'
    engine.instructions = 'test'
    engine.context_only = False
    engine.output_schema = Output
    engine.client = SimpleNamespace(responses=SimpleNamespace(parse=invalid))
    with pytest.raises(DomainError, match='incompleta o inválida'):
        engine.assess({'pages': [], 'identification': {'requests': [{}] * request_count}})
