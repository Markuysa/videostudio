"""Motion mode uses the existing plan/render contract and targeted repair pipeline."""
from studio.knowledge import KIND_PRESETS, MOTION_PROMPT_RULES
from studio.lint import lint_plan
from studio.llm import FakeLLM
from studio.planner import Planner, PlanRequest, system_prompt
from studio.schema import KINDS, Plan, Shot, load_plan, validate
from tests.test_lint import GOOD

MOTION = MOTION_PROMPT_RULES.split('Example of a single clip prompt:\n')[1].strip().replace('\n', ' ')


def test_motion_roundtrip_and_checks(tmp_path):
    plan = Plan(title='Discs', kind='motion', shots=[Shot('001', 5, MOTION)])
    assert validate(plan) == []
    assert lint_plan(plan) == []
    plan.save(tmp_path / 'motion.json')
    assert load_plan(tmp_path / 'motion.json').kind == 'motion'
    assert set(KINDS) == set(KIND_PRESETS)


def test_motion_checks_do_not_affect_film():
    prompt = 'A static camera frames a coral disc on an ivory background. Uniform light. Silence.'
    shot = Shot('001', 5, prompt)
    expected = {'motion_action', 'motion_timing', 'motion_end_state'}
    assert expected <= {i.code for i in lint_plan(Plan(title='x', kind='motion', shots=[shot]))}
    assert not expected & {i.code for i in lint_plan(Plan(title='x', kind='film', shots=[shot]))}


def test_motion_planning_and_automatic_repair():
    outline = {'title': 'Discs', 'style': {'visual': 'flat graphic animation'},
               'acts': [{'name': 'Compose', 'seconds': 6, 'beats': ['Discs assemble']}]}
    llm = FakeLLM(responses=[outline, {'shots': [{'seconds': 6, 'prompt': GOOD}]},
                             {'shots': [], 'notes': []},
                             {'shots': [{'id': '001', 'prompt': MOTION, 'seconds': 6}]}])
    plan = Planner(llm, log=lambda *_: None).plan(PlanRequest(request='Три диска', kind='motion', seconds=6))
    assert plan.kind == 'motion' and plan.format == '16:9'
    assert not plan.captions.enabled
    assert plan.shots[0].prompt == MOTION
    assert len(llm.calls) == 4
    assert all('MOTION DESIGN' in call[0] for call in llm.calls)
    assert not lint_plan(plan)


def test_review_retains_motion_and_loop_instructions():
    plan = Plan(title='Discs', kind='motion', loop=True, shots=[Shot('001', 5, GOOD)])
    llm = FakeLLM(responses=[{'shots': [{'id': '001', 'prompt': MOTION}]}])
    Planner(llm, log=lambda *_: None).refine(plan)
    assert 'MOTION DESIGN' in llm.calls[0][0]
    assert 'LOOP MODE' in llm.calls[0][0]
    assert 'MOTION DESIGN' not in system_prompt(PlanRequest(request='film'), True)
