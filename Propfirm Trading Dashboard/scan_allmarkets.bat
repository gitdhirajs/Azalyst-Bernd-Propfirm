@echo off
:: ============================================================================
::  scan_allmarkets.bat  --  Broad "scan everything" evaluation run (LOCAL)
:: ============================================================================
::  Scans ~193 symbols (stocks + commodities + softs + ETFs + forex + metals +
::  energies + indices + crypto) with Bernd's method, paper-trades a SEPARATE
::  $5k / 1% account (no challenge gating -- takes every qualifying signal to
::  build a track record), and posts signals to your all-markets Discord channel.
::
::  State is isolated under *_allmarkets.json, so this NEVER touches the live
::  FundingPips $5k challenge account.
::
::  Usage:
::    Double-click            -> runs once, then PAUSES so you can read the details
::    scan_allmarkets.bat auto -> runs without pausing (for the daily scheduled task)
:: ============================================================================
cd /d "%~dp0"

:: Load the all-markets Discord webhook + user id (local, gitignored).
if exist ".secrets_allmarkets.bat" (
    call ".secrets_allmarkets.bat"
) else (
    echo [!] .secrets_allmarkets.bat not found -- signals will NOT post to Discord.
    echo     Create it with:  set DISCORD_WEBHOOK_URL=your_webhook
)

:: Clear stale bytecode so any code edits are picked up.
rd /s /q __pycache__ 2>nul

echo.
echo === Azalyst ALL-MARKETS scan (profile: allmarkets, $5k/1%%, take-all) ===
echo.

:: --profile allmarkets  -> BP_config_allmarkets.yaml + *_allmarkets state files
:: --no-open             -> headless (no dashboard browser/server)
:: run_scanner.py auto-posts to Discord using DISCORD_WEBHOOK_URL (set above)
:: with the correct _allmarkets state suffix.
python run_scanner.py --profile allmarkets --no-open

echo.
echo === Scan complete. Signals (if any) were posted to your Discord channel. ===
echo     Paper account + signals detail: scan_results_allmarkets_slim.json
echo.

:: Pause for a manual double-click run; skip the pause when launched as "auto".
if /I "%~1"=="auto" goto :eof
pause
