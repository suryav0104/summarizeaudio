@echo off
:: SummarizeAudio Installer
:: Double-click this file to install SummarizeAudio on Windows.

echo.
echo  SummarizeAudio Installer
echo  ------------------------
echo  This will install SummarizeAudio and all required components.
echo  Internet connection required. First-time setup may take 10-20 minutes
echo  depending on your connection speed (AI model download is ~15 GB).
echo.
pause

PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

echo.
pause
