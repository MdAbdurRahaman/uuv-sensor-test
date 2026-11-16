# Gives the sensor USB adapters back to Windows (e.g. for Ping Viewer): detach + unbind.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Start-Process powershell -Verb RunAs -Wait -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$PSCommandPath`""); return }
$usbipd = (Get-Command usbipd -ErrorAction SilentlyContinue).Source
if (-not $usbipd) { $usbipd = "$env:ProgramFiles\usbipd-win\usbipd.exe" }
foreach ($line in (& $usbipd list)) {
  if ($line -match '^\s*(\d+-\d+)\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+(.+?)\s{2,}(Shared|Attached).*$') {
    if ($Matches[3] -match 'Serial|UART|FT2|FTDI|CP210|CH34|USB-SERIAL') {
      Write-Host "Releasing $($Matches[1]) $($Matches[3])"
      & $usbipd detach --busid $Matches[1] 2>&1 | Out-Host
      & $usbipd unbind --busid $Matches[1] 2>&1 | Out-Host
    }
  }
}
& $usbipd list
Read-Host "Done - the COM ports are back in Windows. Press Enter to close"
