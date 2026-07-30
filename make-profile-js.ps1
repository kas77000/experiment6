<#
.SYNOPSIS
Wrap a volume profile CSV as the .js file the viewer reads from a shared drive.

.DESCRIPTION
The viewer is opened by double-click, so it runs on file://, where a browser
refuses to let a page fetch() or XHR a neighbouring file. A <script> tag is the
one exception: it is exempt from CORS and does read a sibling local file. So the
profile is published as one line of JavaScript rather than as raw CSV:

    VP_PROFILE = "…the whole CSV as a JSON string…";

Run this after whatever job drops the CSV on the share. Uses only Windows
PowerShell; nothing to install.

.EXAMPLE
  .\make-profile-js.ps1 -Csv today.csv -OutDir \\server\share\profiles
  # writes \\server\share\profiles\2026-07-30.js

.EXAMPLE
  .\make-profile-js.ps1 -Csv today.csv -Out \\server\share\profiles\latest.js

.EXAMPLE
  # the whole thing inline, if you would rather not keep a script around:
  "VP_PROFILE = " + (ConvertTo-Json ([IO.File]::ReadAllText("in.csv"))) + ";" |
      Set-Content -Encoding utf8 "out.js"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Csv,
    [string]$OutDir,
    [string]$Out,
    [string]$Date = (Get-Date).ToString("yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Csv)) { throw "No such CSV: $Csv" }
if (-not $Out) {
    if (-not $OutDir) { throw "Give -Out <file.js> or -OutDir <folder>" }
    if (-not (Test-Path -LiteralPath $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
    $Out = Join-Path $OutDir "$Date.js"
}

# [IO.File]::ReadAllText, not Get-Content -Raw: the latter carries extra
# properties that ConvertTo-Json serialises into an object instead of a string.
$text = [IO.File]::ReadAllText($Csv)

if ($text -notmatch "(?i)cumulated") {
    throw "$Csv has no CumulatedPercentage column. Is it a volume profile export?"
}

# ConvertTo-Json emits a JSON string, which is also a valid JavaScript string
# literal, so quotes, backslashes and newlines in the data are all handled.
"VP_PROFILE = " + (ConvertTo-Json $text) + ";" | Set-Content -LiteralPath $Out -Encoding utf8

$size = (Get-Item -LiteralPath $Out).Length
$rows = ([regex]::Matches($text, "`n")).Count
"wrote {0}" -f $Out
"  {0:N0} rows, {1:N0} KB" -f $rows, ($size / 1KB)
"  point the viewer at it with:  dataFile: ""profiles/{yyyy}-{mm}-{dd}.js"""
