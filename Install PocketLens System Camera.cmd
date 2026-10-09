@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install PocketLens System Camera.ps1"
if errorlevel 1 pause
