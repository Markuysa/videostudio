import subprocess
import sys

from tests.conftest import ROOT


def test_cli_estimate_and_review():
    r = subprocess.run([sys.executable, str(ROOT / "studio.py"), "estimate", str(ROOT / "plans" / "storm.json")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "Сцен: 6" in r.stdout
    r = subprocess.run([sys.executable, str(ROOT / "studio.py"), "review", str(ROOT / "plans" / "storm.json")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "сцена 003" in r.stdout


def test_make_film_compat_help():
    r = subprocess.run([sys.executable, str(ROOT / "make_film.py")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "studio.py render" in r.stdout
