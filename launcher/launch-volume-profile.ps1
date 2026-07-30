<#
    Reads the CSV from the share, drops it into a copy of the viewer, and opens
    that copy in the default browser.

    Called by Open-Volume-Profile.bat. Not meant to be run by the user directly.

    The CSV keeps its own name and format: nothing about the daily job changes.
    The merged page is written to the user's temp folder, so the share stays
    read-only and two people opening it at once never collide.
#>
[CmdletBinding()]
param(
    [string]$Csv,
    [string]$Template,
    [string]$Select = ""
)

$ErrorActionPreference = "Stop"

# Report and leave. The .bat pauses on a non-zero exit, so the window stays open
# for the user to read it; never block here, or an unattended run hangs forever.
function Quit($msg, $code) {
    Write-Host ""
    Write-Host "  $msg" -ForegroundColor Red
    exit $code
}

Write-Host ""
Write-Host "  Volume Profile" -ForegroundColor Cyan
Write-Host "  Reading $Csv"

if (-not (Test-Path -LiteralPath $Csv)) {
    Quit "Could not find the profile:`n`n    $Csv`n`n  Check that the share is connected, then try again." 1
}
if (-not (Test-Path -LiteralPath $Template)) {
    Quit "Could not find the viewer:`n`n    $Template" 2
}

$csvText = [IO.File]::ReadAllText($Csv)
if ($csvText -notmatch "(?i)cumulated") {
    Quit "That file has no CumulatedPercentage column, so it is not a volume profile export:`n`n    $Csv" 3
}

$html = [IO.File]::ReadAllText($Template)

# Hand the data straight to the page as a JavaScript string. ConvertTo-Json
# escapes quotes, backslashes and newlines, so any CSV content is safe here.
$payload = "<script>VP_PROFILE = " + (ConvertTo-Json $csvText) + ";" +
           "VP_PROFILE_NAME = " + (ConvertTo-Json ([IO.Path]::GetFileName($Csv))) + ";"
if ($Select) { $payload += "VP_SELECT = " + (ConvertTo-Json $Select) + ";" }
$payload += "</script>"

# Injected before the viewer's own script, which then finds VP_PROFILE waiting.
$marker = '<script id="embeddedProfile"'
$i = $html.IndexOf($marker)
if ($i -lt 0) { Quit "That viewer file is not the expected one: no embeddedProfile marker found." 4 }
$merged = $html.Substring(0, $i) + $payload + "`n" + $html.Substring($i)

$outDir = Join-Path $env:TEMP "volume-profile"
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
$out = Join-Path $outDir ("profile-" + (Get-Date).ToString("yyyyMMdd-HHmmss") + ".html")
[IO.File]::WriteAllText($out, $merged, (New-Object Text.UTF8Encoding $false))

# Yesterday's merged copies are of no use to anyone
Get-ChildItem $outDir -Filter "profile-*.html" -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-1) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$rows = ([regex]::Matches($csvText, "`n")).Count
Write-Host ("  {0:N0} rows loaded. Opening..." -f $rows) -ForegroundColor Green
Start-Process $out
Start-Sleep -Milliseconds 900
