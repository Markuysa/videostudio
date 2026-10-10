#!/usr/bin/env python3
"""AI-киностудия. Запуск: python studio.py --help"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from studio.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
