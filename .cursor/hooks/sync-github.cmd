@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "[Console]::In.ReadToEnd() | Out-Null; Start-Process -WindowStyle Hidden -FilePath powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0..\..\scripts\sync-github.ps1'"
echo {}
