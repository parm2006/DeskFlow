@echo off
echo Setting up DeskFlow Environment...

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment and installing requirements...
call venv\Scripts\activate.bat
pip install -r requirements.txt

echo Starting DeskFlow...
python run.py
pause
