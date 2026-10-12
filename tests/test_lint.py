from studio.lint import errors_only, lint_plan, lint_shot
from studio.schema import Plan, Shot

GOOD = ("Extreme close-up on the weathered hands of an old fisherman with a wet grey beard, yellow oilskin coat and a "
        "brass lantern, as rain hammers the brass handle. The flame flickers, almost dies, then flares back as he "
        "tightens his grip. The camera slowly pulls back to reveal his face and his eyes fixed on the dark sea, cold "
        "blue overcast light with a warm orange glow from the lantern on his cheek. Sound: torrential rain on wood, "
        "wind howling across the pier, the metallic creak of the swinging lantern, then he whispers in a hoarse voice: "
        "\"I'll wait.\"")


def test_good_prompt_passes():
    issues = lint_shot(Shot(id="1", seconds=8, prompt=GOOD), high=True)
    assert errors_only(issues) == []


def test_detects_missing_camera_and_sound():
    p = " ".join(["A man stands near the sea and waits for a long time while the storm rages around him."] * 6)
    codes = {i.code for i in lint_shot(Shot(id="1", seconds=8, prompt=p), high=True)}
    assert {"no_camera", "no_sound"} <= codes


def test_detects_cyrillic_and_formatting():
    p = "Shot 1: Старик стоит на пирсе.\nShot 2: wide shot, sound of rain " + "detail " * 60
    codes = {i.code for i in lint_shot(Shot(id="1", seconds=8, prompt=p), high=True)}
    assert {"language", "formatting"} <= codes


def test_russian_dialogue_in_quotes_is_only_warning():
    p = GOOD.replace('"I\'ll wait."', '"Я подожду."')
    issues = lint_shot(Shot(id="1", seconds=8, prompt=p), high=True)
    lang = [i for i in issues if i.code == "language"]
    assert lang and lang[0].level == "warn"


def test_plan_level_short_hook():
    shots = [Shot(id="1", seconds=8, prompt=GOOD), Shot(id="2", seconds=5, prompt=GOOD)]
    plan = Plan(title="t", shots=shots, kind="short")
    assert any(i.code == "hook" for i in lint_plan(plan, "high"))


def test_warns_about_long_conditioned_shot_in_high(storm_plan):
    issues = lint_plan(storm_plan, "high")
    assert any(i.code == "dfr_conditioned_length" and i.shot_id == "002" for i in issues)
    assert not any(i.code == "dfr_conditioned_length" for i in lint_plan(storm_plan, "fast"))


def test_hissy_sound_words_are_flagged():
    bad = GOOD.replace("torrential rain on wood", "rain hissing on the lake")
    assert any(i.code == "hissy_sound" for i in lint_shot(Shot(id="1", seconds=8, prompt=bad), high=True))
    assert not any(i.code == "hissy_sound" for i in lint_shot(Shot(id="1", seconds=8, prompt=GOOD), high=True))


def test_quiet_main_sound_is_flagged():
    quiet = GOOD.replace("Sound: torrential rain on wood", "Sound: soft rain on wood")
    assert any(i.code == "quiet_sound" for i in lint_shot(Shot(id="1", seconds=8, prompt=quiet), high=True))
    assert not any(i.code == "quiet_sound" for i in lint_shot(Shot(id="1", seconds=8, prompt=GOOD), high=True))
