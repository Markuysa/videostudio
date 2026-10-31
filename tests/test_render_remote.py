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


def test_pod_counts_as_gone_only_on_404(monkeypatch):
    from studio.render_remote import RunPod
    rp = RunPod("key")
    for code, gone in ((404, True), (200, False), (500, False), (599, False)):
        monkeypatch.setattr(rp, "call", lambda *a, c=code: (c, None))
        assert rp.gone("pod") is gone


def test_low_balance_fails_fast_instead_of_waiting_for_gpus(monkeypatch):
    import pytest
    from studio import render_remote as rr
    monkeypatch.setattr(rr, "ensure_key", lambda: "ssh-ed25519 AAAA")
    rp = rr.RunPod("key")
    calls = []
    monkeypatch.setattr(rp, "try_create", lambda body: calls.append(body) or (500, '{"error":"create pod: Your account '
                        'balance is too low to rent a pod. Please add funds to your account.","status":500}'))
    with pytest.raises(rr.RenderError, match="баланс"):
        rr.start_pod(rp, {"network_volume_id": "v", "quality": "high"}, "x")
    assert len(calls) == 1
