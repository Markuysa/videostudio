#!/usr/bin/env python3
"""Совместимость со старой командой. Теперь всё делает studio.py:

    python studio.py render plans/storm.json     # == python make_film.py plans/storm.json
    python studio.py fetch storm                 # == python make_film.py --fetch storm
    python studio.py cleanup                     # == python make_film.py --cleanup
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from studio.cli import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
    elif args[0] == "--cleanup":
        main(["cleanup"])
    elif args[0] == "--fetch":
        main(["fetch", *args[1:2]])
    else:
        main(["render", args[0], *(["--keep-pod"] if "--keep-pod" in args else [])])
