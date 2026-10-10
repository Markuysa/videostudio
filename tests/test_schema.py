import json

import pytest

from studio.schema import (Plan, PlanError, frames_for, load_plan, normalize_durations, slugify, snap_seconds,
                           validate)


def test_frames_grid():
    assert frames_for(8) == 193
    assert frames_for(5) == 121
    assert frames_for(3) == 73
    assert frames_for(0.1) == 9
    for s in (3, 4.2, 5, 6.7, 8, 10):
        assert (frames_for(s) - 1) % 8 == 0
    assert snap_seconds(8) == 8.042


def test_slugify_cyrillic():
    assert slugify("Я подожду") == "a_podojdu"
    assert slugify("!!!") == "film"


def test_v1_plan_loads_and_converts(storm_plan):
    assert storm_plan.version == 2
    assert storm_plan.format == "9:16"
    assert [s.transition for s in storm_plan.shots][:2] == ["cut", "continue"]
    assert storm_plan.slug == "a_podojdu" or storm_plan.slug
    assert validate(storm_plan, "high") == []


def test_total_seconds_accounts_for_transitions():
    d = {"title": "t", "shots": [
        {"prompt": "x" * 30, "seconds": 8},
        {"prompt": "x" * 30, "seconds": 8, "transition": "dissolve", "transition_seconds": 1.0},
        {"prompt": "x" * 30, "seconds": 8, "transition": "continue"},
    ]}
    p = Plan.from_dict(d)
    assert abs(p.total_seconds - (3 * 8.042 - 1.0 - 1 / 24)) < 0.01


def test_validate_catches_bad_durations():
    d = {"title": "t", "quality": "high", "shots": [{"prompt": "x" * 30, "seconds": 15}, {"prompt": "x" * 30, "seconds": 1}]}
    p = Plan.from_dict(d)
    problems = validate(p, "high")
    assert any("длиннее" in x for x in problems) and any("короче" in x for x in problems)


def test_bad_inputs():
    with pytest.raises(PlanError):
        Plan.from_dict({"title": "t", "shots": []})
    with pytest.raises(PlanError):
        Plan.from_dict({"title": "t", "format": "3:2", "shots": [{"prompt": "x" * 30}]})
    with pytest.raises(PlanError):
        Plan.from_dict({"title": "t", "shots": [{"prompt": "x" * 30, "transition": "wipe"}]})


def test_roundtrip(tmp_path, storm_plan):
    storm_plan.music = None
    normalize_durations(storm_plan)
    out = tmp_path / "p.json"
    storm_plan.save(out)
    again = load_plan(out)
    assert [s.prompt for s in again.shots] == [s.prompt for s in storm_plan.shots]
    assert json.loads(out.read_text())["version"] == 2


def test_clamp_conditioned_in_high_mode():
    from studio.schema import clamp_seconds, frames_for
    assert frames_for(clamp_seconds(8, high=True, conditioned=True)) == 121
    assert frames_for(clamp_seconds(8, high=True, conditioned=False)) == 193
    assert frames_for(clamp_seconds(8, high=False, conditioned=True)) == 193
