<#
.SYNOPSIS
Glue the viewer and the launcher into ONE double-clickable .bat file.

.DESCRIPTION
Produces a single file the user copies to their machine and clicks. It carries
the whole viewer inside it, reads the CSV from the share at click time, and
opens the result in the browser. Nothing else is installed and nothing but the
CSV lives on the share.

Run this once, and again whenever volume-profile.html changes.

.EXAMPLE
  .\build-single-file.ps1
  .\build-single-file.ps1 -Csv "\\server\team\profiles\profile.csv" -Select RELIANCE.IN
#>
[CmdletBinding()]
param(
    [string]$Viewer   = (Join-Path $PSScriptRoot "volume-profile.html"),
    [string]$Template = (Join-Path $PSScriptRoot "launcher\single-file-template.bat"),
    [string]$Out      = (Join-Path $PSScriptRoot "Volume-Profile.bat"),
    [string]$Csv      = "",
    [string]$Select   = ""
)

$ErrorActionPreference = "Stop"

foreach ($p in @($Viewer, $Template)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "Missing: $p" }
}

$tpl  = [IO.File]::ReadAllText($Template)
$html = [IO.File]::ReadAllText($Viewer)

if ($html -notmatch '<script id="embeddedProfile"') {
    throw "$Viewer has no embeddedProfile marker; is it the right file?"
}
# The batch header is only safe if cmd never reaches the payload, and it never
# does: the header exits first. But a stray marker would break extraction.
foreach ($m in @('#PS-BEGIN', '#PS-END')) {
    if ($html.Contains($m)) { throw "The viewer contains the marker $m, which would break extraction." }
}

if ($Csv)    { $tpl = [regex]::Replace($tpl, '(?m)^set "VP_CSV=.*"$',    'set "VP_CSV=' + $Csv + '"') }
if ($Select) { $tpl = [regex]::Replace($tpl, '(?m)^set "VP_SELECT=.*"$', 'set "VP_SELECT=' + $Select + '"') }

# CRLF for the batch header so cmd parses it, and no BOM: a BOM at byte 0 makes
# cmd choke on the first line, and .NET reads BOM-less files as UTF-8 anyway.
$tpl = $tpl -replace "`r`n", "`n" -replace "`n", "`r`n"
[IO.File]::WriteAllText($Out, $tpl + $html, (New-Object Text.UTF8Encoding $false))

$size = (Get-Item -LiteralPath $Out).Length
""
"wrote $Out"
"  {0:N0} KB, one file, nothing else needed" -f ($size / 1KB)
""
"  Next: open it in Notepad and set VP_CSV to the share path, then double-click it."
