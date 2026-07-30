@echo off
rem ===========================================================================
rem   VOLUME PROFILE  -  double-click this file
rem ---------------------------------------------------------------------------
rem   EDIT THE TWO LINES BELOW. Nothing else in this file needs touching.
rem ===========================================================================

set "VP_CSV=\\server\team\profiles\profile.csv"
set "VP_SELECT="

rem   VP_CSV     the profile on the share. Always the same name: whatever is
rem              there when you click is what you see. A mapped drive works
rem              too, e.g.  Z:\profiles\profile.csv
rem   VP_SELECT  instrument to open on, e.g. RELIANCE.IN
rem              Leave empty to choose from the list each time.
rem
rem ===========================================================================
rem   Everything below is the program. Leave it alone.
rem ===========================================================================

setlocal
set "VP_SELF=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:VP_SELF);$m='#'+'PS-BEGIN';$n='#'+'PS-END';$a=$t.IndexOf($m);$b=$t.IndexOf($n);if($a -lt 0 -or $b -le $a){Write-Host '';Write-Host '  This file is incomplete - it was probably damaged in transit.' -ForegroundColor Red;exit 9};Invoke-Expression $t.Substring($a+$m.Length,$b-$a-$m.Length)"

rem   Success closes on its own; a failure holds the window so it can be read.
if errorlevel 1 (
  echo.
  pause
)
exit /b %errorlevel%

#PS-BEGIN
$ErrorActionPreference = "Stop"

function Quit($msg, $code) {
    Write-Host ""
    Write-Host "  $msg" -ForegroundColor Red
    exit $code
}

$csv = $env:VP_CSV
$sel = $env:VP_SELECT

Write-Host ""
Write-Host "  Volume Profile" -ForegroundColor Cyan
Write-Host "  Reading $csv"

if ([string]::IsNullOrWhiteSpace($csv)) {
    Quit "No profile location set. Open this file in Notepad and put the share path in VP_CSV." 1
}
if (-not (Test-Path -LiteralPath $csv)) {
    Quit "Could not find the profile:`n`n    $csv`n`n  Check that the share is connected, then try again." 1
}

$csvText = [IO.File]::ReadAllText($csv)
if ($csvText -notmatch "(?i)cumulated") {
    Quit "That file has no CumulatedPercentage column, so it is not a volume profile export:`n`n    $csv" 3
}

# The viewer lives in this same file, after the marker below.
$self = [IO.File]::ReadAllText($env:VP_SELF)
$hm   = '<!--HTML-' + 'BEGIN-->'
$i    = $self.IndexOf($hm)
if ($i -lt 0) { Quit "This file is missing its viewer. Rebuild it with build-single-file.ps1." 4 }
$html = $self.Substring($i + $hm.Length)

# Hand the data to the page as a JavaScript string. ConvertTo-Json escapes
# quotes, backslashes and newlines, so any CSV content is safe to embed.
$payload = "<script>VP_PROFILE = " + (ConvertTo-Json $csvText) + ";" +
           "VP_PROFILE_NAME = " + (ConvertTo-Json ([IO.Path]::GetFileName($csv))) + ";"
if ($sel) { $payload += "VP_SELECT = " + (ConvertTo-Json $sel) + ";" }
$payload += "</script>"

$marker = '<script id="embeddedProfile"'
$j = $html.IndexOf($marker)
if ($j -lt 0) { Quit "The viewer inside this file is not the expected one." 4 }
$merged = $html.Substring(0, $j) + $payload + "`n" + $html.Substring($j)

# One fixed path, overwritten each run: a stable address the browser can keep,
# and nothing piles up on disk.
$outDir = Join-Path $env:LOCALAPPDATA "VolumeProfile"
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$out = Join-Path $outDir "volume-profile.html"
[IO.File]::WriteAllText($out, $merged, (New-Object Text.UTF8Encoding $false))

$rows = ([regex]::Matches($csvText, "`n")).Count
Write-Host ("  {0:N0} rows loaded. Opening..." -f $rows) -ForegroundColor Green
Start-Process $out
Start-Sleep -Milliseconds 700
exit 0
#PS-END
<!--HTML-BEGIN-->
