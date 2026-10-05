# Módulo de Estratégias & Base de Conhecimento Quantitativa

Este diretório contém a infraestrutura de inteligência de trades do sistema. Ele reúne:
1. **Avaliação Multi-Fonte de Trades**: Mineração dos trades do TradingFloor e ingestão de canais e vídeos do YouTube.
2. **Metodologia Quantitativa de Padrões**: Definição de métricas de performance, clustering de trades e classificação de setups.
3. **Motor de Backtest em Cenários Similares**: Simulação de estratégias em dados históricos reais de mercado (B3).
4. **Base de Conhecimento Centralizada**: Catálogo de fichas técnicas padronizadas com regras de entrada, saída, dimensionamento e risco.
5. **Screeners de Mercado**: Varredura ativa em busca de oportunidades com as regras das estratégias catalogadas.

---

## Estrutura de Diretórios

```
strategies/
├── config.yaml                     # Parâmetros de screener, backtest e ingestão
├── README.md                       # Documentação geral
│
├── knowledge_base/                 # Base de Conhecimento de Estratégias
│   ├── catalog.json                # Índice central de estratégias catalogadas
│   ├── youtube/                    # Estratégias extraídas do YouTube por canal
│   │   └── jimmy_carvalho/
│   │       ├── channel_profile.json
│   │       └── STRAT-YT-001_venda_put_300cdi.md
│   └── trading_floor/              # Estratégias mineradas do TradingFloor
│       ├── tf_patterns_report.md
│       ├── tf_traders_profile.json
│       └── setups/
│           ├── STRAT-TF-001_brondi_winfut_scalp.md
│           ├── STRAT-TF-002_calvete_wdofut_trend.md
│           └── STRAT-TF-003_opcoes_eleicoes_b3.md
│
├── methodology/                    # Metodologia & Classificação Quantitativa
│   ├── framework.md                # Fórmulas estatísticas e critérios de validação
│   ├── strategy_schema.py          # Modelo de dados de estratégias
│   └── pattern_detector.py         # Detecção e agrupamento de padrões em trades
│
├── ingestion/                      # Pipelines de Ingestão
│   ├── youtube_crawler.py          # Analisador automático de canais do YouTube
│   ├── strategy_extractor.py       # Extrator estruturado a partir de transcrições
│   └── tf_extractor.py             # Mineração contínua de trades do TradingFloor
│
├── backtesting/                    # Motores de Simulação Histórica
│   ├── price_data_feed.py          # Provedor de cotações diárias com cache
│   ├── option_backtester.py        # Simulador de Venda de Puts OTM (-1 ATR)
│   └── backtest_runner.py          # Executor unificado de backtest
│
└── screeners/                      # Scanners de Mercado Ativos
    ├── put_selling_screener.py     # Screener da estratégia de Put OTM (-1 ATR)
    └── market_screener.py          # Scanner consolidado de setups
```

---

## Como Utilizar

### 1. Rastrear e Analisar Canal/Vídeo do YouTube
Para inspecionar um novo vídeo, listar os vídeos com estratégias do mesmo canal e extrair o setup:
```bash
python strategies/ingestion/youtube_crawler.py --video "https://www.youtube.com/watch?v=L48NBs21q6g"
```

### 2. Rodar o Screener de Mercado em Tempo Real
Busca na B3 os ativos que preenchem as regras da estratégia STRAT-YT-001 (VALE3, PETR4, ITUB4, etc.):
```bash
python strategies/screeners/put_selling_screener.py
```

### 3. Executar o Backtest de Opções (-1 ATR)
Simula a estratégia de venda de Put em VALE3 ou PETR4 ao longo dos últimos anos comparando com o CDI:
```bash
python strategies/backtesting/option_backtester.py --ticker VALE3.SA --years 10
```

### 4. Recalcular Padrões do TradingFloor
Gera o relatório atualizado de win rate e perfil de todos os traders:
```bash
python strategies/methodology/pattern_detector.py
```
