@echo off
rem ===========================================================================
rem   VOLUME PROFILE  -  double-click this file
rem ---------------------------------------------------------------------------
rem   EDIT THE ONE LINE BELOW. Nothing else in this file needs touching.
rem ===========================================================================

set "VP_CSV=\\server\team\profiles\profile.csv"

rem   VP_CSV   the profile on the share. Always the same name: whatever is
rem            there when you click is what you see. A mapped drive works
rem            too, e.g.  Z:\profiles\profile.csv
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

# The viewer itself knows nothing about any of this: it is the plain
# choose-a-file page. So the data is appended after its own script, as a second
# script that calls the functions already defined there. ConvertTo-Json escapes
# quotes, backslashes and newlines, so any CSV content is safe to embed.
#
# No instrument is chosen here. Which one comes first varies from file to file,
# so the page opens on the list and the user picks.
$name = [IO.Path]::GetFileName($csv)
$driver = @"
<script>
(function () {
  var csv = $(ConvertTo-Json $csvText);
  var name = $(ConvertTo-Json $name);
  try { boot(parseCSV(csv), name); }
  catch (e) { showErr("The profile could not be read: " + e.message); return; }
  document.getElementById("btnNew").classList.add("hidden");
  document.getElementById("fileSub").textContent =
    name + "  ·  " + DATA.list.length + " instrument" + (DATA.list.length > 1 ? "s" : "");
  if (DATA.list.length === 1) { pick(0); }
})();
</script>
"@

$marker = '</bo' + 'dy>'
$j = $html.LastIndexOf($marker)
if ($j -lt 0) { Quit "The viewer inside this file is not the expected one." 4 }
$merged = $html.Substring(0, $j) + $driver + $html.Substring($j)

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
