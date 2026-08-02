@echo off
setlocal

cd /d "%~dp0"

set UV_EXE=uv
where uv >nul 2>nul
if errorlevel 1 set UV_EXE=

if "%UV_EXE%"=="" if exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe" set UV_EXE=%LOCALAPPDATA%\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe
if "%UV_EXE%"=="" if exist "%USERPROFILE%\.cargo\bin\uv.exe" set UV_EXE=%USERPROFILE%\.cargo\bin\uv.exe
if "%UV_EXE%"=="" if exist "%USERPROFILE%\.local\bin\uv.exe" set UV_EXE=%USERPROFILE%\.local\bin\uv.exe

if "%UV_EXE%"=="" (
  echo [FicFrame] uv was not found.
  echo Please install uv first: https://docs.astral.sh/uv/
  pause
  exit /b 1
)

set UV_CACHE_DIR=.uv-cache
set FICFRAME_HOST=127.0.0.1
set FICFRAME_PORT=8787

if not exist ".env" (
  if exist ".env.example" (
    copy ".env.example" ".env" >nul
    echo [FicFrame] Created .env from .env.example.
  )
)

echo [FicFrame] Installing or checking dependencies...
"%UV_EXE%" sync
if errorlevel 1 (
  echo [FicFrame] Dependency installation failed.
  pause
  exit /b 1
)

echo [FicFrame] Opening http://%FICFRAME_HOST%:%FICFRAME_PORT%
start "" "http://%FICFRAME_HOST%:%FICFRAME_PORT%"

echo [FicFrame] Starting server. Close this window or press Ctrl+C to stop.
"%UV_EXE%" run ficframe serve --host %FICFRAME_HOST% --port %FICFRAME_PORT%

pause
