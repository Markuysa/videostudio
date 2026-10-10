import pytest

from studio.llm import FakeLLM, LLMError
from studio.planner import Planner, PlanRequest
from studio.schema import Plan, Shot
from tests.test_lint import GOOD


def test_original_request_and_loop_opening_reach_later_acts():
    llm = FakeLLM(responses=[{'shots': []}])
    planner = Planner(llm, log=lambda *_: None)
    req = PlanRequest(request='Красный корабль, без людей', notes='Камера неподвижна', loop=True)
    planner._write_act('system', req, {'acts': [], 'creative_brief': {'must_keep': ['red ship']}},
                       {'name': 'Return', 'seconds': 5, 'beats': ['Return']}, 1, [], True,
                       opening={'prompt': 'opening composition'})
    user = llm.calls[0][1]
    assert req.request in user and req.notes in user
    assert 'opening composition' in user and 'red ship' in user


def test_director_review_preserves_timing_and_persists_brief(tmp_path):
    plan = Plan(title='x', request='Keep the red ship', creative_brief={'avoid': ['people']},
                shots=[Shot('001', 4, GOOD)])
    corrected = GOOD.replace('rain', 'drizzle')
    llm = FakeLLM(responses=[{'shots': [{'id': '001', 'prompt': corrected, 'seconds': 999}],
                             'notes': ['Нужен опорный кадр корабля.']}])
    Planner(llm, log=lambda *_: None).director_review(plan)
    assert plan.shots[0].seconds == 4 and plan.shots[0].prompt == corrected
    assert 'Keep the red ship' in llm.calls[0][1] and 'people' in llm.calls[0][1]
    restored = Plan.from_dict(plan.to_dict())
    assert restored.creative_brief == plan.creative_brief
    assert restored.review_notes == plan.review_notes


def test_director_review_rejects_unknown_ids_atomically():
    plan = Plan(title='x', shots=[Shot('001', 4, GOOD)])
    llm = FakeLLM(responses=[{'shots': [{'id': '001', 'prompt': 'replacement'},
                                      {'id': 'alien', 'prompt': 'invalid'}], 'notes': []}])
    with pytest.raises(LLMError):
        Planner(llm, log=lambda *_: None).director_review(plan)
    assert plan.shots[0].prompt == GOOD


def test_director_review_batches_long_films():
    shots = [Shot(str(i), 4, GOOD) for i in range(13)]
    llm = FakeLLM(responses=[{'shots': [], 'notes': []}, {'shots': [], 'notes': []}])
    Planner(llm, log=lambda *_: None).director_review(Plan(title='x', shots=shots))
    assert len(llm.calls) == 2
    assert 'previous' in llm.calls[1][1] and 'opening' in llm.calls[1][1]
