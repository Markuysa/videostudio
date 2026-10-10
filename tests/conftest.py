import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="нужен ffmpeg")


@pytest.fixture
def storm_plan():
    from studio.schema import load_plan
    return load_plan(ROOT / "plans" / "storm.json")
