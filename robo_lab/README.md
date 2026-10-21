# Robo Lab B3 (`robo_lab`) — Mineração de Estratégias do YouTube, Backtest Exaustivo Multi-Timeframe e Adaptação Causal ao Sentimento de Mercado

Módulo independente dedicado a:
1. **Minerar canais inteiros do YouTube** em busca de vídeos que ensinam setups, indicadores, regras de entrada/saída e robôs de Day Trade e Swing Trade na B3 (Ibovespa `^BVSP`, Mini-Índice `WIN$N`, Mini-Dólar `WDO$N`, ações `VALE3.SA`, `PETR4.SA`, `ITUB4.SA`, `BBAS3.SA`, etc.).
2. **Programar robôs parametrizáveis** (`BotSpec` + geradores vetorizados) com motor universal de filtros (`FilterConfig`: tendência, volume, volatilidade ATR, janela de sessão intradiária e direção `long_only`/`short_only`/`both`).
3. **Exaurir parâmetros e filtros** em múltiplos timeframes (`5m`, `15m`, `60m`, `1d`, `1wk`) até descobrir exatamente quando e com quais filtros cada robô tem expectativa matemática positiva.
4. **Classificar o Sentimento de Mercado** em duas camadas complementares:
   - **Ex-Post (Oráculo Mensal & Perfil Diário)**: classifica cada mês (`ALTA`, `LATERAL`, `BAIXA`) e cada dia da bolsa (`VOLUME_ALTO`/`NORMAL`/`BAIXO` e `DIA_DIRECIONAL_ALTA`/`BAIXA`/`DIA_LATERAL_OSCILANTE`).
   - **Causal / Tempo Real (`causal_regime`, Zero Look-Ahead)**: responde à pergunta central *"se a estratégia X funciona em mês de alta, como usá-la sem saber de antemão que o mês será de alta?"*, utilizando apenas dados fechados até a barra anterior ($t-1$) via **Kaufman Efficiency Ratio ($ER_{10}$)**, **$ADX_{14}$**, **alinhamento e inclinação de médias ($EMA_{20}$, $EMA_{50}$, $EMA_{200}$)** e **momentum de 5/15 barras**.
5. **Exportar código MQL5 (`.mq5`)** pronto para compilar no MetaEditor do MetaTrader 5 já com o Detector Causal de Regime (`DetectCausalMarketRegime()`) embutido.

---

## Estrutura de Diretórios

```text
robo_lab/
├── __init__.py
├── __main__.py                 # CLI principal (python -m robo_lab ...)
├── config.py                   # Ativos B3, timeframes, custos B3/slippage
├── data_feed.py                # MultiTimeframeDataFeed (SQLite cache + MT5 local + resampling)
├── ingestion/
│   ├── youtube_channel_miner.py # Varredura de canais, transcrições PT-BR e catálogo de setups
│   └── sync_external.py        # Script de sincronização de vídeos, transcrições e cotações B3
├── regime/
│   └── market_sentiment.py     # Classificador Ex-Post + Detector Causal Zero Look-Ahead (t-1)
├── strategies/
│   ├── base_bot.py             # Estrutura BotSpec + FilterConfig universal
│   ├── bots_norisknogain.py    # 10 robôs extraídos do canal @norisknogainoficial
│   └── mt5_exporter.py         # Gerador automático de Expert Advisors (.mq5) para MT5
├── backtester/
│   ├── engine.py               # Simulador barra-a-barra + segmentação por regime e perfil diário
│   ├── optimizer.py            # Grid search exaustivo + Meta-Seletor Causal e Oráculo
│   └── reports.py              # Gerador de relatórios JSON + Markdown
└── data/
    ├── market_cache.db         # Cache SQLite multi-timeframe (^BVSP, VALE3, PETR4, ITUB4, etc.)
    ├── channels/
    │   └── norisknogainoficial/
    │       ├── channel_manifest.json   # 250 vídeos varridos (218 vídeos de robôs/setups)
    │       ├── strategy_catalog.json   # Catálogo classificado por família de setup
    │       └── transcripts/            # 23 transcrições completas extraídas dos vídeos
    └── reports/
        ├── norisknogain_full_arena.json
        └── RELATORIO_ROBOS_NORISKNOGAIN.md
```

---

## Como Executar via CLI

### 1. Exibir o catálogo minerado do canal e famílias de setups
```powershell
python -m robo_lab catalog
```

### 2. Rodar a Arena Exaustiva Multi-Timeframe e gerar relatórios
```powershell
python -m robo_lab arena --symbols "^BVSP" VALE3.SA PETR4.SA --timeframes 5m 15m 60m 1d 1wk --max-combos 6
```

### 3. Exportar um Robô Otimizado para MetaTrader 5 (`.mq5`)
```powershell
python -m robo_lab export-mt5 --bot NRNG-009 --symbol "WIN$N" --timeframe 15m
```

### 4. Sincronizar vídeos/transcrições de um canal e atualizar dados de mercado
```powershell
python -m robo_lab.ingestion.sync_external
```
