@echo off
title Copiloto de Trades
cd /d "%~dp0"
echo ============================================================
echo   COPILOTO DE TRADES
echo ============================================================
echo.
echo Abrindo em http://127.0.0.1:5000 ...
echo Mantenha esta janela aberta (o monitor de sinais roda aqui).
echo Pressione Ctrl+C para encerrar.
echo.
start "" /b cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:5000"
python web_app.py
pause
