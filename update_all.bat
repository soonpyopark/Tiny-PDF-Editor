@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo Tiny PDF Editor - update all libraries
echo.

where npm >nul 2>&1
if errorlevel 1 (
  echo [error] npm was not found. Install Node.js and try again.
  pause
  exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
  echo [error] python was not found. Install Python and try again.
  pause
  exit /b 1
)

call npm run build:update_all
if errorlevel 1 (
  echo.
  echo [error] Library update failed.
  pause
  exit /b 1
)

echo.
echo [ok] All libraries updated.
pause
