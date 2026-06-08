#!/usr/bin/env python3
"""Convenience entry point.

  python run.py             → CLI (same as axedup --help)
  python run.py ui          → desktop UI
  python run.py <command>   → any axedup CLI command
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ui":
        sys.argv.pop(1)
        from axedup.ui.app import start
        start()
    else:
        from axedup.cli import app
        app()
