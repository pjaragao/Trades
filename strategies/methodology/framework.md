# Metodologia Quantitativa de Análise & Identificação de Padrões de Trade

Este documento estabelece a metodologia científica adotada pelo sistema para:
1. **Avaliar históricos de operações** provenientes de plataformas (TradingFloor) e estratégias de educadores/canais (YouTube).
2. **Descobrir padrões operacionais** (setups, regras implícitas, faixas de assertividade).
3. **Validar a robustez estatística** das estratégias via backtesting paramétrico.
4. **Construir filtros e gatilhos** para busca de novas oportunidades no mercado B3.

---

## 1. Métricas Estatísticas Centrais

Nenhuma estratégia é aprovada na Base de Conhecimento apenas por "promessas" de retorno. Cada estratégia passa pelo cálculo das seguintes métricas:

### 1.1 Taxa de Acerto (*Win Rate* - $P_w$)
$$P_w = \frac{N_{\text{trades vencedores}}}{N_{\text{total de trades}}} \times 100$$
- **Classificação**:
  - *Alta Frequência / Venda de Volatilidade*: Espera-se $P_w \ge 85\%$.
  - *Trend Following / Rompimento*: Aceita-se $P_w$ entre $35\%$ e $55\%$, desde que com alto Payoff.

### 1.2 Razão de Retorno/Risco (*Payoff Ratio* - $R$)
$$R = \frac{\overline{\text{Lucro Médio dos Trades Vencedores}}}{|\overline{\text{Prejuízo Médio dos Trades Perdedores}}|}$$

### 1.3 Esperança Matemática por Trade ($E$)
Determina se a estratégia possui vantagem estatística (*edge*) positiva a longo prazo:
$$E = (P_w \times \overline{W}) - (P_l \times |\overline{L}|)$$
Onde:
- $P_w$: Probabilidade de vitória.
- $\overline{W}$: Ganho médio nos acertos.
- $P_l = 1 - P_w$: Probabilidade de derrota.
- $|\overline{L}|$: Perda média nos erros.
- **Critério**: O $E$ deve ser estritamente superior a zero após custos de corretagem, emolumentos B3 e slippage.

### 1.4 Fator de Lucro (*Profit Factor* - $PF$)
$$PF = \frac{\sum \text{Lucros Brutos}}{\sum |\text{Prejuízos Brutos}|}$$
- $PF > 1.5$: Estratégia viável.
- $PF > 2.0$: Estratégia excelente.

### 1.5 Drawdown Máximo (*Max Drawdown* - $MDD$)
Queda percentual máxima do pico ao vale no gráfico de patrimônio acumulado:
$$MDD = \max_{t \in (0, T)} \left( \frac{Peak_t - Equity_t}{Peak_t} \right)$$
- No caso de venda de opções fora do dinheiro, o $MDD$ mede a perda em meses de choque de mercado (ex: Joesley Day, Covid-19).

---

## 2. Metodologia de Identificação de Padrões em Histórico

Ao processar históricos brutos de trades (como os 2.388 trades do TradingFloor):

```
                       [Histórico de Trades]
                                 │
     ┌───────────────────────────┼───────────────────────────┐
     ▼                           ▼                           ▼
[Classificação por Ativo]   [Perfil por Trader]     [Padrões Temporais]
- Futuros (WINFUT/WDOFUT)   - Win Rate individual   - Intraday vs Swing
- Opções B3 (Calls/Puts)    - Payoff individual     - Duração média
- Ações/FIIs/BDRs           - Consistência mensal   - Horários de pico
     │                           │                           │
     └───────────────────────────┼───────────────────────────┘
                                 ▼
                     [Clustering & Detecção]
                     - Padrão Scalp Curto
                     - Padrão Tendência com Trailing
                     - Padrão Venda OTM com Alta Probabilidade
                                 ▼
                   [Ficha de Estratégia (KB)]
```

### Critérios de Detecção de Padrões:
1. **Duração do Trade (Holding Time)**:
   - `< 15 min`: Scalping (foco em WINFUT, sensível a spread e execução ultrarrápida).
   - `15 min - Fim do Pregão`: Day Trade de tendência/reversão.
   - `> 1 dia`: Swing Trade ou estrutura mensal de Opções.
2. **Distribuição de Lucro/Pontos**:
   - Ganhos homogêneos e curtos (ex: +70 a +150 pontos em mini-índice) indicam saída em alvo fixo (Take Profit).
   - Cauda longa de perdas indica ausência ou flexibilização de Stop Loss manual.

---

## 3. Metodologia de Ingestão de Estratégias do YouTube

Para transformar vídeos e canais do YouTube em estratégias acionáveis:

1. **Rastreamento de Canal**:
   - Consulta a API/feed do canal com `yt-dlp`.
   - Filtra títulos e descrições com vocabulário de trading (`opções`, `venda de put`, `trava`, `swing trade`, `setup`, `backtest`).
2. **Extração da Transcrição**:
   - Coleta a transcrição temporal completa com `youtube-transcript-api`.
3. **Sintaxe Operacional**:
   - Mapeia: **Ativo** (ex: VALE3) $\to$ **Indicador/Gatilho** (ex: ATR-14) $\to$ **Strike/Delta** (ex: -1 ATR, Delta 0.07) $\to$ **Prazo** (Mensal) $\to$ **Manejo de Risco** (Garantia no CDI).
4. **Validação Cruzada**:
   - Criação imediata da Ficha Técnica na pasta `strategies/knowledge_base/youtube/<canal>/`.
   - Execução de backtest independente nos mesmos ativos usando dados históricos de mercado.

---

## 4. Metodologia de Screening para Novos Trades

A busca por novas operações consiste em:
1. Carregar os ativos permitidos (ex: ações mais líquidas da B3 com mercado ativo de opções: VALE3, PETR4, ITUB4, BBAS3, B3SA3).
2. Obter cotação em tempo real e série de preços diários recentes.
3. Calcular os indicadores da estratégia (ex: ATR 14 dias).
4. Determinar os parâmetros exatos do dia:
   $$\text{Strike Alvo} = \text{Preço Atual} - (1.0 \times \text{ATR}_{14})$$
5. Localizar o contrato de Opção (Put) mais próximo do strike e com o vencimento adequado, calculando o prêmio estimado e o retorno sobre o capital alocado no CDI.
