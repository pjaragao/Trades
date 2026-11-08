---
name: copiloto-risco
description: >-
  Tamanho da posição pelo RISCO e checagem pré-trade do Copiloto: quantidade = menor entre o valor por trade e o
  risco máximo ÷ perda por unidade até o stop (no lote, com custos), R:R conferido contra o acerto que ele exige
  (e contra o acerto histórico do analista), perda máxima do dia, entradas por dia, janela de horário, vencimento da
  opção, venda a descoberto, preço perseguido e trades semelhantes em carteira. Devolve APROVADO/BLOQUEADO com os
  motivos e a boleta. Use quando o usuário disser "quanto eu compro?", "isso passa no meu risco?", "dimensiona",
  "qual o tamanho da posição", "checa o risco", ou tiver entrada e stop e quiser a boleta.
argument-hint: "TICKER --entrada X --stop Y [--alvo Z] [--trader NOME]"
---

# copiloto-risco

trader-budget + trader-risk (day-trader-skill, MIT) adaptados ao Copiloto. Núcleo em `src/services/pretrade.py`.
O Copiloto já dimensionava por valor (`services/sizing.py`) e conferia capital/exposição (`execution/risk.py`);
o que faltava é usar o stop para limitar a perda por trade e travar o que foge da regra.

```bash
python .claude/skills/copiloto-risco/risco.py PETR4 --entrada 38.50 --stop 37.20 --alvo 41
python .claude/skills/copiloto-risco/risco.py SAUDK170 --entrada 0.90 --stop 0.47 --alvo 1.19 --trader Sanita
python .claude/skills/copiloto-risco/risco.py PETR4 --entrada 38.50 --stop-pct 3 --alvo-pct 6 --conta paper
```

Outras: `--lado venda`, `--vencimento`, `--risco-max R$`, `--perda-dia R$` (sobrescrevem só nesta execução),
`--limites ARQ`, `--db ARQ`, `--sem-api`, `--json`. Saída 0 = aprovado, 1 = bloqueado.

## Limites (`limites.json` desta pasta)

| chave | padrão | o quê |
| --- | --- | --- |
| `risco_max_trade` | 100 | R$ perdidos se o stop executar (1% de R$ 10 mil), custos de ida e volta incluídos |
| `perda_max_dia` | 300 | perda realizada hoje + risco deste trade não pode passar disso |
| `rr_min` | 1,0 | R:R mínimo quando o analista não tem histórico suficiente |
| `margem_acerto` | 5 | p.p. que o acerto do analista precisa ter acima do acerto de empate 1/(1+R) |
| `min_historico` | 20 | operações do analista para usar o acerto dele |
| `exige_stop` | true | sem stop, bloqueia |
| `entradas_max_dia` | 3 | compras registradas hoje |
| `sem_entrada_antes` / `sem_entrada_depois` | 10:15 / 16:30 | fora disso, aviso |
| `dias_min_vencimento` | 5 | opção vencendo antes disso, bloqueia |

Capital, valor por trade, lote e slippage máximo vêm das Configurações do app.

## O que bloqueia

Sem stop; stop ou alvo do lado errado; capital por trade não compra 1 lote; 1 lote já arrisca mais que
`risco_max_trade`; R:R abaixo do que o acerto do analista sustenta (ou de `rr_min`, sem histórico); perda do dia
estourando; entradas do dia esgotadas; opção perto do vencimento; venda a descoberto; preço já andou mais que o
slippage máximo das Configurações desde a entrada do analista.

Avisos: pregão fechado ou fora da janela, sem alvo, trade semelhante em carteira, capital livre/exposição, e
**carteira não conferida** quando o banco não tem execuções (esta máquina de desenvolvimento: rode no servidor ou com
`--db` apontando para uma cópia do `app.db`).

## Passos

1. Precisa de entrada e stop. Sem stop, use a skill copiloto-sinal (plano pelo histórico/ATR) ou pergunte.
2. Rode e repita APROVADO/BLOQUEADO com os motivos, a quantidade (e se o risco ou o valor limitou), a perda no stop,
   o R:R e o acerto de empate. Mostre a boleta só se aprovado.
3. Se a quantidade pelo risco ficou bem abaixo da pelo valor, diga: o stop é que manda no tamanho.

## Regras

- Nunca afrouxe um limite por conta própria nem sugira isso para o trade passar.
- R:R baixo não é defeito por si (quem acerta muito vive de R:R < 1); a conta é contra o acerto exigido.
- O stop é uma intenção, não garantia: gap executa pior. A perda mostrada é no preço do stop.
- Nada aqui envia ordem.
