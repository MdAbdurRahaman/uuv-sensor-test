# Waits for the dashboard and opens it at whichever address answers (localhost or the WSL IP).
param([int]$Port = 8765)
$distro = 'Ubuntu-24.04'
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
  $urls = @("http://localhost:$Port/")
  try { $ip = (wsl.exe -d $distro -e hostname -I).Trim().Split(' ')[0]; if ($ip) { $urls += "http://$($ip):$Port/" } } catch {}
  foreach ($u in $urls) {
    try { $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { Start-Process $u; exit } } catch {}
  }
  Start-Sleep -Seconds 2
}
