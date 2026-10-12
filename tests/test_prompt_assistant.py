import json

import pytest

from studio.llm import FakeLLM, LLMError
from studio.prompt_assistant import FIELDS, suggest_direction


def response():
    return {**{key: 'Clear direction' for key in FIELDS}, 'assumptions': [], 'questions': []}


def test_context_and_preferences():
    llm = FakeLLM([response()])
    result = suggest_direction(llm, {'request': 'Тихий город', 'loop': True, 'music': 'none',
                                   'notes': 'Keep the camera still', 'api_key': 'not context'}, 'Photoreal')
    system, user = llm.calls[0]
    assert 'Photoreal' in system
    assert json.loads(user)['loop'] is True
    assert json.loads(user)['music'] == 'none'
    assert 'api_key' not in user
    assert result == response()


@pytest.mark.parametrize('body', [None, [], {}, {'request': ''}, {'request': 42}, {'request': 'x' * 12001}])
def test_invalid_request_does_not_call_model(body):
    llm = FakeLLM()
    with pytest.raises(ValueError):
        suggest_direction(llm, body)
    assert not llm.calls


@pytest.mark.parametrize('change', [{'camera': None}, {'questions': 'oops'}, {'assumptions': [42]}])
def test_invalid_model_output(change):
    with pytest.raises(LLMError):
        suggest_direction(FakeLLM([{**response(), **change}]), {'request': 'City'})
