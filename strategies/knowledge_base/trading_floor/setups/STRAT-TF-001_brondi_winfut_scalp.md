# STRAT-TF-001: Scalping Direcional de Alta Frequência em Mini-Índice (WINFUT)

- **ID**: `STRAT-TF-001`
- **Fonte**: TradingFloor (Trader Brondi)
- **Classe de Ativo**: Futuros B3 (WINFUT)
- **Status**: Ativo
- **Estilo**: Scalping Intraday

---

## 1. Tese Operacional & Vantagem Estatística (Edge)
O trader Brondi realiza operações de curtíssima duração (scalp) no mini-índice futuro, aproveitando micro-movimentos de liquidez e impulsões de fluxo no livro de ofertas.
A vantagem estatística decorre do número elevado de operações com alvo curto pré-definido (50 a 150 pontos), controlando a perda máxima por operação.

---

## 2. Parâmetros e Regras de Operação

### Entrada
- **Ativo**: WINFUT (contrato vigente do mini-índice B3).
- **Gatilho**: Rompimento de micro-consolidação intraday ou teste de médias móveis exponenciais rápidas (9 e 21 períodos no gráfico de 1 a 5 minutos).
- **Lado**: Ambidestro (opera tanto na ponta compradora BUY quanto vendedora SELL).

### Saída
- **Take Profit (TP)**: 80 a 150 pontos do mini-índice.
- **Stop Loss (SL)**: 60 a 100 pontos técnicos.
- **Stop de Tempo**: Caso a operação não atinja o alvo em até 10 minutos, encerrar a mercado.

### Gestão de Risco
- **Tamanho de Posição**: Alocação de risco controlada por contrato, limite de perda diária (*Daily Loss Limit*).
- **Execução**: Mercado imediato ou limite agressivo na ponta oposta do book.

---

## 3. Estatísticas Históricas Validadas (677 Trades)
- **Total de Operações**: 677
- **Taxa de Acerto (Win Rate)**: 33.7% (com lucro acumulado positivo devido a assimetria e gestão de lote)
- **Payoff Ratio**: 1.13
- **Profit Factor**: 1.35
- **PnL Realizado Acumulado**: + R$ 4.143,96
- **Expectativa Matemática**: + R$ 6,12 por contrato/trade
