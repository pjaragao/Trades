# STRAT-YT-006: Metodologia de Auditoria & Backtesting de Estratégias de Opções

- **ID**: `STRAT-YT-006`
- **Nome**: Protocolo de Validação Quantitativa e Detecção de Riscos Ocultos em Opções
- **Fonte**: YouTube (Jimmy Carvalho)
- **Vídeo de Origem**: [MELHOR MANEIRA DE SABER SE UMA ESTRATÉGIA DE OPÇÕES FUNCIONA!](https://www.youtube.com/watch?v=0NciLs5l7jY)
- **Canal**: Jimmy Carvalho (`UCSD7SH09s-rmWrhPc-Lpc0w`)
- **Classe de Ativo**: Metodologia / Derivativos B3
- **Status**: Ativa / Catalogada

---

## 1. Tese & Fundamento Metodológico

Muitas estratégias no mercado prometem rentabilidades astronômicas (ex: "ganhe 2.000%", "99% de acerto sem risco") ocultando o verdadeiro perfil de risco de cauda (*tail risk* / Cisne Negro).
Para que uma estratégia seja considerada institucionalmente válida, ela deve ser submetida a um protocolo estrito de backtesting que considere:
1. **Distorção de Amostra Curta**: Testar em ciclos de pelo menos 10 a 15 anos para incluir crises sistêmicas (2008, 2015-2016, 2020).
2. **Custo de Fricção Real**: Considerar taxas B3, emolumentos de exercício, slippage de book e impostos.
3. **Mapeamento do Pior Caso (*Worst-Case Scenario*)**: Qual o prejuízo da carteira no pior mês da história do ativo?

---

## 2. As 4 Etapas do Protocolo de Validação

### Etapa 1: Verificação da Assimetria
- Taxas de acerto elevadas (> 90%) são matematicamente obtidas vendendo seguros baratos (Puts ou Calls muito fora do dinheiro).
- A auditoria exige calcular se os 90% de pequenos ganhos compensam os 10% de perdas acentuadas.
- **Fórmula**: $\text{Expectância} = (P_w \times \overline{W}) - (P_l \times |\overline{L}|) > 0$.

### Etapa 2: Simulação de Black Swans (Stress Test)
- Simular o comportamento da estrutura em dias de circuit breaker (queda de 10% a 20% no pregão).
- Em estratégias de Venda de Put, verificar se o capital mantido no CDI é suficiente para honrar 100% da liquidação física das ações sem levar a conta a saldo devedor.

### Etapa 3: Sensibilidade ao Delta e Volatilidade Implícita (Vega)
- Identificar se a estratégia depende de volatilidade implícita (IV) alta para dar lucro ou se é resiliente em ambientes de IV comprimida (como 20% a 25%).

### Etapa 4: Comparativo Obrigatório com o CDI e Buy & Hold
- Toda estratégia brasileira deve obrigatoriamente superar o CDI líquido no longo prazo com drawdown controlado. Se render menos que o CDI ou empatar com volatilidade elevada, a estratégia é reprovada.
