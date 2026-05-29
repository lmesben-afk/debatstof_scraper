@echo off
title Debatstof-radar app v8.3

echo ============================================
echo Starter Debatstof-radar app v8.3...
echo ============================================
echo.
echo Appen laeser data fra:
echo C:\Users\Esben.L.Mikkelsen\OneDrive - JP Politikens Hus\Jyllands-Posten\Scrapere\Fælles-data
echo.
echo Appen aabner paa:
echo http://127.0.0.1:5057
echo.

cd /d "%~dp0"

start http://127.0.0.1:5057

python -m flask --app app/app.py run --debug --port 5057

pause
