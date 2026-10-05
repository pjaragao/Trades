# STRAT-YT-005: Rastreamento de Fluxo Institucional em Opções (Big Trades & Travas dos Gringos)

- **ID**: `STRAT-YT-005`
- **Nome**: Rastreamento de Fluxo Institucional / Posicionamento Anormal de Derivativos
- **Fonte**: YouTube (Jimmy Carvalho)
- **Vídeo de Origem**: [A APOSTA DE 5.2 MILHÕES DE CALLS DOS GRINGOS NO BRASIL](https://www.youtube.com/watch?v=UpqUy3xjp2Q)
- **Canal**: Jimmy Carvalho (`UCSD7SH09s-rmWrhPc-Lpc0w`)
- **Classe de Ativo**: Opções sobre Índices e Blue Chips (`BOVA11`, `PETR4`, `VALE3`)
- **Status**: Ativa / Catalogada

---

## 1. Tese Operacional & Vantagem Estatística (Edge)

Grandes fundos de investimento estrangeiros e *market makers* institucionais movimentam bilhões na B3 e não montam posições direcionais expressivas em ações à vista sem antes estruturar proteção ou alavancagem assimétrica através do mercado de derivativos.
- **Anomalia de Volume**: Quando o volume financeiro diário de negociação de uma série específica de Calls ou Puts ultrapassa em 5x a 10x o volume médio histórico (como a aposta de 5.2 milhões de contratos de Calls em BOVA11), isso indica um forte direcionamento institucional para o próximo vencimento.
- **Vantagem Informativa**: Seguir o rastro dos grandes blocos institucionais (com risco travado via spreads) permite antecipar ondas de liquidez antes que o mercado à vista conclua o movimento de alta.

---

## 2. Regras Operacionais

### A. Detecção do Sinal Institucional
1. Monitorar o ranking diário dos derivativos mais negociados na B3.
2. Identificar séries de Calls OTM com volume acima de R$ 10 milhões negociados em uma única sessão.
3. Checar a corretora / ponta compradora via dados de custódia (presença dominante de corretoras gringas: Morgan Stanley, JP Morgan, Goldman Sachs, UBS).

### B. Estruturação da Entrada para o Varejo
1. **Nunca comprar Calls a seco OTM**: O decaimento temporal (*theta*) destruirá o capital caso o movimento demore alguns dias.
2. **Replicar a tese via Trava de Alta (Bull Spread)**:
   - Compra Call no strike próximo ao ponto de entrada do institucional.
   - Vende Call superior para financiar o custo e neutralizar o decaimento temporal.
3. **Custo Máximo da Estrutura**: No máximo 25% a 30% da largura da trava (potencial de ganho de 2.5x a 3x o valor investido).

### C. Saída e Manejo
- **Take Profit**: 70% a 90% do valor máximo da trava.
- **Stop de Tempo**: Caso o ativo não desenvolva tração até 7 dias úteis antes do vencimento, desmontar antecipadamente.
