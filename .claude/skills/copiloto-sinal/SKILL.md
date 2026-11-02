---
name: copiloto-sinal
description: >-
  Revisão completa de um sinal do TradingFloors antes de copiar: histórico real do analista, plano de stop e alvo
  (o TradingFloors não publica stop), Máquina do Tempo (10.000 replays Monte Carlo), quantidade pelo risco,
  APROVADO/BLOQUEADO com os motivos e a boleta pronta para o Home Broker. Use quando o usuário disser "vale copiar
  esse sinal?", "revisa o sinal", "analisa o trade da Sanita/do Ferri", "checa esse sinal", "quais sinais estão
  abertos", "quanto eu compro disso", ou mandar um ticker de opção/ação com entrada para avaliar. Nunca envia ordem.
argument-hint: "[--abertos | --id ID | TICKER --entrada X --trader NOME]"
---

# copiloto-sinal

O fluxo do day-trader-skill (exit → timemachine → budget → risk → broker) adaptado ao Copiloto de Trades. O sinal
vem do TradingFloors **sem stop e sem alvo** (os campos `stop_loss`/`take_profit` chegam sempre vazios na API), então
o plano sai, nesta ordem: do que o usuário informar → do histórico do próprio analista → do ATR do ativo. A ordem
quem envia é o usuário, no Home Broker ou na tela do Copiloto (que tem a própria confirmação).

Rode a partir da raiz do repositório (no Linux/WSL, `python3`):

```bash
python .claude/skills/copiloto-sinal/sinal.py --abertos                     # sinais abertos dos analistas seguidos
python .claude/skills/copiloto-sinal/sinal.py --abertos --todos             # inclui quem não é seguido
python .claude/skills/copiloto-sinal/sinal.py --id e4891f70                 # revisão de um sinal (id ou prefixo)
python .claude/skills/copiloto-sinal/sinal.py --id e4891f70 --entrada 0.85 --stop 0.55
python .claude/skills/copiloto-sinal/sinal.py PETR4 --entrada 38.50 --trader "Artur Horta"
python .claude/skills/copiloto-sinal/sinal.py VALE3 --entrada 60 --modo intraday --hora 11:00
```

Outras opções: `--alvo`, `--stop-pct`, `--alvo-pct`, `--strike`, `--vencimento`, `--subjacente`, `--dias`,
`--replays`, `--seed` (padrão 19), `--sem-simulacao`, `--conta paper`, `--limites ARQ`, `--db ARQ`, `--sem-api`,
`--json`. Código de saída: 0 aprovado, 1 bloqueado, 2 sinal não encontrado.

## De onde vêm os dados

| o quê | fonte |
| --- | --- |
| sinais e histórico dos analistas | banco do Copiloto (`COPILOTO_DB` ou `--db`); banco sem sinais → API do TradingFloors (login em `config/.env`) |
| barras do ativo | Yahoo Finance (gratuito, não oficial, ~15 min de atraso): 2 anos diários ou 60 dias de 5 min |
| carteira, perda do dia, entradas de hoje | execuções do banco do Copiloto. Banco sem execuções (ex.: esta máquina de desenvolvimento) → a checagem avisa que **não conferiu** |
| limites de risco | `.claude/skills/copiloto-risco/limites.json` |
| capital, valor por trade, lote, slippage máximo | Configurações do app (tabela `settings`) |

## Passos

1. Sem sinal definido, rode `--abertos` e mostre a lista curta (id, data, analista, ticker, entrada x atual).
2. Rode a revisão do sinal escolhido. Se o usuário já tem o próprio stop/alvo/entrada, passe-os.
3. Responda nesta ordem:
   - **APROVADO ou BLOQUEADO** e cada motivo, como impresso (✖ bloqueia, ! aviso, · informação);
   - **Máquina do Tempo**: as quatro chances, a faixa de 90% do preço no fim, o R médio, as linhas de veredito
     **exatamente como impressas**, e a semente;
   - **analista**: acerto, retorno médio, t e se é copiável à mão;
   - **boleta**, se aprovada, em bloco de texto para copiar.
4. Se o preço já andou além do slippage máximo desde a entrada do analista, diga com todas as letras que copiar
   agora é outro trade (o R:R do analista já foi consumido em parte).
5. Diga uma vez que simulação e histórico não são previsão, e que nada foi enviado.

## Regras

- Nunca arredonde um "perto do empate" para edge. Repita o veredito, não reescreva.
- Nunca sugira afrouxar um limite para o trade passar. Mudar `limites.json` ou as Configurações é decisão do
  usuário, pedida por ele.
- Opção: a simulação é do ativo-objeto com Black-Scholes e vol implícita constante (sem sorriso, sem choque de vol).
  Diga isso quando a decisão depender de poucos centavos de prêmio.
- O acerto histórico do analista é com as saídas DELE, não com o stop/alvo do plano. A Máquina do Tempo é que testa o
  plano.
- Analista com "copiável: não" (opera no mesmo dia): a cópia manual chega atrasada. Mencione.
- Futuros (WIN/WDO): o Yahoo não tem barra confiável. Só com `--csv` exportado do MT5 (ver skill
  copiloto-maquina-do-tempo). Nunca use dados sintéticos (lição da auditoria do robo_lab).

## O que nunca faz

Não envia, não agenda e não arma ordem. Não altera o banco, as Configurações nem os limites. Não liga
`EXECUTION_ENABLED`.
