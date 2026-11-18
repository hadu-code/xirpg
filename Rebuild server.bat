@echo off
title Rebuild XIRPG server
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rebuild.ps1"
echo.
echo You can close this window now.
pause
