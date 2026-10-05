# Copiloto de Trades

App pessoal para seguir os sinais dos analistas do **TradingFloors** operando **manualmente no Home Broker**.
Ele avisa quando um analista abre ou encerra uma operação, entrega a boleta pronta, registra o que você
executou de fato e mostra se você está ganhando dinheiro de verdade (com custos, slippage e IR).

> A execução automática no MetaTrader 5 está **desligada** (`execution.enabled: false`). Ela volta na Fase 6.

## Como usar

```bash
pip install -r requirements.txt
```

1. Copie `config/.env.example` para `config/.env` e preencha `TF_EMAIL` e `TF_PASSWORD`.
2. Rode `start_web.bat` (ou `python web_app.py`) e abra http://127.0.0.1:5000.
3. Na primeira vez o app baixa todo o histórico do TradingFloors (alguns segundos).
4. Em **Configurações**: capital, valor por trade, analistas seguidos, custos e alertas.
   Clique em "Permitir notificações" para receber avisos do navegador.

Para consultar pelo celular na mesma rede: `python web_app.py --host 0.0.0.0` e acesse `http://<ip-do-pc>:5000`.

### O fluxo

| Etapa | Onde |
|---|---|
| Analista abre sinal → alerta (navegador, som, Telegram opcional) | monitor de sinais (sempre ativo) |
| Boleta pronta: quantidade, preço limite, máximo aceitável, custo, perda máxima, avisos | **Hoje** |
| Copiar boleta → executar no Home Broker → **Executei** (formulário pré-preenchido) | **Hoje** / **Sinais** |
| Acompanhar posição: meu preço médio, P&L, retorno do sinal, vencimento | **Carteira** |
| Analista encerra → **Saída pendente** com boleta de saída | **Hoje** / **Carteira** |
| Registrar saída → resultado real, slippage vs. analista, IR/DARF, CSV | **Resultados** |
| Quem vale a pena seguir? Backtest de cópia, screeners, IA, base de conhecimento | **Laboratório** |

### Telas

- **Hoje** — só o que exige decisão agora: novos sinais (com boleta), saídas pendentes, lembretes, posições e resumo.
- **Sinais** — todos os sinais (abertos/encerrados), filtros, sua decisão em cada um e selo *Copiável*
  (o analista costuma carregar a posição de um pregão para outro).
- **Carteira** — suas posições derivadas das execuções; cotação do TradingFloors ou manual.
- **Resultados** — curva de patrimônio real, desempenho por analista, slippage, custos, IR mensal (estimativa) e exportação CSV.
- **Laboratório** — perfil dos analistas, backtest "e se eu tivesse copiado?", screeners (estimativas, CDI do BCB),
  previsão TimesFM (opcional) e base de conhecimento.
- **Configurações** — preferências e status do sistema.

Tudo que é estimado/simulado leva o selo **Estimativa**; o status do monitor mostra quando os dados estão desatualizados.

## Estrutura

```
web_app.py                 # servidor local (python web_app.py [--port --host --db --no-monitor])
config/settings.yaml       # infraestrutura (API TF, intervalo do monitor, flags de execução)
config/.env                # credenciais (não versionado)
database/app.db            # banco único do Copiloto (não versionado)
src/
  core/                    # config, banco + migrações, calendário B3, tickers/opções
  integrations/            # cliente TradingFloors (token em cache) + deduplicação única
  services/                # monitor de sinais, boleta, diário/posições, carteira, alertas, IR, resultados
  lab/                     # backtest de cópia, taxas BCB, TimesFM sob demanda
  execution/               # MT5 (Fase 6) e o robô antigo em execution/legacy
strategies/                # screeners, backtest de opções, base de conhecimento, ingestão YouTube
web/
  app.py, api/             # Flask + blueprints da API
  templates/app.html       # shell da interface
  static/css, static/js    # design system e módulos ES (sem build)
tests/                     # pytest
```

### Dados

- `signals`: sinais do TradingFloors. A tabela `trades` da API é a fonte canônica; `opcoes_trades`
  só enriquece (preço atual, strike). A deduplicação fica em `src/integrations/tradingfloors.py`.
- `executions`: o que você executou. Posições e P&L são sempre recalculados a partir daqui
  (preço médio com custos; day trade separado de swing por dia, como na apuração de IR).
- `decisions`, `alerts`, `quotes`, `settings`, `kv`.

O histórico antigo (`database/backtest_cache.db`) é importado uma vez, só com as operações que a API não devolve mais.

## Testes

```bash
python -m pytest
```

## Opcionais

- `pip install -r requirements-lab.txt` — previsão com Google TimesFM e importação de vídeos do YouTube.
- Telegram: preencha `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` em `config/.env` e ligue em Configurações.
- Robô antigo (só simulação): `python -m src.execution.legacy.main --dry-run`.
