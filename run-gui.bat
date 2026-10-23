@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "STUDIO_PYTHON=.venv\Scripts\python.exe"
) else (
    set "STUDIO_PYTHON=python"
)
"%STUDIO_PYTHON%" -c "import sys; assert sys.version_info >= (3, 11); import tkinter, jira_test" >nul 2>&1
if errorlevel 1 (
    echo Python 3.11+, Tcl/Tk and the project package are required.
    echo Enable "Tcl/Tk and IDLE" in Python Setup, then run:
    echo   python -m venv .venv
    echo   .venv\Scripts\python -m pip install -e .
    echo   .venv\Scripts\python -m tkinter
    pause
    exit /b 2
)
"%STUDIO_PYTHON%" -m jira_test gui --workspace "%CD%"
if errorlevel 1 pause
