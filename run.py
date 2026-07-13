import sys
import os
import argparse

# Ensure the project root is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.gui import run_gui


def main():
    parser = argparse.ArgumentParser(description="DeskFlow")
    parser.add_argument("--daemon", action="store_true", help="run without a GUI window")
    args, remaining = parser.parse_known_args()
    if args.daemon:
        from app.daemon import run_daemon
        return run_daemon(remaining)
    run_gui()

if __name__ == "__main__":
    main()
