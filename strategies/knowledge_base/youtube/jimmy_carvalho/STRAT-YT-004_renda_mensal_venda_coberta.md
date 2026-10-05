# STRAT-YT-004: Renda Mensal com Opções (Venda Coberta & Dividendos Sintéticos)

- **ID**: `STRAT-YT-004`
- **Nome**: Geração de Renda Mensal Recorrente com Venda de Opções (Covered Call & Cash-Secured Put)
- **Fonte**: YouTube (Jimmy Carvalho)
- **Vídeo de Origem**: [Renda Mensal Com OPÇÕES de forma Rápida Guia Completo para Iniciantes](https://www.youtube.com/watch?v=ohVQe64IZak)
- **Canal**: Jimmy Carvalho (`UCSD7SH09s-rmWrhPc-Lpc0w`)
- **Classe de Ativo**: Opções B3 (Calls e Puts)
- **Ativos Prioritários**: `PETR4`, `VALE3`, `BBAS3`, `ITUB4`, `B3SA3`
- **Status**: Ativa / Catalogada

---

## 1. Tese Operacional & Vantagem Estatística (Edge)

A geração de renda mensal recorrente é a porta de entrada mais segura para o investidor de derivativos.
- **Venda de Put**: Usada para comprar ações sólidas com desconto em relação ao preço atual, sendo remunerado antecipadamente mesmo se a ação não cair até o strike.
- **Venda Coberta de Call (Covered Call)**: Uma vez posicionado nas ações em carteira, realiza-se a venda mensal de Calls fora do dinheiro (OTM) para coletar dividendos sintéticos regulares de 1.5% a 3.0% ao mês.
- **O Edge do Theta (Tempo)**: Toda opção perde valor intrínseco diariamente à medida que o vencimento se aproxima. O investidor vendedor atua como uma "seguradora", embolsando esse decaimento temporal sistematicamente.

---

## 2. Regras Operacionais Passo a Passo

### Fase 1: Entrada com Venda de Put (Cash-Secured Put)
1. Escolher uma ação que você aceitaria carregar na carteira de longo prazo (ex: BBAS3 ou PETR4).
2. Deixar 100% do valor de compra em Renda Fixa / Tesouro Selic (gerando CDI).
3. Vender Put com strike entre 3% e 7% abaixo do preço atual (Delta entre -0.15 e -0.25).
4. Coletar o prêmio na abertura (tipicamente 1.0% a 2.0% do valor da ação).
   - Se a ação ficar acima do strike: a opção expira, o prêmio fica integralmente na conta e o ciclo se repete.
   - Se for exercido: adquire a ação com preço médio bem abaixo do preço inicial (Strike menos Prêmio recebido).

### Fase 2: Venda Coberta de Call (Covered Call / Dividendos Sintéticos)
1. Com as ações em custódia, escolher um strike de Call de 4% a 8% acima do preço de compra (Delta entre 0.20 e 0.30).
2. Vender 1 contrato de Call para cada 100 ações em custódia (100% coberto).
3. Coletar o prêmio mensal imediato (1.5% a 2.5% ao mês).
   - Se a ação subir moderadamente ou cair: o prêmio é lucro líquido, aumentando a rentabilidade da carteira.
   - Se a ação disparar acima do strike: as ações são vendidas no strike, capturando o lucro da valorização da ação + o prêmio integral da Call.

---

## 3. Gestão de Risco e Parâmetros Práticos
- **Proibição Absoluta**: Nunca vender Call sem possuir as ações em custódia (venda a descoberto de Call possui risco ilimitado).
- **Rolagem Preventiva**: Caso a ação caia expressivamente, não realizar venda de Call abaixo do preço médio de compra das ações, para evitar assumir prejuízo patrimonial compulsório.
- **Rentabilidade Alvo**: 18% a 30% ao ano sobre o patrimônio total (superando amplamente o CDI e o Ibovespa).
