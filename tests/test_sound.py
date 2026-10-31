"""Звуковая студия: схема, подгонка реплик, фоли-промпт, сведение стемов и полный прогон pod-стороны."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

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
    assert again.sound.voices == "qwen" and again.sound.level("model") == 0.45
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


def test_align_to_speech_moves_line_onto_model_speech():
    plan = _plan()
    s = plan.shots[0]
    s.seconds = 6.042
    durs = {("001", 0): 2.4}
    notes = sound.align_to_speech(s, [[0.3, 0.6], [3.3, 5.4]], durs, {("001", 0): 0.3})
    assert s.dialogue[0].at == 3.0 and notes                 # смешок 0.3 с пропущен, речь TTS начинается в 3.3
    sound.align_to_speech(s, [[5.0, 6.0]], durs)
    assert s.dialogue[0].at == round(6.042 - 2.4 - 0.1, 2)   # не вылезает за конец сцены
    s.dialogue[0].on_screen = False
    s.dialogue[0].at = 1.0
    sound.align_to_speech(s, [[3.3, 5.4]], durs)
    assert s.dialogue[0].at == 1.0                           # голос из-за кадра не двигаем


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
    manifest = {"shots": {"001": {"lines": [{"file": "lines/a.wav", "at": 1.0}], "foley": "foley.wav",
                                  "model_speech": [[3.3, 5.4]]},
                          "002": {"lines": [], "foley": None, "model_speech": [[1.0, 2.0]]}}}
    st = sound.stems_for(plan, "001", tmp_path, manifest)
    assert st["model"] == 0.45 and st["voices"][0][1:] == (1.0, 1.0) and st["foley"][0][2] == 0.7
    assert st["mute"] == [(3.3, 5.4)]                                          # «речь» LTX вырезана из подложки
    st2 = sound.stems_for(plan, "002", tmp_path, manifest)
    assert st2["model"] == 1.0 and st2["mute"] == []                            # без фоли и реплик звук LTX целиком
    assert sound.stems_for(plan, "001", tmp_path, manifest, {"model": 0.3})["model"] == 0.3
    assert sound.stems_for(_plan(sound=None), "001", tmp_path, manifest)["voices"] == []


@needs_ffmpeg
def test_film_py_sound_studio_end_to_end(tmp_path):
    plan = _plan(sound={"voices": "qwen", "lipsync": True}).to_dict()
    plan_path = tmp_path / "zvuk.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    fake = f"{sys.executable} {ROOT / 'tests' / 'fake_audio.py'}"
    env = dict(os.environ, LTX_TEST_CMD=f"bash {ROOT / 'tests' / 'fake_ltx.sh'}", FILM_QUALITY="high",
               FILM_DIR=str(tmp_path / "proj"), FILM_RETRIES="1", VOICES_DIR=str(tmp_path / "voices"),
               TTS_TEST_CMD=f"{fake} tts", FOLEY_TEST_CMD=f"{fake} foley", MUSIC_TEST_CMD=f"{fake} music",
               VAD_TEST_CMD=f"{fake} vad", LATENTSYNC_TEST_CMD=f"{fake} latentsync")
    r = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    proj = tmp_path / "proj"
    report = json.loads((proj / "report.json").read_text(encoding="utf-8"))
    assert report["sound"] == {"lines": 1, "lipsync": ["001"], "foley": ["001", "002"], "score": True}
    by_id = {s["id"]: s for s in report["shots"]}
    assert "_lips_" in by_id["001"]["clip"] and by_id["001"]["clip_original"] != by_id["001"]["clip"]
    frames = lambda p: subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",  # noqa: E731
                                       "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", p],
                                      capture_output=True, text=True).stdout.strip()
    assert frames(by_id["001"]["clip"]) == frames(by_id["001"]["clip_original"])   # липсинк не меняет длину сцены
    manifest = sound.load_manifest(proj / "sound")
    line = manifest["shots"]["001"]["lines"][0]
    assert (proj / "sound" / line["file"]).exists()
    assert manifest["score"] and (proj / "sound" / manifest["score"]).exists()
    assert list((tmp_path / "voices" / "zvuk").glob("*.wav"))             # голос персонажа закэширован
    graph = (proj / "filter_complex.txt").read_text()
    assert "[vox" in graph and "sidechaincompress" in graph and "volume=0.450" in graph
    assert by_id["001"]["lipsync_engine"] == "latentsync" and manifest["shots"]["001"]["model_speech"] == [[1.5, 2.5]]
    assert manifest["shots"]["001"]["lines"][0]["at"] == 1.5                 # реплика встала на «речь» LTX
    assert "_clean_" in manifest["shots"]["001"]["foley"] and "_clean_" not in manifest["shots"]["002"]["foley"]
    assert "between(t,1.40,2.65)" in graph                                   # и эта «речь» вырезана из подложки
    # повторный запуск: ни TTS, ни липсинк, ни фоли не пересчитываются
    r2 = subprocess.run([sys.executable, str(ROOT / "remote" / "film.py"), str(plan_path)], env=env,
                        capture_output=True, text=True, timeout=600)
    assert r2.returncode == 0
    assert "озвучиваю" not in r2.stdout and "Липсинк сцены" not in r2.stdout and "Фоли и эмбиент" not in r2.stdout


def test_fill_gaps_replaces_speech_with_neighbouring_texture():
    np = pytest.importorskip("numpy")
    import importlib.util
    spec = importlib.util.spec_from_file_location("vad_worker", ROOT / "remote" / "audio" / "vad_worker.py")
    vw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vw)
    sr = 1000
    rain = np.random.default_rng(0).normal(0, 0.1, (3 * sr, 1)).astype(np.float32)
    x = rain.copy()
    x[1200:1800] += 0.8 * np.sin(np.arange(600) / 5)[:, None]          # «бормотание» поверх дождя
    gaps = vw.merge([[1.2, 1.8]], 0.05, 3.0)
    y = vw.fill_gaps(x, sr, gaps)
    assert gaps == [[1.15, 1.85]]
    assert abs(float(y[1300:1700].std()) - 0.1) < 0.03                    # в окне снова дождь той же силы
    assert np.allclose(y[:1100], x[:1100]) and np.allclose(y[1900:], x[1900:])   # вне окна ничего не тронуто
    assert vw.merge([[0.0, 1.0], [1.1, 2.0]], 0.1, 1.5) == [[0.0, 1.5]]


def test_elevenlabs_line_files_fall_back_to_qwen_and_carry_delivery(tmp_path):
    from studio.audio import eleven_text
    plan = _plan(sound={"voices": "elevenlabs"})
    s = plan.shots[0]
    qwen = tmp_path / sound.line_name(plan, s, 0, "qwen")
    assert sound.line_path(plan, s, 0, tmp_path) == qwen                       # записи ElevenLabs нет — Qwen
    eleven = tmp_path / sound.line_name(plan, s, 0, "elevenlabs")
    eleven.write_bytes(b"x")
    assert sound.line_path(plan, s, 0, tmp_path) == eleven
    assert sound.tts_job(plan, tmp_path, tmp_path)["lines"] == []              # Qwen не переозвучивает готовое
    s.dialogue[0].delivery = "warmly"
    assert sound.line_name(plan, s, 0, "elevenlabs") != eleven.name           # новая подача — новая запись
    assert eleven_text("Привет.", "warmly", "eleven_v4") == "[warmly] Привет."
    assert eleven_text("Привет.", "warmly", "eleven_multilingual_v2") == "Привет."
    assert sound.voice_key(plan, "Анна").startswith("anna_")
