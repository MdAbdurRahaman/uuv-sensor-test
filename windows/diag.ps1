# Collects network/dashboard diagnostics into diag.txt (run while the bench window is open)
$out = Join-Path $PSScriptRoot 'diag.txt'
$distro = 'Ubuntu-24.04'
$env:WSL_UTF8 = '1'
function T($title, [scriptblock]$b) { "`n===== $title =====" | Out-File $out -Append -Encoding utf8
  try { & $b 2>&1 | Out-String -Width 200 | Out-File $out -Append -Encoding utf8 } catch { "ERR: $_" | Out-File $out -Append -Encoding utf8 } }
"diag $(Get-Date -Format s)" | Out-File $out -Encoding utf8
T 'wsl --version' { wsl.exe --version }
T 'wsl -l -v' { wsl.exe -l -v }
T '.wslconfig' { $p = "$env:USERPROFILE\.wslconfig"; if (Test-Path $p) { Get-Content $p } else { 'no .wslconfig' } }
T 'WSL ip' { wsl.exe -d $distro -e hostname -I }
T 'listening :8765 inside WSL' { wsl.exe -d $distro -e bash -c "ss -ltnp 2>/dev/null | grep -E ':8765|State' || netstat -ltn | grep 8765" }
T 'curl inside WSL 127.0.0.1:8765' { wsl.exe -d $distro -e bash -c "curl -s -m 5 -o /dev/null -w 'HTTP %{http_code} in %{time_total}s\n' http://127.0.0.1:8765/ || echo 'curl failed/timed out'" }
T 'curl inside WSL /api/state' { wsl.exe -d $distro -e bash -c "curl -s -m 5 http://127.0.0.1:8765/api/state | head -c 600; echo" }
T 'ros2 nodes' { wsl.exe -d $distro -e bash -c "source /opt/ros/jazzy/setup.bash; source ~/ros2_ws/install/setup.bash; timeout 10 ros2 node list" }
T 'Windows -> localhost:8765' { curl.exe -s -m 5 -o NUL -w "HTTP %{http_code} in %{time_total}s`n" http://localhost:8765/ ; "exit $LASTEXITCODE" }
T 'Windows -> 127.0.0.1:8765' { curl.exe -s -m 5 -o NUL -w "HTTP %{http_code} in %{time_total}s`n" http://127.0.0.1:8765/ ; "exit $LASTEXITCODE" }
$ip = (wsl.exe -d $distro -e hostname -I).Trim().Split(' ')[0]
T "Windows -> WSL ip $ip :8765" { curl.exe -s -m 5 -o NUL -w "HTTP %{http_code} in %{time_total}s`n" "http://$($ip):8765/" ; "exit $LASTEXITCODE" }
T 'Windows proxy settings' { netsh winhttp show proxy; Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' | Select-Object ProxyEnable,ProxyServer,ProxyOverride,AutoConfigURL }
T 'port 8765 on Windows' { netstat -ano | Select-String ':8765' }
T 'serial devices in WSL' { wsl.exe -d $distro -e bash -c "ls -l /dev/serial/by-id/ 2>/dev/null; ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo 'no serial devices in WSL'" }
T 'usbipd list' { if (Get-Command usbipd -ErrorAction SilentlyContinue) { usbipd list } else { 'usbipd not installed' } }
$yamlWsl = (wsl.exe -d $distro -e wslpath -a "$PSScriptRoot\test_bench.yaml").Trim()
$nucleus = (wsl.exe -d $distro -e python3 -c "import re,sys;t=open(sys.argv[1]).read();m=re.search(r'/dvl:[\s\S]*?\n\s+host:\s*(\S+)',t);print(m.group(1) if m else '')" $yamlWsl).Trim()
T "ping Nucleus host $nucleus from WSL" { wsl.exe -d $distro -e ping -c 2 -W 2 $nucleus }
T "Nucleus data port 9002 from WSL" { wsl.exe -d $distro -e bash -c "timeout 4 bash -c '</dev/tcp/$nucleus/9002' && echo 'port 9002 open' || echo 'port 9002 NOT reachable'" }
"`nDONE" | Out-File $out -Append -Encoding utf8
Write-Host "Saved $out" -ForegroundColor Green
