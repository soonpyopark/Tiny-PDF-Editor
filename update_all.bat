@echo off
chcp 949 >nul 2>&1

REM ============================================================================
REM  Tiny PDF Editor - Update all components to latest
REM  git pull + npm + Python pip + optional MSI build
REM ============================================================================

if /I not "%~1"=="_inner" if /I not "%~1"=="_quiet" (
    call "%~f0" _inner %*
    set "EXIT_CODE=%ERRORLEVEL%"
    echo.
    pause
    exit /b %EXIT_CODE%
)
if /I "%~1"=="_inner" shift
if /I "%~1"=="_quiet" shift

setlocal EnableExtensions

set "PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%PS%" (
    echo [ERROR] PowerShell not found
    exit /b 1
)

set "APP_ROOT=%~dp0"
if "%APP_ROOT:~-1%"=="\" set "APP_ROOT=%APP_ROOT:~0,-1%"

set "EXTRA_ARGS="

:parse_args
if "%~1"=="" goto run
if /I "%~1"=="build" (
    set "EXTRA_ARGS=%EXTRA_ARGS% -BuildDist"
    shift
    goto parse_args
)
if /I "%~1"=="force" (
    set "EXTRA_ARGS=%EXTRA_ARGS% -Force"
    shift
    goto parse_args
)
if /I "%~1"=="skip-git" (
    set "EXTRA_ARGS=%EXTRA_ARGS% -SkipGit"
    shift
    goto parse_args
)
if /I "%~1"=="skip-npm" (
    set "EXTRA_ARGS=%EXTRA_ARGS% -SkipNpm"
    shift
    goto parse_args
)
if /I "%~1"=="skip-python" (
    set "EXTRA_ARGS=%EXTRA_ARGS% -SkipPython"
    shift
    goto parse_args
)
if /I "%~1"=="skip-cores" (
    set "EXTRA_ARGS=%EXTRA_ARGS% -SkipCores"
    shift
    goto parse_args
)
set "EXTRA_ARGS=%EXTRA_ARGS% %~1"
shift
goto parse_args

:run
echo.
echo ============================================================
echo  Tiny PDF Editor - update_all
echo ============================================================
echo  Root : %APP_ROOT%
echo  Log  : .cache\logs\update-all.log
echo.
echo  Options: build force skip-git skip-npm skip-python skip-cores
echo ============================================================
echo.

"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%APP_ROOT%\scripts\update-all.ps1" %EXTRA_ARGS%
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
