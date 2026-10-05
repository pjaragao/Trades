# STRAT-YT-002: Trava de Alta com Call (Bull Call Spread - Multiplicação de Capital 2x a 3x)

- **ID**: `STRAT-YT-002`
- **Nome**: Trava de Alta com Call Direcional (Bull Call Spread)
- **Fonte**: YouTube (Jimmy Carvalho)
- **Vídeo de Origem**: [HOW TO 3X YOUR MONEY IN THE STOCK MARKET (STRATEGY: BULL SPREAD)](https://www.youtube.com/watch?v=TeKdmKI7EYE)
- **Canal**: Jimmy Carvalho (`UCSD7SH09s-rmWrhPc-Lpc0w`)
- **Classe de Ativo**: Opções de Compra B3 (Calls)
- **Ativos Prioritários**: `VALE3`, `PETR4`, `BBAS3`, `BOVA11`
- **Status**: Ativa / Catalogada

---

## 1. Tese Operacional & Vantagem Estatística (Edge)

A Trava de Alta com Call (Bull Spread) é uma estrutura direcional montada a débito com risco 100% delimitado e conhecida assimetria matemática positiva.
- **Risco Delimitado**: O investidor nunca perde mais do que o valor líquido desembolsado para montar a operação.
- **Assimetria de Retorno**: Projeta multiplicação de **2x a 3x o capital investido** (lucro líquido de 100% a 200%) com movimentos moderados de alta do ativo subjacente (2% a 6% de valorização da ação até o vencimento).
- **Proteção contra o Tempo**: A venda da Call superior reduz drasticamente o custo de entrada e o decaimento temporal negativo (*theta decay*) da posição comprada.

---

## 2. Regras Operacionais Precisas

### A. Seleção de Ativos e Gráfico
1. Ação em tendência de alta no gráfico diário ou em ponto de suporte/pivô técnico relevante.
2. Papéis com alta liquidez de derivativos na B3 para evitar spread excessivo de book.

### B. Montagem da Operação (Ciclo Mensal de 20 a 30 dias úteis)
1. **Ponta Comprada (Long Call)**:
   - Compra Call no dinheiro (ATM) ou ligeiramente fora do dinheiro (Delta ~0.50 a 0.55).
2. **Ponta Vendida (Short Call)**:
   - Vende Call fora do dinheiro (OTM) no nível de resistência gráfica projetada ou 1 a 2 strikes acima (Delta ~0.25 a 0.30).
3. **Largura dos Strikes vs Custo**:
   - A largura entre os strikes (diferença de R$ no alvo) deve ser no mínimo **3x a 4x o débito líquido pago**.
   - *Exemplo*: Trava de R$ 2,00 de largura custando R$ 0,60 de débito.
     - Risco Máximo: R$ 0,60 por contrato.
     - Ganho Máximo: $\text{Largura} - \text{Débito} = \text{R\$} 2,00 - \text{R\$} 0,60 = \text{R\$} 1,40$.
     - Retorno sobre o capital arriscado: $\frac{1,40}{0,60} \approx 233\%$ de lucro líquido (3.33x o capital).

### C. Regras de Saída
- **Take Profit Total**: No atingimento do lucro máximo (preço da ação ultrapassou o strike vendido) ou faltando 5 dias para o vencimento com mais de 80% do lucro máximo capturado.
- **Stop Loss Técnico**: Se a ação romper o suporte chave no gráfico diário, desmontar a trava a mercado para resgatar o valor residual (resgate típico de 30% a 50% do débito pago).
- **Vencimento**: Se o ativo fechar abaixo do strike comprado, a trava expira sem valor com perda estritamente limitada ao débito inicial.

---

## 3. Gestão de Risco e Dimensionamento
- **Alocação por Operação**: Nunca alocar mais do que 1% a 2% do patrimônio líquido total por trava de alta.
- **Perfil**: Estratégia de assimetria positiva (Payoff > 2.0). Mesmo com Win Rate na faixa de 45% a 55%, a expectativa matemática é fortemente lucrativa.
