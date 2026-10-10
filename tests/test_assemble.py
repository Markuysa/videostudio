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
    opts = AssembleOptions(704, 1280, music_path="m.mp3", captions=True)
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
