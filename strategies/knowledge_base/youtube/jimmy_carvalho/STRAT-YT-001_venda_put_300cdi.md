# STRAT-YT-001: Venda de Put OTM no Nível -1 ATR (Renda 300% do CDI)

- **ID**: `STRAT-YT-001`
- **Nome**: Venda de Put Fora do Dinheiro com -1 ATR em Ações Líquidas
- **Fonte**: YouTube (Jimmy Carvalho)
- **Vídeo de Origem**: [DESCOBRI UMA ESTRATÉGIA QUE RENDE 300% O CDI](https://www.youtube.com/watch?v=L48NBs21q6g)
- **Canal**: Jimmy Carvalho (`UCSD7SH09s-rmWrhPc-Lpc0w`)
- **Classe de Ativo**: Opções sobre Ações B3 (Puts)
- **Ativos Prioritários**: `VALE3`, `PETR4`, `ITUB4`
- **Status**: Ativa / Validada

---

## 1. Tese Operacional & Vantagem Estatística (Edge)

A estratégia combina a **segurança da Renda Fixa pós-fixada** com a **remuneração periódica por venda de volatilidade implícita** em opções de venda (Puts).
- **Renda Fixa de Base**: 100% do capital financeiro permanece aplicado em títulos públicos (Tesouro Selic) ou ETFs de renda fixa (ex: LFTS11 / LFTB11), rendendo **100% do CDI** com risco soberano.
- **Remuneração Adicional com Opções**: Esse capital em renda fixa serve como margem de garantia integral na B3 para venda coberta de Puts com probabilidade de ganho de **95% a 99%**.
- **O Edge Matemático**: O strike da Put é posicionado abaixo do preço atual com margem de segurança baseada no indicador **ATR (Average True Range)** de 14 períodos diários. A grande maioria das opções vira pó, permitindo embolsar o prêmio integralmente mês após mês.

---

## 2. Regras Operacionais Precisas

### A. Alocação de Capital e Garantia
1. 100% do valor nominal da operação deve estar alocado em ativo garantidor aceito pela B3 (Tesouro Selic ou ETF de CDI).
2. Não operar alavancado: se possui R$ 100.000, venda Puts cujo valor de strike somado totalize no máximo R$ 100.000 de obrigação financeira (ex: 2.000 Puts com strike R$ 50,00 = R$ 100.000).

### B. Regra de Entrada (Abertura da Posição)
1. **Momento da Montagem**: Na segunda-feira seguinte ao vencimento mensal das opções da B3 (ciclo de aproximadamente 20 a 25 pregões até o próximo vencimento).
2. **Cálculo do Nível de Entrada**:
   - No gráfico diário do ativo base (ex: VALE3), calcular o $\text{ATR}(14)$.
   - Strike Alvo:
     $$\text{Strike}_{\text{Put}} \le \text{Preço de Fechamento} - (1.0 \times \text{ATR}_{14})$$
3. **Filtro de Delta OTM Alternativo**:
   - Caso prefira selecionar via Delta na grade de opções, escolher a Put com **Delta entre -0.04 e -0.12** (alvo ideal: **Delta ~ -0.07**, equivalente a aproximadamente 93% a 96% de probabilidade de expirar fora do dinheiro).
4. **Execução**: Ordem de venda a mercado ou a limite no melhor preço de compra do livro.

### C. Regra de Saída (No Vencimento)
- **Cenário 1: Opção Expira OTM (Preço da Ação > Strike) - Frequência de 95% a 99%**:
  - A opção vira pó. O prêmio recebido na abertura é 100% lucro líquido.
  - O capital de garantia rendeu 100% do CDI no mês.
  - O resultado total do mês é: $\text{CDI} + \text{Prêmio das Opções}$ (gerando de 200% a 400% do CDI).
- **Cenário 2: Exercício (Preço da Ação < Strike) - Frequência de 1% a 5%**:
  - O investidor compra a ação pelo valor do Strike acordado (que já tinha um desconto de 1 ATR em relação ao preço inicial).
  - Vende a ação no mercado para zerar e assumir a perda pontual, OU mantém a posição e inicia lançamento coberto de Call (Wheel Strategy) para recuperar a diferença.

---

## 3. Desempenho Histórico Validado

| Métrica | Mercado Americano (S&P 500) | Brasil - B3 (VALE3) | Brasil - B3 (PETR4) |
| :--- | :---: | :---: | :---: |
| **Período Testado** | 36 anos (1990 - 2026) | 17.5 anos (2009 - 2026) | 17.5 anos (2009 - 2026) |
| **Total de Pregões / Meses** | 9.223 pregões (1.898 trades) | 210 meses | 210 meses |
| **Taxa de Acerto (Win Rate)** | **95.1%** | **99.0%** (2 meses negativos) | **96.5%** |
| **Multiplicação de Capital** | Superior ao Buy & Hold | **20.8x o capital inicial** | **11.0x o capital inicial** |
| **Comparativo vs CDI** | 3x a 4x S&P 500 | **4.2x o CDI** (CDI rendeu 4.9x) | **2.2x o CDI** |
| **Retorno Médio Composto** | ~18% a.a. | ~21.5% a.a. | ~17.2% a.a. |
| **Pior Drawdown Mensal** | -7.5% | -18.2% (queda atípica) | -31.4% (choque petróleo) |

---

## 4. Matriz de Gestão de Risco & Alertas

> [!TIP]
> **Recomendação**: Sempre operar o parâmetro mais conservador (-1 ATR ou Delta ~0.07). Configurações mais agressivas aumentam a taxa anual para ~31%, mas elevam o índice de erro para 1 a cada 4 meses.

> [!WARNING]
> **Risco de Cauda (Black Swan)**: Em meses de quedas extremas (como desastres pontuais ou pandemias), o ativo pode abrir com gap abaixo do strike. A garantia em CDI deve ser estritamente mantida para honrar a liquidação sem alavancagem ou chamada de margem compulsória.
