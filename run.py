import sys
import os
import logging

# Ensure the project root is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.gui import run_gui


def configure_runtime_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

if __name__ == "__main__":
    configure_runtime_logging()
    run_gui()
