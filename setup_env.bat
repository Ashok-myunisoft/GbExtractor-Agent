@echo off
echo Setting up virtual environment...

rem Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed or not in PATH.
    pause
    exit /b 1
)

rem Create .venv if it doesn't exist
if not exist ".venv" (
    echo Creating .venv...
    python -m venv .venv
)

rem Activate .venv
call .venv\Scripts\activate

rem Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

rem Install dependencies
echo Installing dependencies from requirements.txt...
pip install -r requirements.txt

echo Setup complete.
pause
