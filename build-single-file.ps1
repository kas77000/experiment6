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
  .\build-single-file.ps1 -Csv "\\server\team\profiles\profile.csv"
#>
[CmdletBinding()]
param(
    [string]$Viewer   = (Join-Path $PSScriptRoot "volume-profile.html"),
    [string]$Template = (Join-Path $PSScriptRoot "launcher\single-file-template.bat"),
    [string]$Out      = (Join-Path $PSScriptRoot "Volume-Profile.bat"),
    [string]$Csv      = ""
)

$ErrorActionPreference = "Stop"

foreach ($p in @($Viewer, $Template)) {
    if (-not (Test-Path -LiteralPath $p)) { throw "Missing: $p" }
}

$tpl  = [IO.File]::ReadAllText($Template)
$html = [IO.File]::ReadAllText($Viewer)

# The launcher appends a small driver script after the viewer's own and calls
# what is already defined there. Every one of those names is checked here, so a
# rename in the viewer fails the build instead of failing on a client's screen.
$requires = [ordered]@{
    '</body>'            = 'the closing body tag the driver is appended before'
    'function boot('     = 'boot(), which loads a parsed profile'
    'function parseCSV(' = 'parseCSV(), which reads the CSV text'
    'function showErr('  = 'showErr(), used to report an unreadable profile'
    'function pick('     = 'pick(), used when the file holds one instrument'
    'id="btnNew"'        = 'the Open-another-file button the driver hides'
    'id="fileSub"'       = 'the sub-heading the driver rewrites'
}
$missing = @()
foreach ($k in $requires.Keys) { if (-not $html.Contains($k)) { $missing += "  $k   ($($requires[$k]))" } }
if ($missing) {
    throw ("$Viewer no longer provides what the launcher calls:`n" + ($missing -join "`n") +
           "`n`nEither restore those names, or update the driver in $Template.")
}
# The batch header is only safe if cmd never reaches the payload, and it never
# does: the header exits first. But a stray marker would break extraction.
foreach ($m in @('#PS-BEGIN', '#PS-END')) {
    if ($html.Contains($m)) { throw "The viewer contains the marker $m, which would break extraction." }
}

# Normalise to LF first: with CRLF still in place, "$" in a multiline regex sits
# after the \r and the substitution below silently matches nothing.
$tpl = $tpl -replace "`r`n", "`n"

if ($Csv) {
    $before = $tpl
    $tpl = [regex]::Replace($tpl, '(?m)^set "VP_CSV=.*"$', 'set "VP_CSV=' + $Csv + '"')
    if ($tpl -eq $before) { throw "Could not set VP_CSV: the template line was not found." }
}

# CRLF for the batch header so cmd parses it, and no BOM: a BOM at byte 0 makes
# cmd choke on the first line, and .NET reads BOM-less files as UTF-8 anyway.
$tpl = $tpl -replace "`n", "`r`n"
[IO.File]::WriteAllText($Out, $tpl + $html, (New-Object Text.UTF8Encoding $false))

# Read the result back and confirm it is the shape the .bat will look for at run
# time, so a build never hands over a file that fails on the first click.
$built = [IO.File]::ReadAllText($Out)
$b = [IO.File]::ReadAllBytes($Out)
$checks = [ordered]@{
    'starts with @echo'   = ($b[0] -eq 0x40 -and $b[1] -eq 0x65)
    'no byte-order mark'  = -not ($b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF)
    'PowerShell section'  = ($built.IndexOf('#PS-BEGIN') -gt 0 -and
                             $built.IndexOf('#PS-END') -gt $built.IndexOf('#PS-BEGIN'))
    'viewer attached'     = ($built.IndexOf('<!--HTML-BEGIN-->') -gt 0 -and
                             $built.LastIndexOf('</html>') -gt $built.IndexOf('<!--HTML-BEGIN-->'))
}
$bad = $checks.Keys | Where-Object { -not $checks[$_] }
if ($bad) {
    Remove-Item -LiteralPath $Out -Force
    throw ("The built file failed its own check (" + ($bad -join ", ") + "). Nothing was written.")
}

$size = (Get-Item -LiteralPath $Out).Length
# \r?$ , not $ : the built file is CRLF, and "$" sits after the \r, so a plain
# "$" here matches nothing. Same trap as the VP_CSV substitution above.
$csvLine = ([regex]::Match($built, '(?m)^set "VP_CSV=(.*)"\r?$')).Groups[1].Value
""
"wrote $Out"
"  {0:N0} KB, one file, nothing else needed" -f ($size / 1KB)
"  reads: $csvLine"
""
if ($csvLine -like '\\server\team\*') {
    "  NOTE: that is still the placeholder path. Set VP_CSV before handing this out."
} else {
    "  Ready to hand out."
}
