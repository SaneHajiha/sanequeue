@echo off
setlocal
powershell -NoProfile -Command "try {$r=Invoke-WebRequest -Uri 'http://127.0.0.1:18895/__sanequeue__/build' -UseBasicParsing -TimeoutSec 3; $r.Content} catch { Write-Host '[ERROR] Port 18895 did not return the expected build info:' $_.Exception.Message }"
pause
