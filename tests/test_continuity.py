"""Связность сцен: якорь мира в каждом промпте, леджер состояний между актами, линтер."""
from studio.lint import lint_plan
from studio.llm import FakeLLM
from studio.planner import Planner, PlanRequest, ensure_anchor, inject_anchor, ledger
from studio.schema import Plan, Shot
from tests.test_lint import GOOD

ANCHOR = "A narrow wooden pier at night in a storm, black sea behind, lit only by a swinging brass lantern, cold teal shadows with warm amber highlights, shot on a 35mm cinema lens with fine grain."


def test_inject_anchor_after_first_sentence_and_idempotent():
    body = "Extreme close-up on weathered hands gripping a brass lantern. The flame flickers. Sound: rain."
    out = inject_anchor(body, ANCHOR)
    assert out.startswith("Extreme close-up on weathered hands gripping a brass lantern. A narrow wooden pier")
    assert out.endswith("Sound: rain.")
    assert inject_anchor(out, ANCHOR) == out                       # повторно не вставляется
    assert inject_anchor(out, ANCHOR.rstrip(".")) == out            # и без точки на конце тоже
    assert inject_anchor("no punctuation at all", ANCHOR).endswith(ANCHOR)


def test_ensure_anchor_on_plan_and_lint_flags_missing():
    plan = Plan(title="t", style={"anchor": ANCHOR}, shots=[Shot("001", 5, GOOD), Shot("002", 5, GOOD)])
    codes = {(i.shot_id, i.code) for i in lint_plan(plan)}
    assert ("001", "anchor_missing") in codes and ("002", "anchor_missing") in codes
    ensure_anchor(plan)
    assert all(ANCHOR in s.prompt for s in plan.shots)
    assert not any(i.code == "anchor_missing" for i in lint_plan(plan))


def test_descriptor_missing_is_an_error_when_characters_defined():
    pronoun_prompt = GOOD.replace("an old fisherman with a wet grey beard, yellow oilskin coat and a brass lantern", "the man")
    plan = Plan(title="t", characters=[{"name": "Старик", "descriptor": "an old fisherman with a wet grey beard, yellow oilskin coat and a brass lantern"}],
                shots=[Shot("001", 5, pronoun_prompt)])
    issues = [i for i in lint_plan(plan) if i.code == "descriptor_missing"]
    assert issues and issues[0].level == "error"


def test_ledger_and_history_reach_next_act():
    history = [{"beat": "старик зажигает фонарь", "seconds": 8, "direction": {"start": "s", "end": "the fisherman stands at the pier end, lantern raised, soaked"}},
               {"beat": "волна", "seconds": 5, "direction": {"end": "he kneels, lantern on the boards, hair dripping"}}]
    led = ledger(history)
    assert led[1] == {"n": 2, "beat": "волна", "seconds": 5, "end": "he kneels, lantern on the boards, hair dripping"}
    llm = FakeLLM(responses=[{"shots": []}])
    Planner(llm, log=lambda *_: None)._write_act("system", PlanRequest(request="x"), {"acts": []},
                                                  {"name": "Финал", "seconds": 8, "beats": ["свет"]}, 1, history[-2:], True,
                                                  history=history)
    user = llm.calls[0][1]
    assert "STATE LEDGER OF ALL EARLIER SHOTS" in user and "lantern on the boards" in user
    assert "LAST SHOTS OF THE PREVIOUS ACT IN FULL" in user


def test_no_start_state_warning():
    plan = Plan(title="t", shots=[Shot("001", 5, GOOD, direction={"end": "x"}), Shot("002", 5, GOOD, direction={"action": "y"})])
    assert any(i.code == "no_start_state" and i.shot_id == "002" for i in lint_plan(plan))
