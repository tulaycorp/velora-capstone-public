@echo off
setlocal enabledelayedexpansion

set "ROOT_DIR=%~dp0"
set "BACKEND_DIR=%ROOT_DIR%backend"
set "BACKEND_PY=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "DRAMATIQ_BIN=%BACKEND_DIR%\.venv\Scripts\dramatiq.exe"
set "BACKEND_ENV_FILE=%BACKEND_DIR%\.env"
set "FRONTEND_ENV_FILE=%ROOT_DIR%.env.local"
set "REDIS_CONTAINER_NAME=velora-local-redis"
set "REDIS_CONTAINER_STARTED=0"

if not exist "%BACKEND_PY%" (
  echo Backend virtual environment not found at %BACKEND_PY%
  echo Create it first with: cd backend ^&^& python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
  exit /b 1
)

if not exist "%DRAMATIQ_BIN%" (
  echo Dramatiq executable not found at %DRAMATIQ_BIN%
  echo Install backend dependencies first with: cd backend ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
  exit /b 1
)

if not exist "%ROOT_DIR%node_modules" (
  echo Frontend dependencies are missing at %ROOT_DIR%node_modules
  echo Install them first with: npm install
  exit /b 1
)

if not exist "%BACKEND_ENV_FILE%" (
  echo Missing backend env file at %BACKEND_ENV_FILE%
  echo Create it from backend/.env.example and fill in the real Neon ^+ Clerk ^+ storage values first.
  exit /b 1
)

if not exist "%FRONTEND_ENV_FILE%" (
  echo Missing frontend env file at %FRONTEND_ENV_FILE%
  echo Create it from .env.local.example and fill in the real Clerk values first.
  exit /b 1
)

findstr /r /c:"replace-me" /c:"YOUR-PASSWORD" /c:"pk_test_replace_me" /c:"sk_test_replace_me" "%BACKEND_ENV_FILE%" "%FRONTEND_ENV_FILE%" >nul
if %errorlevel% equ 0 (
  echo Found placeholder values in env files.
  echo Replace the example Clerk/Neon/storage placeholders before starting the integrated stack.
  exit /b 1
)

if not defined REDIS_URL (
  for /f "tokens=1,* delims==" %%A in ('findstr /b "REDIS_URL=" "%BACKEND_ENV_FILE%"') do set "REDIS_URL=%%B"
)
if not defined REDIS_URL set "REDIS_URL=redis://127.0.0.1:6379/0"

call :check_redis
if %errorlevel% neq 0 (
  for /f "delims=" %%A in ('"%BACKEND_PY%" -c "import os; from urllib.parse import urlparse; print(urlparse(os.environ['REDIS_URL']).hostname or '127.0.0.1')"') do set "REDIS_HOST=%%A"
  for /f "delims=" %%A in ('"%BACKEND_PY%" -c "import os; from urllib.parse import urlparse; print(urlparse(os.environ['REDIS_URL']).port or 6379)"') do set "REDIS_PORT=%%A"

  if not "!REDIS_HOST!"=="127.0.0.1" if not "!REDIS_HOST!"=="localhost" (
    echo Redis is unreachable at !REDIS_URL!
    echo Start the configured Redis/Valkey service before running the Velora stack.
    exit /b 1
  )

  if exist "%ProgramFiles%\Redis\redis-server.exe" (
    echo Starting local Redis on !REDIS_HOST!:!REDIS_PORT!
    start "Velora Redis" /b "%ProgramFiles%\Redis\redis-server.exe" --bind !REDIS_HOST! --port !REDIS_PORT! --save "" --appendonly no
  ) else if exist "%ProgramFiles%\Valkey\valkey-server.exe" (
    echo Starting local Valkey on !REDIS_HOST!:!REDIS_PORT!
    start "Velora Redis" /b "%ProgramFiles%\Valkey\valkey-server.exe" --bind !REDIS_HOST! --port !REDIS_PORT! --save "" --appendonly no
  ) else if exist "%ProgramFiles(x86)%\Redis\redis-server.exe" (
    echo Starting local Redis on !REDIS_HOST!:!REDIS_PORT!
    start "Velora Redis" /b "%ProgramFiles(x86)%\Redis\redis-server.exe" --bind !REDIS_HOST! --port !REDIS_PORT! --save "" --appendonly no
  ) else if exist "%ProgramFiles(x86)%\Valkey\valkey-server.exe" (
    echo Starting local Valkey on !REDIS_HOST!:!REDIS_PORT!
    start "Velora Redis" /b "%ProgramFiles(x86)%\Valkey\valkey-server.exe" --bind !REDIS_HOST! --port !REDIS_PORT! --save "" --appendonly no
  ) else (
    where docker >nul 2>&1
    if !errorlevel! neq 0 (
      echo Redis is unreachable at !REDIS_URL!, and no local Redis, Valkey, or Docker runtime is available.
      echo Install Redis/Valkey or start the configured broker before running the Velora stack.
      exit /b 1
    )
    echo Starting local Redis container on !REDIS_HOST!:!REDIS_PORT!
    docker ps -a --format "{{.Names}}" | findstr /x /c:"%REDIS_CONTAINER_NAME%" >nul
    if !errorlevel! equ 0 (
      docker start "%REDIS_CONTAINER_NAME%" >nul
    ) else (
      docker run -d --rm --name "%REDIS_CONTAINER_NAME%" -p !REDIS_PORT!:6379 redis:7-alpine >nul
    )
    set "REDIS_CONTAINER_STARTED=1"
  )

  set "REDIS_READY=0"
  for /L %%I in (1,1,30) do (
    if "!REDIS_READY!"=="0" (
      call :check_redis
      if !errorlevel! equ 0 set "REDIS_READY=1"
      if "!REDIS_READY!"=="0" timeout /t 1 /nobreak >nul
    )
  )
  if "!REDIS_READY!"=="0" (
    echo Redis did not become ready at !REDIS_URL!
    call :cleanup
    exit /b 1
  )
)

echo Starting backend on http://127.0.0.1:8000
echo Backend env: %BACKEND_ENV_FILE%
start "Velora Backend" /b cmd /c "cd /d ""%BACKEND_DIR%"" && ""%BACKEND_PY%"" -m uvicorn app.main:app --reload"

echo Starting Dramatiq workers
start "Velora Workers" /b cmd /c "cd /d ""%BACKEND_DIR%"" && ""%DRAMATIQ_BIN%"" --processes 1 --threads 4 app.jobs.broker:broker app.jobs.orders app.jobs.publishing app.jobs.analytics app.jobs.etsy_sales"

taskkill /FI "WINDOWTITLE eq Velora Scheduler" /T /F >nul 2>&1
echo Starting scheduler
start "Velora Scheduler" /b cmd /c "cd /d ""%BACKEND_DIR%"" && ""%BACKEND_PY%"" -m app.scheduler"

echo Starting frontend on http://127.0.0.1:3000
echo Frontend env: %FRONTEND_ENV_FILE%
cd /d "%ROOT_DIR%"
call npm run dev

call :cleanup
endlocal
exit /b 0

:check_redis
"%BACKEND_PY%" -c "import os, redis; redis.Redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=1, socket_timeout=1).ping()" >nul 2>&1
exit /b %errorlevel%

:cleanup
for %%T in ("Velora Backend" "Velora Workers" "Velora Scheduler" "Velora Redis") do taskkill /FI "WINDOWTITLE eq %%~T" /T /F >nul 2>&1
if "%REDIS_CONTAINER_STARTED%"=="1" docker stop "%REDIS_CONTAINER_NAME%" >nul 2>&1
exit /b 0
