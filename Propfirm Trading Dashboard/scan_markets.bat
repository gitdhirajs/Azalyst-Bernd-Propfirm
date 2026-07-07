@echo off
REM ============================================================
REM   Azalyst Propfirm - Local Scanner (multi-strategy)
REM ============================================================
REM Usage:
REM   scan_markets.bat               -> default strategy (daily)
REM   scan_markets.bat weekly        -> HTF=1wk, LTF=1d   -> scanner_weekly.log
REM   scan_markets.bat monthly       -> HTF=1mo, LTF=1wk  -> scanner_monthly.log
REM   scan_markets.bat daily         -> HTF=1d,  LTF=60m  -> scanner_daily.log
REM   scan_markets.bat intraday      -> HTF=60m, LTF=15m  -> scanner_intraday.log
REM ============================================================

setlocal

set STRATEGY=%~1
if "%STRATEGY%"=="" set STRATEGY=daily

if /I not "%STRATEGY%"=="weekly" if /I not "%STRATEGY%"=="monthly" if /I not "%STRATEGY%"=="daily" if /I not "%STRATEGY%"=="intraday" (
    echo ERROR: Unknown strategy "%STRATEGY%". Use: weekly ^| monthly ^| daily ^| intraday
    pause
    exit /b 2
)

title Azalyst Propfirm Scanner [%STRATEGY%]

echo ============================================
echo   Azalyst Propfirm - Local Scanner
echo   Strategy: %STRATEGY%
echo   $5,000 account / $150 daily / $300 total (FundingPips 1-Step)
echo ============================================
echo.
echo Starting scan at %date% %time%
echo.

cd /d "%~dp0"

REM Check Python and Virtual Environment
set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" (
    set PYTHON_EXE="%~dp0.venv\Scripts\python.exe"
    echo Using virtual environment...
)

%PYTHON_EXE% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.8+ from python.org or ensure .venv is correct.
    pause
    exit /b 1
)

REM Install dependencies on first run
if not exist ".deps_installed" (
    if not exist ".venv" (
        echo Installing dependencies to global Python...
        %PYTHON_EXE% -m pip install yfinance pandas numpy pyyaml requests psutil --quiet
    ) else (
        echo Dependencies should already be in .venv.
    )

    echo. > .deps_installed
    echo Dependencies initialized.
    echo.
)

REM ============================================================
REM Discord webhook for trade signal notifications.
REM   - DISCORD_WEBHOOK_URL is the channel webhook target.
REM   - DISCORD_USER_ID is your Discord snowflake; you get @-pinged only
REM     when there are NEW signals (per send_discord.py policy).
REM Comment these out or leave blank to disable Discord notifications.
REM SECURITY: anyone with disk access to this file can post to your
REM channel. Treat this file like a secret.
REM ============================================================
REM Load the webhook URL + user ID from a local, gitignored file so the
REM secrets never enter the repo. Copy .secrets.example.bat -> .secrets.bat
REM and fill in your own values. If .secrets.bat is missing, Discord posting
REM is silently skipped (which is the correct behaviour for fresh clones).
if exist ".secrets.bat" call ".secrets.bat"

REM ------------------------------------------------------------
REM Pre-clear any compiled bytecode so freshly edited .py files
REM are guaranteed to be picked up. (Python normally re-compiles
REM on mtime change, but this removes any doubt.)
REM ------------------------------------------------------------
if exist "__pycache__" rd /s /q "__pycache__"

REM ------------------------------------------------------------
REM Run the scanner. Python manages its own per-strategy log file
REM (scanner_<strategy>.log, written fresh each run) so we no longer
REM redirect stdout here -- you see live progress in this window.
REM The shared rolling log is always scanner.log.
REM ------------------------------------------------------------
set PER_STRAT_LOG=scanner_%STRATEGY%.log
echo Per-strategy log: %PER_STRAT_LOG% (written by Python)
echo.

%PYTHON_EXE% run_scanner.py --strategy %STRATEGY%
set SCAN_EXIT=%ERRORLEVEL%

REM Show the tail of the per-strategy log so the user can see a summary
echo.
echo --- Last 60 progress lines of %PER_STRAT_LOG% ---
powershell -NoProfile -Command "Get-Content '%PER_STRAT_LOG%' | Select-String '\[\d+/\d+\]|SIGNAL|ERROR|Scan complete|signals_found|SCAN COMPLETE' | Select-Object -Last 60"
echo.
echo ============================================
echo   Scan complete (%STRATEGY%). Dashboard at http://127.0.0.1:8765
echo   Full log: %PER_STRAT_LOG%
echo   Close this window to stop the local server.
echo ============================================
pause
exit /b %SCAN_EXIT%

