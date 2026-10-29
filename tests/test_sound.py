"""Звуковая студия: схема, подгонка реплик, фоли-промпт, сведение стемов и полный прогон pod-стороны."""
import json
import os
import pathlib
import subprocess
import sys

from tests.conftest import ROOT, needs_ffmpeg

from studio import sound
from studio.lint import lint_plan
from studio.schema import Plan, validate

CHARS = [{"name": "Анна", "descriptor": "the young woman with auburn hair", "voice": "Woman, 28, warm husky alto"}]


def _plan(**kw) -> Plan:
    d = {"title": "Звук", "format": "9:16", "quality": "high", "seed": 1, "language": "ru", "characters": CHARS,
         "sound": {"voices": "qwen"},
         "shots": [{"id": "001", "seconds": 4, "prompt": "Medium close-up of the young woman with auburn hair at a "
                    "counter, she looks up and says in Russian: \"Спасибо, Рыжик.\" Sound: a ceramic scrape on oak, "
                    "her warm whisper, a quiet sip.",
                    "dialogue": [{"speaker": "Анна", "text": "Спасибо, Рыжик.", "at": 1.0}],
                    "foley": "a ceramic cup scraping on oak, a quiet sip, cafe room tone"},
                   {"id": "002", "seconds": 3, "prompt": "Wide shot of a rainy street, heavy rain drumming on awnings. "
                    "Sound: loud heavy rain, distant thunder."}]}
    d.update(kw)
    return Plan.from_dict(d)


def test_schema_roundtrip_keeps_dialogue_and_sound():
    plan = _plan()
    again = Plan.from_dict(json.loads(json.dumps(plan.to_dict(), ensure_ascii=False)))
    assert again.sound.voices == "qwen" and again.sound.level("model") == 0.0
    assert again.shots[0].dialogue[0].speaker == "Анна" and again.shots[0].dialogue[0].on_screen
    assert again.shots[0].foley.startswith("a ceramic")
    assert "dialogue" not in again.to_dict()["shots"][1]          # пустые поля не пишутся
    assert validate(again) == []
    assert Plan.from_dict({**plan.to_dict(), "sound": None}).sound is None


def test_validate_and_lint_catch_dialogue_problems():
    plan = _plan()
    plan.shots[0].dialogue[0].at = 9.0
    plan.sound.voices = "robot"
    problems = validate(plan)
    assert any("вне сцены" in p for p in problems) and any("sound.voices" in p for p in problems)
    plan = _plan()
    plan.shots[0].dialogue[0].speaker = "Призрак"
    plan.shots[0].dialogue.append(type(plan.shots[0].dialogue[0])(speaker="Анна", text="Этого нет в промпте"))
    codes = {i.code for i in lint_plan(plan)}
    assert {"unknown_speaker", "line_not_in_prompt"} <= codes


def test_fit_dialogue_extends_shot_and_separates_lines():
    plan = _plan()
    s = plan.shots[0]
    s.dialogue.append(type(s.dialogue[0])(speaker="Анна", text="Ещё одна реплика", at=1.2))
    notes = sound.fit_dialogue(plan, {("001", 0): 2.0, ("001", 1): 2.5}, high=True)
    assert s.dialogue[1].at >= 3.0                         # вторая реплика не наезжает на первую
    assert s.seconds >= s.dialogue[1].at + 2.5 and any("удлинена" in n for n in notes)
    assert (s.frames - 1) % 8 == 0                          # длина осталась на сетке LTX
    win = sound.lipsync_window(s, {("001", 0): 2.0, ("001", 1): 2.5})
    assert win[0] == 0.7 and win[1] <= s.seconds


def test_foley_prompt_drops_speech_and_quotes():
    plan = _plan()
    assert sound.foley_prompt(plan.shots[0]) == plan.shots[0].foley
    plan.shots[0].foley = None
    fp = sound.foley_prompt(plan.shots[0])
    assert "Рыжик" not in fp and "whisper" not in fp and "ceramic scrape" in fp
    assert "heavy rain" in sound.foley_prompt(plan.shots[1])


