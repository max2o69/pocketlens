@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Allow PocketLens Network.ps1" -Remove
if errorlevel 1 pause
