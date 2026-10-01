<#
  Recolor Windows 11 folder icons system-wide (keeps content thumbnails).

    .\apply.ps1 blue        # or green, purple, black, gray, teal, red, orange, pink
    .\apply.ps1 yellow      # restore stock Windows icons from the backup

  The first run backs up the stock C:\Windows\SystemResources\imageres.dll.mun to
  .\backup\. After a Windows update reverts the file, just run this again: it
  detects the fresh stock file, re-backs it up and re-applies your color.
#>
param([string]$Color, [switch]$Elevated)

$ErrorActionPreference = 'Stop'
$here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$sysDir  = 'C:\Windows\SystemResources'
$sysFile = Join-Path $sysDir 'imageres.dll.mun'
$bakDir  = Join-Path $here 'backup'
$bakFile = Join-Path $bakDir 'imageres.dll.mun.original'
$state   = Join-Path $here 'state.json'
$colors  = 'blue','green','purple','black','gray','teal','red','orange','pink','yellow'

if (-not $Color) {
    Write-Host "Colors: $($colors -join ', ')"
    $Color = Read-Host 'Pick a color'
}
$Color = $Color.ToLower()
if ($colors -notcontains $Color) { throw "Unknown color '$Color'. Choose: $($colors -join ', ')" }

# --- first run: fetch Resource Hacker + Python packages ---
if ($Color -ne 'yellow' -and -not (Test-Path (Join-Path $here 'tools\ResourceHacker\ResourceHacker.exe'))) {
    & (Join-Path $here 'setup.ps1')
}

# --- self-elevate (one UAC prompt) ---
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList @(
        '-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$($MyInvocation.MyCommand.Path)`"",$Color,'-Elevated')
    # restart Explorer un-elevated
    if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
    Get-Content (Join-Path $here 'apply.log') -Tail 25
    exit $p.ExitCode
}

Start-Transcript -Path (Join-Path $here 'apply.log') -Force | Out-Null
try {
    New-Item -ItemType Directory -Force $bakDir | Out-Null
    $sysHash = (Get-FileHash $sysFile -Algorithm SHA256).Hash
    $st = if (Test-Path $state) { Get-Content $state -Raw | ConvertFrom-Json } else { $null }

    # --- keep a pristine backup ---
    $sysIsOurs = $st -and $st.patchedHash -eq $sysHash
    if (-not $sysIsOurs) {
        $bakHash = if (Test-Path $bakFile) { (Get-FileHash $bakFile -Algorithm SHA256).Hash } else { '' }
        if ($bakHash -ne $sysHash) {
            if ($bakHash) { Move-Item $bakFile "$bakFile.$(Get-Date -Format yyyyMMdd-HHmmss)" }
            Copy-Item $sysFile $bakFile
            $ver = (Get-Item $sysFile).VersionInfo.FileVersion
            "Backed up stock imageres.dll.mun (OS $([Environment]::OSVersion.Version), file $ver)" | Write-Host
        }
    }

    # --- build the new file (on a temp copy) ---
    $newFile = Join-Path $env:TEMP 'imageres.dll.mun.new'
    if ($Color -eq 'yellow') {
        Copy-Item $bakFile $newFile -Force
    } else {
        & python (Join-Path $here 'folder_colors.py') patch $Color $bakFile $newFile
        if ($LASTEXITCODE -ne 0) { throw 'patch step failed; system file untouched' }
    }

    # --- swap into SystemResources ---
    Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue
    $aclSave = Join-Path $env:TEMP 'sysres_acl.txt'
    icacls $sysDir /save $aclSave | Out-Null
    takeown /f $sysDir /a | Out-Null
    icacls $sysDir /grant '*S-1-5-32-544:(F)' | Out-Null
    takeown /f $sysFile /a | Out-Null
    icacls $sysFile /grant '*S-1-5-32-544:(F)' | Out-Null

    $old = "$sysFile.old"
    if (Test-Path $old) {
        try { Remove-Item $old -Force } catch { Rename-Item $old "$old.$([DateTime]::Now.Ticks)" }
    }
    Rename-Item $sysFile $old
    try {
        Copy-Item $newFile $sysFile
    } catch {
        Rename-Item $old $sysFile   # put the original back
        throw
    }
    icacls $sysFile /inheritance:r /grant:r 'NT SERVICE\TrustedInstaller:(F)' '*S-1-5-32-544:(RX)' `
        '*S-1-5-18:(RX)' '*S-1-5-32-545:(RX)' '*S-1-15-2-1:(RX)' '*S-1-15-2-2:(RX)' | Out-Null
    icacls $sysFile /setowner 'NT SERVICE\TrustedInstaller' /q

    # restore the folder's original permissions + owner
    icacls 'C:\Windows' /restore $aclSave | Out-Null
    icacls $sysDir /setowner 'NT SERVICE\TrustedInstaller' /q

    $newHash = (Get-FileHash $sysFile -Algorithm SHA256).Hash
    @{ color = $Color; patchedHash = $(if ($Color -eq 'yellow') { '' } else { $newHash });
       appliedAt = (Get-Date).ToString('s') } | ConvertTo-Json | Set-Content $state -Encoding utf8

    # --- clear icon + thumbnail caches ---
    $exp = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Explorer'
    Get-ChildItem $exp -Filter 'iconcache_*.db' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem $exp -Filter 'thumbcache_*.db' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:LOCALAPPDATA 'IconCache.db') -Force -ErrorAction SilentlyContinue
    Write-Host "Applied '$Color'."
}
catch {
    Write-Host "FAILED: $_"
    exit 1
}
finally {
    # when launched from a normal prompt the un-elevated parent restarts Explorer
    if (-not $Elevated -and -not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
    Stop-Transcript | Out-Null
}
