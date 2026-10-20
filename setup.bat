@echo off
rem OpenCaster setup: double-click this file.  It runs setup.ps1, which
rem installs Python packages and adds Desktop / Start Menu shortcuts.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
echo.
pause
