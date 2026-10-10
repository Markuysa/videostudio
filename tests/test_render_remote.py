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


def test_reference_images_are_packaged_without_changing_local_plan(tmp_path):
    from studio.render_remote import reference_asset, upload_studio
    from types import SimpleNamespace
    (tmp_path / 'plans').mkdir()
    source = tmp_path / 'frame.png'
    source.write_bytes(b'first image')
    plan_path = tmp_path / 'plans' / 'ref.json'
    plan = Plan.from_dict({'title': 'ref', 'shots': [{'prompt': 'p' * 40, 'image': '../frame.png'}]})
    plan.save(plan_path)
    original = plan_path.read_bytes()
    collect_plan_assets(plan, plan_path, tmp_path)
    _, relative = reference_asset('../frame.png', plan_path)
    assert (plan_path.parent / relative).read_bytes() == b'first image'
    source.write_bytes(b'updated image')
    collect_plan_assets(plan, plan_path, tmp_path)
    assert (plan_path.parent / relative).read_bytes() == b'updated image'

    class Remote:
        def run(self, *args, **kwargs):
            return SimpleNamespace(returncode=0)

        def put(self, src, dst):
            if dst.endswith('/ref.json'):
                self.uploaded = Plan.from_dict(__import__('json').loads(src.read_text()))

    remote = Remote()
    upload_studio(remote, plan_path)
    assert remote.uploaded.shots[0].image == str(relative)
    assert plan_path.read_bytes() == original


def test_missing_reference_fails_before_gpu_allocation(tmp_path):
    import pytest
    from studio.render_remote import RenderError
    plan = Plan.from_dict({'title': 'x', 'shots': [{'prompt': 'p' * 40, 'image': 'missing.png'}]})
    with pytest.raises(RenderError, match='опорный кадр'):
        collect_plan_assets(plan, tmp_path / 'x.json', tmp_path)
