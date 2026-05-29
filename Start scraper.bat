@echo off
title Debatstof-scraper

echo ============================================
echo Starter debatstof-scraper...
echo ============================================
echo.

cd /d "%~dp0"

python run_scraper.py

echo.
echo JSON-output:
echo output\latest\articles.json

echo.
echo ============================================
echo Scraper-korsel afsluttet.
echo Luk vinduet eller tryk en tast.
echo ============================================

pause
