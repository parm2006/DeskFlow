import sys
import os

# Ensure the project root is in the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.gui import run_gui

if __name__ == "__main__":
    run_gui()
