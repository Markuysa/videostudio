import json

from studio.llm import FakeLLM, extract_json
from studio.planner import PlanRequest, Planner, plan_summary
from studio.schema import validate
from tests.test_lint import GOOD

OUTLINE = {
    "title": "Красный зонт", "logline": "Девушка ищет кота в неоновом Токио.", "synopsis": "Дождь. Поиск. Встреча.",
    "style": {"anchor": "A narrow neon-lit Tokyo alley at night in heavy rain, wet black asphalt doubling every sign, "
                        "cold teal shadows with magenta highlights, shot on an anamorphic lens with fine grain.",
              "visual": "neon rain", "palette": "red, teal", "lens": "anamorphic", "lighting": "neon", "camera": "slow",
              "sound": "rain", "pace": "slow"},
    "characters": [{"name": "Старик", "descriptor": "an old fisherman with a wet grey beard, yellow oilskin coat and a brass lantern",
                    "description": "x", "voice": "hoarse"}],
    "locations": [{"name": "Улица", "descriptor": "a narrow neon-lit Tokyo alley"}],
    "music": {"file": "assets/music/lofi_rain.mp3", "mood": "lo-fi", "volume": 0.25, "duck": True},
    "acts": [{"name": "Поиск", "seconds": 16, "beats": ["Мика идёт по улице", "Кот под навесом"]},
             {"name": "Встреча", "seconds": 8, "beats": ["Мика берёт кота"]}],
}
BAD_PROMPT = "She walks. Rain falls."


def shots_response(n, first_bad=False):
    shots = []
    for i in range(n):
        shots.append({"beat": f"beat {i}", "seconds": 8, "transition": "cut" if i == 0 else "continue",
                      "prompt": BAD_PROMPT if (first_bad and i == 0) else GOOD, "caption": "Токио", "narration": None,
                      "sfx": [{"file": "assets/sfx/thunder.wav", "offset": 1.0, "volume": 0.7}]})
    return {"shots": shots}


def test_extract_json_variants():
    assert extract_json('```json\n{"a": [1, 2,]}\n```') == {"a": [1, 2]}
    assert extract_json('Here you go: {"b": {"c": "d"}} thanks') == {"b": {"c": "d"}}


def test_planner_builds_valid_plan_and_fixes_bad_prompt():
    library = {"music": [{"file": "assets/music/lofi_rain.mp3", "tags": ["lofi"]}],
               "sfx": [{"file": "assets/sfx/thunder.wav", "tags": ["thunder"]}]}
    llm = FakeLLM(responses=[
        OUTLINE,                                   # outline
        shots_response(2, first_bad=True),         # act 1
        shots_response(1),                         # act 2
        {"shots": [], "notes": []},                 # director review
        {"shots": [{"id": "001", "prompt": GOOD, "seconds": 8, "caption": "Токио"}]},   # revise
    ])
    req = PlanRequest(request="Эстетичный шортс про Токио", kind="aesthetic", seconds=24, quality="high",
                      library=library, captions=True, seed=7)
    plan = Planner(llm, log=lambda *_: None).plan(req)
    assert plan.title == "Красный зонт" and plan.kind == "aesthetic" and plan.format == "9:16"
    assert [s.id for s in plan.shots] == ["001", "002", "003"]
    assert plan.shots[0].transition == "cut" and plan.shots[1].transition == "continue"
    assert plan.shots[0].prompt.startswith(GOOD.split(". ")[0] + ".")   # исправлено раундом правок
    assert all("Tokyo alley at night in heavy rain" in s.prompt for s in plan.shots)   # якорь мира в каждой сцене
    assert plan.music and plan.music.file == "assets/music/lofi_rain.mp3"
    assert plan.shots[0].sfx[0].file == "assets/sfx/thunder.wav"
    assert plan.captions.enabled and plan.shots[0].caption == "Токио"
    assert validate(plan, "high") == []
    assert len(llm.calls) == 5
    # системный промпт содержит правила LTX и библиотеку
    system = llm.calls[0][0]
    assert "LTX-2.5" in system and "lofi_rain.mp3" in system
    assert "Красный зонт" in plan_summary(plan)


def test_planner_rescales_duration_and_drops_unknown_sfx():
    llm = FakeLLM(responses=[OUTLINE, shots_response(2), shots_response(1), {"shots": [], "notes": []}])
    req = PlanRequest(request="x", kind="aesthetic", seconds=60, quality="fast", library=None, music="none")
    plan = Planner(llm, log=lambda *_: None).plan(req)
    total = sum(s.seconds for s in plan.shots)
    assert 45 <= total <= 66          # 3 сцены по 8 с растянуты к 60 с, с учётом лимитов
    assert plan.music is None and all(not s.sfx for s in plan.shots)
    assert all(s.frames <= 481 for s in plan.shots)
