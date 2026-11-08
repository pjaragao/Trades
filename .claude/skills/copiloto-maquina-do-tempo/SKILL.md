---
name: copiloto-maquina-do-tempo
description: >-
  Máquina do Tempo para a B3: replays Monte Carlo de um trade (entrada, stop, alvo) a partir das próprias barras do
  ativo — 10.000 réplicas dos próximos pregões (swing, barras diárias) ou do resto do pregão (intraday, barras de
  5 min) — e devolve a chance de bater o alvo primeiro, o stop primeiro ou nenhum, o preço no fim, o R médio e um
  veredito honesto. Funciona com ações e opções (reprecifica o prêmio por Black-Scholes). Use quando o usuário disser
  "roda a máquina do tempo", "simula esse trade", "quais as chances", "monte carlo", "isso é cara ou coroa?",
  "quantas vezes bate o alvo", ou antes de dimensionar uma entrada.
argument-hint: "TICKER --entrada X [--stop Y --alvo Z] [--modo swing|intraday]"
---

# copiloto-maquina-do-tempo

Adaptação do trader-timemachine (github.com/Jakeschincariol/day-trader-skill, MIT) para a B3. O núcleo está em
`src/lab/timemachine.py` (testado em `tests/test_copiloto_skills.py`); este é o atalho de linha de comando.

```bash
python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETR4 --entrada 38.50                       # stop 1,5×ATR, alvo 2R
python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETR4 --entrada 38.50 --stop 37.20 --alvo 41
python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETR4 --lado venda --entrada 38.5 --modo intraday --hora 11:30
python .claude/skills/copiloto-maquina-do-tempo/maquina.py SAUDK170 --entrada 0.90 --strike 16.93 --alvo-pct 32.5 --dias 4
python .claude/skills/copiloto-maquina-do-tempo/maquina.py WINZ26 --entrada 131000 --stop 130500 --alvo 132000 \
    --csv win_5m.csv --modo intraday --hora 10:30
```

Plano: `--stop`/`--alvo` > `--stop-pct`/`--alvo-pct` > `--stop-atr K` (padrão 1,5 no swing, 0,5 no intraday) com
alvo em `--alvo-r` (padrão 2). Outras: `--dias` (padrão 10), `--ate HH:MM` (zerar até; padrão 10 min antes do
fechamento), `--data AAAA-MM-DD`, `--replays`, `--seed` (padrão 19), `--vencimento`, `--tipo call|put`,
`--subjacente`, `--selic`, `--json`.

## Como funciona

1. **Pool.** Swing: as razões abertura/máxima/mínima/fechamento ÷ fechamento anterior dos últimos ~500 pregões
   (ajustados por proventos). Intraday: as mesmas razões por barra de 5 min, agrupadas pelo horário, dos pregões
   anteriores com ≥ 80% das barras; barra que o Yahoo omite (sem negócio) vira barra parada. Só pregões ANTES da
   data do plano entram — nada do dia em andamento.
2. **Uma réplica.** Swing: sorteia blocos de 5 pregões seguidos (mantém a volatilidade agrupada). Intraday: cada
   barra é sorteada entre as do mesmo horário ±2 barras. Barra a barra: gap além do stop/alvo executa na abertura;
   barra que toca os dois conta como stop.
3. **Opção.** Simula o ativo-objeto e reprecifica o prêmio por Black-Scholes, com vol implícita tirada do prêmio de
   entrada e Selic do Banco Central; horizonte cortado no vencimento. Mostra a que preço do ativo-objeto o stop e
   o alvo do prêmio correspondem hoje.
4. **Veredito.** Entre as réplicas que tocaram um lado, o alvo precisa vir primeiro em 1/(1+R) para empatar (50% a
   1R, 33% a 2R). Menos de 5 p.p. de diferença: "perto de cara ou coroa"/"perto do empate"; 5–15: "pende";
   15+: "fortemente". Abaixo, quando cabe: aviso se > 40% não tocaram nenhum lado, e se o R médio vai contra.

## Passos

1. Confirme ticker, lado, entrada e o plano. Sem stop/alvo, diga de onde o plano veio (ATR ou %).
2. Rode. Swing para sinais que o analista carrega por dias; intraday só com `--hora` e para o resto do pregão.
3. Responda nesta ordem: as quatro chances, mediana e faixa de 90% do preço no fim, R médio, as linhas de veredito
   **como impressas**, e a semente. Em opção, a vol implícita e o equivalente do stop/alvo no ativo-objeto.
4. Diga uma vez: é simulação a partir do passado recente do ativo, não previsão — balanço, notícia, leilão e choque
   de vol fazem o que esses dias não fizeram.

## Regras

- Todo número sai da execução. Nunca transforme "perto do empate" em edge, nem julgue um plano de 2R só por alvo x stop.
- Sempre diga a semente (mesma entrada + mesmos dados + mesma semente = mesmos números).
- Yahoo é gratuito e não oficial: atrasa ~15 min e pode falhar. Barras de 5 min, nunca tick a tick.
- Futuros, índice e dólar: o Yahoo não serve (só tem o diário do índice/BRL=X). Exija `--csv` com barras reais
  exportadas do MT5 (colunas data/hora, open, high, low, close; o formato `<DATE> <TIME>` do MT5 é aceito). Nunca
  fabrique barras intraday a partir de diárias — foi o erro que invalidou os relatórios antigos do robo_lab.
- Um plano por execução. Mudou entrada, stop, alvo ou data: nova execução.

## O que nunca faz

Não dimensiona, não envia ordem, não muda o plano por conta própria e não chama nada de certeza.
