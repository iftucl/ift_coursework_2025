@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "TEAM_DIR=%SCRIPT_DIR%.."
set "VENV_DIR=%TEAM_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "DEV_REQ=%SCRIPT_DIR%requirements-dev.txt"

cd /d "%SCRIPT_DIR%"

call :resolve_python
if errorlevel 1 (
  echo [CW2 Full Workflow] Python was not found. Please install Python or fix PATH.
  pause
  exit /b 1
)

call :ensure_dev_deps
if errorlevel 1 (
  echo [CW2 Full Workflow] Dependencies could not be installed. See the pip output above.
  pause
  exit /b 1
)

echo Running CW2 one-command full workflow...
echo This checks quality gates, databases, the full strategy flow, robustness evidence, and the web API.
echo.

"%PYTHON_EXE%" scripts\full_workflow.py --start-services --serve
set "WF_EXIT=%ERRORLEVEL%"

echo.
echo Full workflow command finished with exit code %WF_EXIT%.
pause

exit /b %WF_EXIT%

:resolve_python
set "PYTHON_EXE="
if exist "%VENV_PYTHON%" (
  set "PYTHON_EXE=%VENV_PYTHON%"
  exit /b 0
)

call :resolve_bootstrap_python
if errorlevel 1 exit /b 1

echo [CW2 Full Workflow] Creating local virtual environment at %VENV_DIR% ...
"%BOOTSTRAP_PYTHON%" -m venv "%VENV_DIR%"
if errorlevel 1 exit /b 1
if not exist "%VENV_PYTHON%" exit /b 1
set "PYTHON_EXE=%VENV_PYTHON%"
exit /b 0

:resolve_bootstrap_python
set "BOOTSTRAP_PYTHON="
where python >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%I in ('where python') do (
    set "BOOTSTRAP_PYTHON=%%I"
    exit /b 0
  )
)

where py >nul 2>nul
if not errorlevel 1 (
  set "BOOTSTRAP_PYTHON=py"
  exit /b 0
)

if exist "C:\Users\grace\miniconda3\python.exe" (
  set "BOOTSTRAP_PYTHON=C:\Users\grace\miniconda3\python.exe"
  exit /b 0
)

exit /b 1

:ensure_dev_deps
if not exist "%DEV_REQ%" exit /b 1
"%PYTHON_EXE%" -c "import black, isort, flake8, bandit, sphinx, fastapi, uvicorn, sqlalchemy, psycopg2, pandas, numpy, yaml" >nul 2>nul
if not errorlevel 1 (
  exit /b 0
)

echo [CW2 Full Workflow] Installing runtime and quality dependencies into %VENV_DIR% ...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%PYTHON_EXE%" -m pip install -r "%DEV_REQ%"
exit /b %ERRORLEVEL%