def test_voice_key_is_stable_and_tts_job_casts_each_speaker_once(tmp_path):
    plan = _plan()
    job = sound.tts_job(plan, tmp_path / "lines", tmp_path / "voices")
    assert list(job["voices"]) == ["Анна"] and job["voices"]["Анна"]["instruct"].startswith("Woman")
    assert job["voices"]["Анна"]["cache"].endswith(sound.voice_key(plan, "Анна") + ".wav")
    assert len(job["lines"]) == 1 and job["lines"][0]["out"].endswith(".wav")
    other = _plan(characters=[{**CHARS[0], "voice": "Man, 60, deep baritone"}])
    assert sound.voice_key(other, "Анна") != sound.voice_key(plan, "Анна")


def test_stems_mute_model_audio_only_when_foley_exists(tmp_path):
    plan = _plan()
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "a.wav").write_bytes(b"x")
    (tmp_path / "foley.wav").write_bytes(b"x")
    manifest = {"shots": {"001": {"lines": [{"file": "lines/a.wav", "at": 1.0}], "foley": "foley.wav"},
                          "002": {"lines": [], "foley": None}}}
    st = sound.stems_for(plan, "001", tmp_path, manifest)
    assert st["model"] == 0.0 and st["voices"][0][1:] == (1.0, 1.0) and st["foley"][0][2] == 0.7
    assert sound.stems_for(plan, "002", tmp_path, manifest)["model"] == 1.0     # без фоли звук LTX остаётся
    assert sound.stems_for(plan, "001", tmp_path, manifest, {"model": 0.3})["model"] == 0.3
    assert sound.stems_for(_plan(sound=None), "001", tmp_path, manifest) == {"voices": [], "foley": [], "model": 1.0}


@needs_ffmpeg
def test_film_py_sound_studio_end_to_end(tmp_path):
    plan = _plan().to_dict()
    plan_path = tmp_path / "zvuk.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    fake = f"{sys.executable} {ROOT / 'tests' / 'fake_audio.py'}"
    env = dict(os.environ, LTX_TEST_CMD=f"bash {ROOT / 'tests' / 'fake_ltx.sh'}", FILM_QUALITY="high",
               FILM_DIR=str(tmp_path / "proj"), FILM_RETRIES="1", VOICES_DIR=str(tmp_path / "voices"),
               TTS_TEST_CMD=f"{fake} tts", FOLEY_TEST_CMD=f"{fake} foley", MUSIC_TEST_CMD=f"{fake} music")
    r = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    proj = tmp_path / "proj"
    report = json.loads((proj / "report.json").read_text(encoding="utf-8"))
    assert report["sound"] == {"lines": 1, "lipsync": ["001"], "foley": ["001", "002"], "score": True}
    by_id = {s["id"]: s for s in report["shots"]}
    assert "_lips_" in by_id["001"]["clip"] and by_id["001"]["clip_original"] != by_id["001"]["clip"]
    manifest = sound.load_manifest(proj / "sound")
    line = manifest["shots"]["001"]["lines"][0]
    assert (proj / "sound" / line["file"]).exists() and line["at"] == 1.0
    assert manifest["score"] and (proj / "sound" / manifest["score"]).exists()
    assert list((tmp_path / "voices" / "zvuk").glob("*.wav"))             # голос персонажа закэширован
    graph = (proj / "filter_complex.txt").read_text()
    assert "[vox" in graph and "sidechaincompress" in graph and "volume=0.000" in graph
    # повторный запуск: ни TTS, ни липсинк, ни фоли не пересчитываются
    r2 = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                        capture_output=True, text=True, timeout=600)
    assert r2.returncode == 0
    assert "озвучиваю" not in r2.stdout and "Липсинк сцены" not in r2.stdout and "Фоли и эмбиент" not in r2.stdout
