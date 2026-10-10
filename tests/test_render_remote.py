import pathlib

from studio.render_remote import HIGH_GPUS, collect_plan_assets, gpu_lists
from studio.schema import Plan


def test_gpu_lists_by_quality():
    mine, extra = gpu_lists({"quality": "fast", "gpu_types": ["NVIDIA L40S"]})
    assert mine == ["NVIDIA L40S"] and "NVIDIA L40S" not in extra and "NVIDIA GeForce RTX 5090" in extra
    mine_h, extra_h = gpu_lists({"quality": "high"})
    assert mine_h == HIGH_GPUS and extra_h == []


def test_collect_plan_assets(tmp_path):
    root = tmp_path
    (root / "assets" / "music").mkdir(parents=True)
    (root / "assets" / "music" / "a.mp3").write_bytes(b"x")
    plan = Plan.from_dict({"title": "t", "music": {"file": "assets/music/a.mp3"},
                           "shots": [{"prompt": "p" * 30, "sfx": [{"file": "assets/sfx/missing.wav"}]}]})
    plan_path = root / "plans" / "t.json"
    plan_path.parent.mkdir()
    msgs = []
    collect_plan_assets(plan, plan_path, root, log_fn=msgs.append)
    assert (root / "plans" / "t_assets" / "assets" / "music" / "a.mp3").exists()
    assert any("missing.wav" in m for m in msgs)
