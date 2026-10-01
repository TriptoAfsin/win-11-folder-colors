<#
  One-time setup: Python packages + Resource Hacker.

  Resource Hacker's licence only allows redistribution of its complete ZIP, so
  it isn't committed here. This downloads the official ZIP from angusj.com and
  unpacks it whole into tools\ResourceHacker\.
#>
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3 not found on PATH. Install it from https://www.python.org/downloads/ (tick "Add to PATH").'
}
Write-Host 'Installing Python packages (pillow, numpy, pefile)...'
& python -m pip install --quiet --disable-pip-version-check -r (Join-Path $here 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

$rhDir = Join-Path $here 'tools\ResourceHacker'
$rhExe = Join-Path $rhDir 'ResourceHacker.exe'
if (Test-Path $rhExe) {
    Write-Host 'Resource Hacker already present.'
} else {
    Write-Host 'Downloading Resource Hacker from angusj.com...'
    New-Item -ItemType Directory -Force $rhDir | Out-Null
    $zip = Join-Path $env:TEMP 'resource_hacker.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest 'https://www.angusj.com/resourcehacker/resource_hacker.zip' -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $rhDir -Force
    Remove-Item $zip
    if (-not (Test-Path $rhExe)) { throw 'ResourceHacker.exe missing after unzip' }
}
Write-Host 'Setup done. Next: .\apply.cmd blue'
