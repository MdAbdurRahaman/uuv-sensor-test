# Shares USB serial adapters (Ping360 / Ping2) with WSL via usbipd-win, then
# identifies which port is which sensor and writes them into test_bench.yaml.
$ErrorActionPreference = 'Continue'
# usbipd bind needs administrator rights: re-launch elevated if needed.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host "Asking for administrator rights (click Yes)..." -ForegroundColor Yellow
  try {
    Start-Process powershell -Verb RunAs -Wait -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`"")
  } catch { Write-Host "Administrator rights were refused - the sensors cannot be shared with WSL without them." -ForegroundColor Red }
  return
}
Start-Transcript -Path (Join-Path $PSScriptRoot 'attach_log.txt') -Force | Out-Null
Write-Host "Windows COM ports:" -ForegroundColor Cyan
Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -match '\(COM\d+\)' } | ForEach-Object { Write-Host "  $($_.Name)   [$($_.DeviceID)]" }
$distro = 'Ubuntu-24.04'
function Find-Usbipd {
  $c = Get-Command usbipd -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($p in "$env:ProgramFiles\usbipd-win\usbipd.exe", "${env:ProgramFiles(x86)}\usbipd-win\usbipd.exe") { if (Test-Path $p) { return $p } }
  return $null
}
$usbipd = Find-Usbipd
if (-not $usbipd) {
  Write-Host "Installing usbipd-win (one time)..." -ForegroundColor Yellow
  winget install --id dorssel.usbipd-win -e --silent --accept-source-agreements --accept-package-agreements
  $usbipd = Find-Usbipd
  if (-not $usbipd) { Stop-Transcript | Out-Null; Write-Host "usbipd install failed. Install it from https://github.com/dorssel/usbipd-win/releases and run this again." -ForegroundColor Red; return }
}
wsl.exe -d $distro -e true | Out-Null   # WSL must be running for attach

$list = & $usbipd list
Write-Host "`nUSB devices:" -ForegroundColor Cyan
$list | ForEach-Object { Write-Host "  $_" }
$serial = @()
foreach ($line in $list) {
  if ($line -match '^\s*(\d+-\d+)\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.+?)\s{2,}(\S.*)$') {
    $busid = $Matches[1]; $desc = $Matches[3]; $state = $Matches[4]
    if ($desc -match 'Serial|UART|FT2|FTDI|CP210|CH34|CH9|PL230|USB-SERIAL|\(COM\d+\)') { $serial += [pscustomobject]@{Busid=$busid; Desc=$desc; State=$state} }
  }
}
if (-not $serial) {
  Write-Host "`nNo USB serial adapter recognised automatically." -ForegroundColor Yellow
  $ids = Read-Host "Type the BUSID(s) of the sensors from the list above (e.g. 1-3 1-4)"
  $serial = $ids -split '\s+' | Where-Object { $_ } | ForEach-Object { [pscustomobject]@{Busid=$_; Desc='manual'; State=''} }
}
foreach ($d in $serial) {
  Write-Host "`nSharing $($d.Busid)  $($d.Desc)" -ForegroundColor Cyan
  if ($d.State -notmatch '^(Shared|Attached)') {
    # --force is required when a USB filter driver such as USBPcap (Wireshark) is installed.
    # Effect: Windows apps can't use this COM port until 6_RELEASE_USB_TO_WINDOWS.bat is run.
    & $usbipd bind --force --busid $d.Busid 2>&1 | Out-Host
    Start-Sleep 2
  }
  if ($d.State -notmatch '^Attached') {
    $ok = $false
    for ($i = 0; $i -lt 3 -and -not $ok; $i++) {
      $r = & $usbipd attach --wsl --busid $d.Busid 2>&1
      $r | Out-Host
      $ok = ($LASTEXITCODE -eq 0)
      if (-not $ok) { Start-Sleep 2 }
    }
  }
}
Start-Sleep 3
Write-Host "`nSerial ports in WSL:" -ForegroundColor Cyan
wsl.exe -d $distro -e bash -c "ls -l /dev/serial/by-id/ 2>/dev/null || ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo none"

Write-Host "`nIdentifying sensors (Ping360 vs Ping2)..." -ForegroundColor Cyan
$here = (wsl.exe -d $distro -e wslpath -a "$PSScriptRoot").Trim()
wsl.exe -d $distro -e python3 "$here/identify_sensors.py" "$here/test_bench.yaml"
Stop-Transcript | Out-Null
Write-Host "`nDone. Note: after unplugging a sensor or restarting Windows, run this again." -ForegroundColor Green
Read-Host "Press Enter to close"
