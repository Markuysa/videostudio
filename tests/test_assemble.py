import pathlib
import subprocess

import pytest

from studio.assemble import AssembleOptions, ClipSpec, build_graph, build_timeline, write_ass
from tests.conftest import needs_ffmpeg


def three_clips():
    return [ClipSpec("a.mp4", "001", caption="Привет"),
            ClipSpec("b.mp4", "002", transition="continue"),
            ClipSpec("c.mp4", "003", transition="dissolve", transition_seconds=0.5, sfx=[("s.wav", 1.0, 0.8)])]


def test_timeline_positions():
    segs = build_timeline(three_clips(), [8.04, 8.04, 5.04])
    assert segs[0].start == 0 and abs(segs[0].end - 8.04) < 1e-3
    assert abs(segs[1].duration - (8.04 - 1 / 24)) < 1e-3          # continue: минус дублирующийся кадр
    assert abs(segs[2].start - (segs[1].end - 0.5)) < 1e-3          # dissolve: начинается раньше на длину наплыва
    assert abs(segs[2].end - (8.04 + 8.04 - 1 / 24 + 5.04 - 0.5)) < 1e-3


def test_graph_structure():
    opts = AssembleOptions(704, 1280, music_path="m.mp3", captions=True, loudnorm=True)
    graph, segs, total = build_graph(three_clips(), [8.04, 8.04, 5.04], opts, [], "captions.ass")
    assert "xfade=transition=fade:duration=0.5" in graph
    assert "acrossfade=d=0.5" in graph
    assert "concat=n=2:v=1:a=0" in graph
    assert "sidechaincompress" in graph and "loudnorm" in graph
    assert "ass=captions.ass" in graph
    assert graph.count("adelay=") == 1
    assert "[vout]" in graph and "[aout]" in graph


def test_graph_without_music_or_sfx_is_simple():
    clips = [ClipSpec("a.mp4", "1"), ClipSpec("b.mp4", "2")]
    graph, _, _ = build_graph(clips, [5.0, 5.0], AssembleOptions(704, 1280, loudnorm=False), [], None)
    assert "amix" not in graph and "sidechain" not in graph and "loudnorm" not in graph


def test_ass_has_events_for_captions():
    segs = build_timeline(three_clips(), [8.04, 8.04, 5.04])
    ass = write_ass(segs, 1088, 1920)
    assert ass.count("Dialogue:") == 1 and "Привет" in ass and "PlayResY: 1920" in ass


@needs_ffmpeg
def test_real_assembly(tmp_path):
    from studio.assemble import assemble, probe
    clips = []
    for i, dur in enumerate((3.0, 3.0, 3.0)):
        p = tmp_path / f"c{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=size=320x576:rate=24:duration={dur}",
                        "-f", "lavfi", "-i", f"sine=frequency={300 * (i + 1)}:sample_rate=48000:duration={dur}",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
        clips.append(p)
    music = tmp_path / "m.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=110:sample_rate=48000:duration=2",
                    str(music)], check=True)
    specs = [ClipSpec(str(clips[0]), "1"), ClipSpec(str(clips[1]), "2", transition="continue"),
             ClipSpec(str(clips[2]), "3", transition="dissolve", transition_seconds=0.5, sfx=[(str(music), 0.5, 0.5)])]
    opts = AssembleOptions(320, 576, music_path=str(music))
    out = tmp_path / "film.mp4"
    rep = assemble(specs, out, opts, tmp_path / "work")
    info = probe(out)
    expected = 3.0 + (3.0 - 1 / 24) + 3.0 - 0.5
    assert abs(rep["seconds"] - expected) < 0.05
    assert abs(info["duration"] - expected) < 0.15
    assert info["has_audio"] and info["width"] == 320
    assert len(rep["timeline"]) == 3


def test_clip_gain_is_bounded_and_keeps_silence_quiet():
    from studio.assemble import clip_gain_db, loudnorm_filter
    assert clip_gain_db(-18.0) == 0.0
    assert clip_gain_db(-9.0) == -9.0                 # громкий клип приглушаем
    assert clip_gain_db(-50.0) == 18.0                # почти тишину не накачиваем до -18: максимум +18 дБ
    assert clip_gain_db(-40.0) == 18.0
    assert clip_gain_db(-2.0) == -12.0                # и не режем сильнее -12 дБ
    assert clip_gain_db(None) == 0.0
    fin = loudnorm_filter({"input_i": "-20.5", "input_tp": "-3.1", "input_lra": "7.2", "input_thresh": "-31.0"})
    assert fin.startswith("volume=+6.50dB,alimiter=")          # к -14 LUFS: -14 - (-20.5) = +6.5, пики в запасе лимитера
    hot = loudnorm_filter({"input_i": "-30.0", "input_tp": "+2.0"})
    assert hot.startswith("volume=+2.50dB")                    # усиление ограничено пиками: -1.5 - 2 + 6 = +2.5, а не +16
    assert loudnorm_filter(None).startswith("loudnorm=")       # без замеров — запасной однопроходный режим


def test_graph_applies_clip_gain_and_audio_only_mode():
    clips = [ClipSpec("a.mp4", "1", gain_db=-6.0), ClipSpec("b.mp4", "2", gain_db=0.02)]
    graph, _, _ = build_graph(clips, [5.0, 5.0], AssembleOptions(704, 1280), [], None)
    assert "volume=-6.0dB" in graph and "volume=+0.0dB" not in graph
    audio, _, _ = build_graph(clips, [5.0, 5.0], AssembleOptions(704, 1280), [], None, audio_only=True)
    assert "[vout]" not in audio and "xfade" not in audio and "[aout]" in audio and "loudnorm" not in audio


@needs_ffmpeg
def test_measure_loudness_on_synthetic_tone(tmp_path):
    from studio.assemble import measure_loudness
    p = tmp_path / "tone.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
                    "-af", "volume=-20dB", str(p)], check=True)
    lufs = measure_loudness(p)
    assert lufs is not None and -50 < lufs < -15      # моно-синус на -20 dBFS
    silent = tmp_path / "silent.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2", str(silent)], check=True)
    assert measure_loudness(silent) is None


def test_raw_mode_leaves_model_audio_untouched():
    clips = [ClipSpec("a.mp4", "1"), ClipSpec("b.mp4", "2")]
    graph, _, _ = build_graph(clips, [5.0, 5.0], AssembleOptions(704, 1280), [], None)
    assert "volume=" not in graph and "loudnorm" not in graph and "alimiter" not in graph
    assert "aresample=48000" in graph and "afade" in graph          # только формат и микрофейды на стыках


def test_quiet_shots_detection():
    from studio.assemble import quiet_shots
    assert quiet_shots({"001": -42.4, "002": -45.9, "003": -13.5, "004": -14.6, "005": -15.0}) == ["001", "002"]
    assert quiet_shots({"001": -20.0, "002": -22.0}) == []
    assert quiet_shots({"001": -20.0}) == []
