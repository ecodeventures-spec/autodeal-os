@echo off
chcp 65001 >nul
title NUDHUJ AutoDeal OS - Autonomous Revenue SaaS Platform (autodeal.nudhuj.com)
echo ============================================================================
echo   ⚡ نضج | NUDHUJ AutoDeal OS — Autonomous Revenue & Proposals SaaS Platform
echo   🌐 Official Domain: https://autodeal.nudhuj.com
echo   🚀 Starting Unified SaaS Gateway on http://127.0.0.1:8000
echo ============================================================================
echo.
python -m src.cli dashboard --port 8000
pause
