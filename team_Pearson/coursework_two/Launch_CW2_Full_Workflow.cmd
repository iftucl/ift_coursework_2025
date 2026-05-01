@echo off
setlocal

cd /d "%~dp0"

if exist "..\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=..\.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

echo Running CW2 one-command full workflow...
echo This checks quality gates, databases, the full strategy flow, robustness evidence, and the web API.
echo.

"%PYTHON_EXE%" scripts\full_workflow.py --start-services --serve

echo.
echo Full workflow command finished with exit code %ERRORLEVEL%.
pause
