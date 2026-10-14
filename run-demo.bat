@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Run from CMD. This demo uses synthetic data and does not connect to Jira.
rem A first-time setup needs internet access to download Python packages.

pushd "%~dp0"
if errorlevel 1 exit /b 1

if not exist "pyproject.toml" (
    echo ERROR: Run this file from a complete repository checkout.
    popd
    exit /b 1
)

echo [1/7] Checking Python 3.11 or newer...
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 goto try_launcher
set "JIRA_DEMO_BOOTSTRAP=python"
goto prepare_venv

:try_launcher
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Install Python 3.11 or newer, then open a new CMD window.
    popd
    exit /b 1
)
set "JIRA_DEMO_BOOTSTRAP=py -3"

:prepare_venv
echo [2/7] Preparing the dedicated .venv-demo environment...
set "JIRA_DEMO_STEP=virtual environment setup"
if exist ".venv-demo\Scripts\python.exe" goto check_venv
if exist ".venv-demo" (
    echo ERROR: .venv-demo exists but has no Windows Python executable.
    echo Rename that directory and rerun this demo. No files were removed.
    popd
    exit /b 1
)
%JIRA_DEMO_BOOTSTRAP% -m venv ".venv-demo"
if errorlevel 1 goto failed

:check_venv
set "JIRA_DEMO_PYTHON=%CD%\.venv-demo\Scripts\python.exe"
"%JIRA_DEMO_PYTHON%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 goto failed

echo [3/7] Installing project dependencies...
set "JIRA_DEMO_STEP=dependency installation"
"%JIRA_DEMO_PYTHON%" -m pip install -e "."
if errorlevel 1 goto failed

rem Give every run a separate report directory; keep earlier results intact.
:choose_output
set "JIRA_DEMO_OUTPUT=%CD%\artifacts\windows-demo-%RANDOM%-%RANDOM%"
if exist "%JIRA_DEMO_OUTPUT%" goto choose_output
set "JIRA_DEMO_STEP=report directory creation"
mkdir "%JIRA_DEMO_OUTPUT%"
if errorlevel 1 goto failed

echo [4/7] Running local tests...
set "JIRA_DEMO_STEP=local tests"
"%JIRA_DEMO_PYTHON%" -m pytest tests -q --junitxml "%JIRA_DEMO_OUTPUT%\unit-tests.xml"
if errorlevel 1 goto failed

echo [5/7] Validating all sample YAML scenarios...
set "JIRA_DEMO_STEP=YAML validation"
"%JIRA_DEMO_PYTHON%" -m jira_test validate --suite "examples\yaml"
if errorlevel 1 goto failed

echo [6/7] Querying the synthetic demo catalog...
set "JIRA_DEMO_STEP=catalog query"
"%JIRA_DEMO_PYTHON%" -m jira_test query --catalog "examples\demo-catalog.json" --field summary --source api > "%JIRA_DEMO_OUTPUT%\catalog-query.json"
if errorlevel 1 goto failed

echo [7/7] Running the sample catalog test...
set "JIRA_DEMO_SUITE=%CD%\examples\yaml\05_required_metadata.yaml"
set "JIRA_DEMO_CATALOG=%CD%\examples\demo-catalog.json"
set "JIRA_DEMO_STEP=demo working directory"
pushd "%JIRA_DEMO_OUTPUT%"
if errorlevel 1 goto failed
set "JIRA_DEMO_NESTED=1"
set "JIRA_DEMO_STEP=sample catalog test"
"%JIRA_DEMO_PYTHON%" -m jira_test run --suite "%JIRA_DEMO_SUITE%" --catalog "%JIRA_DEMO_CATALOG%" --junit "%JIRA_DEMO_OUTPUT%\demo-junit.xml"
if errorlevel 1 goto failed
popd
set "JIRA_DEMO_NESTED="

echo.
echo SUCCESS: Local tests, YAML validation and the demo test passed.
echo Reports: "%JIRA_DEMO_OUTPUT%"
echo This result does not verify a live Jira connection or Edge browser.
popd
exit /b 0

:failed
set "JIRA_DEMO_EXIT=%ERRORLEVEL%"
if "%JIRA_DEMO_EXIT%"=="0" set "JIRA_DEMO_EXIT=1"
echo.
echo ERROR: Failed during %JIRA_DEMO_STEP%.
echo Exit code: %JIRA_DEMO_EXIT%
if defined JIRA_DEMO_OUTPUT echo Reports: "%JIRA_DEMO_OUTPUT%"
if defined JIRA_DEMO_NESTED popd
popd
exit /b %JIRA_DEMO_EXIT%
