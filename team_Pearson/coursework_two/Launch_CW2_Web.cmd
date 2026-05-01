@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "HOST=127.0.0.1"
set "PORT=8011"
set "URL=http://%HOST%:%PORT%/"
set "DB_PORT=5439"
set "DB_CONTAINER=postgres_db_cw"
set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"
set "LOG_DIR=%SCRIPT_DIR%outputs\web_state\launcher_logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
set "SERVER_LOG=%LOG_DIR%\uvicorn_8011.out.log"
set "SERVER_ERR_LOG=%LOG_DIR%\uvicorn_8011.err.log"

cd /d "%SCRIPT_DIR%"

call :resolve_python
if errorlevel 1 (
  echo [CW2 Web] Python was not found. Please install Python or fix PATH.
  pause
  exit /b 1
)

call :ensure_postgres
if errorlevel 1 (
  echo [CW2 Web] PostgreSQL on port %DB_PORT% did not become ready.
  pause
  exit /b 1
)

call :server_ready
if "%SERVER_READY%"=="1" (
  echo [CW2 Web] Existing server detected on %URL%. Restarting it to load the latest code...
  call :stop_server
)

echo [CW2 Web] Starting local web server on %URL%
if exist "%SERVER_LOG%" del /f /q "%SERVER_LOG%" >nul 2>nul
if exist "%SERVER_ERR_LOG%" del /f /q "%SERVER_ERR_LOG%" >nul 2>nul
start "CW2 Web Server" /min cmd /c ""%PYTHON_EXE%" -m uvicorn api.main:app --host %HOST% --port %PORT% 1>>"%SERVER_LOG%" 2>>"%SERVER_ERR_LOG%""

set "ATTEMPTS=0"
:wait_loop
set /a ATTEMPTS+=1
ping -n 2 127.0.0.1 >nul
call :server_ready
if "%SERVER_READY%"=="1" goto open_browser
if %ATTEMPTS% GEQ 20 goto startup_failed
goto wait_loop

:open_browser
echo [CW2 Web] Opening browser...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%URL%'" >nul 2>nul
exit /b 0

:startup_failed
echo [CW2 Web] The server did not become ready in time.
if exist "%SERVER_LOG%" (
  echo [CW2 Web] Last stdout log:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%SERVER_LOG%' -Tail 20"
)
if exist "%SERVER_ERR_LOG%" (
  echo [CW2 Web] Last stderr log:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%SERVER_ERR_LOG%' -Tail 20"
)
echo [CW2 Web] You can retry by double-clicking this launcher again.
pause
exit /b 1

:stop_server
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$conn = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue }"
ping -n 2 127.0.0.1 >nul
exit /b 0

:ensure_postgres
call :postgres_ready
if "%POSTGRES_READY%"=="1" exit /b 0

call :ensure_docker
if errorlevel 1 exit /b 1

echo [CW2 Web] PostgreSQL is not listening on %DB_PORT%. Attempting docker start %DB_CONTAINER%...
powershell -NoProfile -ExecutionPolicy Bypass -Command "docker start %DB_CONTAINER% *> $null" >nul 2>nul

set "PG_ATTEMPTS=0"
:wait_pg
set /a PG_ATTEMPTS+=1
ping -n 2 127.0.0.1 >nul
call :postgres_ready
if "%POSTGRES_READY%"=="1" exit /b 0
if %PG_ATTEMPTS% GEQ 25 exit /b 1
goto wait_pg

:ensure_docker
call :docker_ready
if "%DOCKER_READY%"=="1" exit /b 0

echo [CW2 Web] Docker engine not ready. Attempting to start Docker services...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Service -Name 'com.docker.service' -ErrorAction SilentlyContinue" >nul 2>nul

if exist "%DOCKER_DESKTOP%" (
  echo [CW2 Web] Launching Docker Desktop...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%DOCKER_DESKTOP%'" >nul 2>nul
)

set "DOCKER_ATTEMPTS=0"
:wait_docker
set /a DOCKER_ATTEMPTS+=1
ping -n 3 127.0.0.1 >nul
call :docker_ready
if "%DOCKER_READY%"=="1" exit /b 0
if %DOCKER_ATTEMPTS% GEQ 45 exit /b 1
goto wait_docker

:docker_ready
set "DOCKER_READY=0"
docker version >nul 2>nul
if not errorlevel 1 set "DOCKER_READY=1"
exit /b 0

:postgres_ready
set "POSTGRES_READY=0"
"%PYTHON_EXE%" -c "import socket,sys; s=socket.create_connection(('127.0.0.1', int(sys.argv[1])), 2); s.close()" %DB_PORT% >nul 2>nul
if not errorlevel 1 set "POSTGRES_READY=1"
exit /b 0

:resolve_python
set "PYTHON_EXE="
if exist "C:\Users\grace\miniconda3\python.exe" (
  set "PYTHON_EXE=C:\Users\grace\miniconda3\python.exe"
  exit /b 0
)
if exist "%SCRIPT_DIR%..\coursework_one\.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%SCRIPT_DIR%..\coursework_one\.venv\Scripts\python.exe"
  exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%I in ('where python') do (
    set "PYTHON_EXE=%%I"
    exit /b 0
  )
)

where py >nul 2>nul
if not errorlevel 1 (
  for /f "delims=" %%I in ('where py') do (
    set "PYTHON_EXE=%%I"
    exit /b 0
  )
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  exit /b 0
)

exit /b 1

:server_ready
set "SERVER_READY=0"
"%PYTHON_EXE%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%PORT%/health', timeout=2).read()" >nul 2>nul
if not errorlevel 1 set "SERVER_READY=1"
exit /b 0
