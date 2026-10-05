# STRAT-TF-005: Swing Trade em Ações & Opções de Small Caps (Trader Artur Horta)

- **ID**: `STRAT-TF-005`
- **Fonte**: TradingFloor (Trader Artur Horta)
- **Classe de Ativo**: Ações B3 & Opções
- **Status**: Ativo / Validado
- **Estilo**: Swing Trade Híbrido

---

## 1. Tese Operacional & Vantagem Estatística (Edge)
Artur Horta combina análise gráfica clássica e fundamentalista para selecionar ações e opções com assimetria de valor, incluindo empresas de média e baixa capitalização (Small Caps e Mid Caps como `VAMO3`, `COGN3`, `NATU3`, `CAML3`, `MDNE3`).
- **O Edge**: Identificação de reversões de fundo ou rompimento de canais em ativos que o mercado precificou com desconto excessivo, usando opções para alavancar a assimetria sem risco de chamada de margem.

---

## 2. Parâmetros Operacionais

### Entrada
- **Ativos**: Ações à vista e séries de opções de ações da B3.
- **Gatilho**: Cruzamento de médias de curto prazo associado a divergências de alta no IFR (RSI) no gráfico diário.
- **Dimensionamento**: Posições calculadas para risco de 1% a 2% da carteira por recomendação.

### Saída
- **Take Profit**: Alvos de 8% a 20% na ação à vista, ou 80% a 150% na série de opções.
- **Stop Loss**: Mínima do fundo anterior no gráfico diário.
- **Duração**: De 5 a 20 dias úteis.

---

## 3. Métricas Estatísticas Validadas (92 Trades)
- **Total de Operações**: 92 trades (85 encerrados, 7 em aberto).
- **Taxa de Acerto (Win Rate)**: **57.6%** (49 vitórias / 36 derrotas).
- **PnL Realizado Acumulado**: **+ R$ 7.694,26**.
- **Expectativa Matemática**: **+ R$ 90,52 por trade**.
