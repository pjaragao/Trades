# STRAT-TF-002: Níveis e Pullback em Mini-Índice B3 (Trader Calvete)

- **ID**: `STRAT-TF-002`
- **Fonte**: TradingFloor (Trader Calvete)
- **Classe de Ativo**: Futuros B3 (WINFUT)
- **Status**: Ativo / Validado
- **Estilo**: Day Trade / Pullback & Suporte/Resistência

---

## 1. Tese Operacional & Vantagem Estatística (Edge)
Calvete é um dos traders de maior volume histórico da plataforma TradingFloor (510 operações concluídas).
Sua abordagem foca no Mini-Índice Futuro (WINFUT) com entradas posicionadas em zonas de teste de níveis técnicos (máximas e mínimas do dia anterior, VWAP e médias de referência intraday).
- **Vantagem Estatística**: Mesmo com taxa de acerto moderada (~47%), atinge um **Profit Factor de 1.97** e lucro acumulado de **+ R$ 7.882,79**, operando assimetrias favoráveis e realizando saídas parciais para proteger o saldo contra reversões bruscas.

---

## 2. Parâmetros Operacionais

### Entrada
- **Ativo Principal**: WINFUT (Mini-Índice B3).
- **Gatilho**: Rejeição de preço ou absorção de fluxo em níveis de suporte e resistência chave.
- **Direção**: Opera comprado (BUY) em testes de suporte e vendido (SELL) em exaustão de compras em topos.

### Saída
- **Take Profit**: Alvos escalonados de 100 a 250 pontos de mini-índice.
- **Stop Loss**: Stop técnico posicionado além da zona de suporte/resistência violada (80 a 150 pontos).
- **Encerramento Intraday**: Todas as posições são obrigatoriamente zeradas antes do fechamento do pregão da B3 (Day Trade estrito).

---

## 3. Métricas Estatísticas Validadas (510 Trades)
- **Total de Operações**: 510 trades (502 em WINFUT).
- **Taxa de Acerto (Win Rate)**: **46.86%** (239 vitórias / 90 derrotas / breakevens).
- **Profit Factor**: **1.97**.
- **Payoff Ratio**: 0.74 (compensado pelo volume de acertos vs perdas totais).
- **PnL Realizado Acumulado**: **+ R$ 7.882,79**.
- **Expectativa Matemática**: **+ R$ 15,46 por operação**.
