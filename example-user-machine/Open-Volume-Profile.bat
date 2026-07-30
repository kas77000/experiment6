@echo off
rem ===========================================================================
rem  Volume Profile - double-click this
rem ===========================================================================
rem  Reads the CSV named below, loads it into the viewer, and opens it in the
rem  browser. The CSV can be replaced on the share whenever you like; this
rem  reads whatever is there at the moment it is clicked.
rem
rem  EDIT THESE TWO LINES, then never again.
rem ---------------------------------------------------------------------------

set "PROFILE_CSV=C:\Users\user\Desktop\Work\Projects\Work\VolumeProfile\example-fake-share\profile.csv"
set "OPEN_ON=RELIANCE.IN"

rem  PROFILE_CSV  the profile on the share. Always the same name; whatever is
rem               there when this is clicked is what gets shown. A mapped drive
rem               works too:  Z:\profiles\profile.csv
rem  OPEN_ON      instrument to open on, e.g. RELIANCE.IN. Leave empty to let
rem               the user pick from the list.
rem
rem  This file, the .ps1 and the .html all sit together on the user's machine.
rem  The share holds nothing but the CSV.
rem ===========================================================================

setlocal
set "VIEWER=%~dp0volume-profile.html"
set "RUNNER=%~dp0launch-volume-profile.ps1"

if not exist "%RUNNER%" (
  echo.
  echo   Missing: %RUNNER%
  echo   Keep this .bat next to launch-volume-profile.ps1 and volume-profile.html.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%RUNNER%" -Csv "%PROFILE_CSV%" -Template "%VIEWER%" -Select "%OPEN_ON%"

rem  On success the browser is open and this window closes on its own.
rem  On failure, hold it so the message can be read.
if errorlevel 1 (
  echo.
  pause
)
exit /b %errorlevel%
