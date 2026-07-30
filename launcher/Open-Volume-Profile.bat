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

set "PROFILE_CSV=%~dp0profile.csv"
set "OPEN_ON="

rem  PROFILE_CSV  where the profile lives. %~dp0 means "this folder", so leave
rem               it as-is if the CSV sits beside this file. Otherwise put the
rem               full path, e.g.  \\server\team\profiles\profile.csv
rem  OPEN_ON      instrument to open on, e.g. RELIANCE.IN. Leave empty to let
rem               the user pick from the list.
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
