@echo off
setlocal

cd /d "%~dp0"

set FICFRAME_HOST=127.0.0.1
set FICFRAME_PORT=8787
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo [FicFrame] Created .env from .env.example.
  )
)

call :find_uv
if not "%UV_EXE%"=="" (
  echo [FicFrame] uv found. Using uv environment.
  set UV_CACHE_DIR=.uv-cache
  "%UV_EXE%" sync
  if errorlevel 1 goto dependency_failed
  echo [FicFrame] Opening http://%FICFRAME_HOST%:%FICFRAME_PORT%
  start "" "http://%FICFRAME_HOST%:%FICFRAME_PORT%"
  echo [FicFrame] Starting server with uv. Close this window or press Ctrl+C to stop.
  "%UV_EXE%" run ficframe serve --host %FICFRAME_HOST% --port %FICFRAME_PORT%
  pause
  exit /b 0
)

echo [FicFrame] uv was not found. Falling back to Python venv + pip.
call :find_python
if "%PY_EXE%"=="" (
  echo [FicFrame] Python 3.10+ was not found.
  echo Please install Python from https://www.python.org/downloads/
  echo During installation, enable "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [FicFrame] Creating virtual environment...
  %PY_EXE% -m venv .venv
  if errorlevel 1 (
    echo [FicFrame] Failed to create .venv.
    pause
    exit /b 1
  )
)

echo [FicFrame] Installing or checking dependencies with pip...
".venv\Scripts\python.exe" -m pip install -U pip -i %PIP_INDEX_URL%
if errorlevel 1 goto dependency_failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt -i %PIP_INDEX_URL%
if errorlevel 1 goto dependency_failed

echo [FicFrame] Opening http://%FICFRAME_HOST%:%FICFRAME_PORT%
start "" "http://%FICFRAME_HOST%:%FICFRAME_PORT%"

echo [FicFrame] Starting server with Python venv. Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" -m ficframe.cli serve --host %FICFRAME_HOST% --port %FICFRAME_PORT%

pause
exit /b 0

:find_uv
set UV_EXE=uv
where uv >nul 2>nul
if errorlevel 1 set UV_EXE=
if "%UV_EXE%"=="" if exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe" set UV_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe
if "%UV_EXE%"=="" if exist "%USERPROFILE%\.cargo\bin\uv.exe" set UV_EXE=%USERPROFILE%\.cargo\bin\uv.exe
if "%UV_EXE%"=="" if exist "%USERPROFILE%\.local\bin\uv.exe" set UV_EXE=%USERPROFILE%\.local\bin\uv.exe
exit /b 0

:find_python
set PY_EXE=
where py >nul 2>nul
if not errorlevel 1 set PY_EXE=py -3
if "%PY_EXE%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 set PY_EXE=python
)
exit /b 0

:dependency_failed
echo [FicFrame] Dependency installation failed.
pause
exit /b 1
