@echo off
title Agente MT5 - Copiloto de Trades
pushd "%~dp0"
echo ============================================================
echo   AGENTE MT5 DO COPILOTO (rode no Windows com o MetaTrader 5)
echo ============================================================
echo.
echo Requisitos: terminal MT5 aberto e conta logada ("Algo Trading" ligado para ordens).
echo Somente cotacoes (recusa ordens): start_mt5_agent.bat --readonly
echo Token: MT5_AGENT_TOKEN em config\.env (o mesmo do Copiloto no Docker).
echo Libere a porta 8765 no Firewall do Windows para o IP do homelab.
echo.
python -m pip show MetaTrader5 >nul 2>&1 || python -m pip install MetaTrader5 flask python-dotenv pyyaml requests
python -m src.execution.agent --host 0.0.0.0 --port 8765 %*
popd
pause
