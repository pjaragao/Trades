---
name: copiloto-analista
description: >-
  Histórico real de um analista do TradingFloors numa classe de ativo: acerto, retorno médio e mediano, fator de
  lucro, ganho e perda medianos, dias carregados, se é copiável à mão, as últimas 10 operações, o t estatístico (edge
  ou sorte?) e um plano de stop/alvo/horizonte tirado de como ele costuma sair. Também ranqueia todos os analistas de
  uma classe. Use quando o usuário perguntar "a Sanita é boa mesmo?", "quem vale seguir em opções?", "qual o acerto
  do Ferri", "esse analista tem edge?", "ranking dos analistas", ou antes de seguir alguém novo.
argument-hint: "NOME [--classe OPCAO|ACAO|FUTURO...] | --ranking [--classe ...]"
---

# copiloto-analista

O "histórico" da Máquina do Tempo adaptado ao Copiloto: o original re-roda o setup nos pregões passados; aqui o
setup é "copiar este analista", e o passado são os sinais encerrados dele. Núcleo em `src/lab/analyst_history.py`
(reaproveita `services/performance.py`, o mesmo cálculo da tela de analistas).

```bash
python .claude/skills/copiloto-analista/analista.py Sanita --classe OPCAO
python .claude/skills/copiloto-analista/analista.py "Artur Horta" --classe ACAO --desde 2026-01-01
python .claude/skills/copiloto-analista/analista.py --ranking --classe OPCAO
python .claude/skills/copiloto-analista/analista.py --ranking --classe FUTURO --min 30
```

Fonte: banco do Copiloto (`COPILOTO_DB` ou `--db`); banco sem sinais encerrados → API do TradingFloors. A primeira
linha da saída diz qual foi usada.

## Como ler

- **Retorno** é % sobre a entrada, com o sinal do lado (venda ganha na queda). Em opção, % do prêmio.
- **t** = retorno médio ÷ erro padrão. Mesma régua da auditoria do robo_lab: t < 2 não é edge comprovado;
  menos de 20 operações não conclui nada.
- **Copiável à mão**: "não" quando ≥ 60% das operações abrem e fecham no mesmo dia (a cópia chega atrasada).
- **Plano a partir do histórico**: stop no 75º percentil das perdas (exige ≥ 5 perdas; com menos, o percentil não diz
  nada e a revisão usa o ATR), alvo no ganho mediano, horizonte na mediana de dias. O TradingFloors não publica stop:
  esse é o substituto mais próximo de "sair junto com o analista".

## Passos

1. Rode para o analista e a classe pedidos (ou `--ranking`).
2. Responda: amostra e período, acerto, retorno médio, fator de lucro, t com a leitura (edge / fraco / sem edge /
   amostra pequena), se é copiável e as últimas 10.
3. Acerto muito alto com poucas perdas grandes (ex.: 97% de acerto, perdas de −80%): diga que o resultado depende de
   segurar o perdedor até quase zerar, e que um stop curto mudaria a conta — rode a Máquina do Tempo para ver.

## Regras

- Os números são os que o TradingFloors publica (entrada e saída do analista), sem slippage de cópia nem custos.
  Para "e se eu tivesse copiado, com custos e meu capital", aponte o Lab do app (`src/lab/signal_backtest.py`).
- Não confunda acerto com edge: o que importa é acerto × ganho médio − erro × perda média, e o t.
- Amostra recente pequena não vira tendência. Últimas 10 é termômetro, não estatística.

## O que nunca faz

Não muda quem é seguido nas Configurações e não grava nada no banco.
