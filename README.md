# Copiloto de Trades

App pessoal para seguir os sinais dos analistas do **TradingFloors**. Ele avisa quando um analista abre ou encerra
uma operação, entrega a boleta pronta, registra o que você executou (no Home Broker ou via MetaTrader 5),
importa as notas de corretagem e mostra se você está ganhando dinheiro de verdade (com custos reais, slippage e IR).

## Rodando

### Docker (homelab)

```bash
cp .env.example .env        # preencha COPILOTO_PASSWORD, TF_EMAIL, TF_PASSWORD
docker compose up -d --build
```

Acesse `http://<ip-do-homelab>:5000`. Os dados ficam em `./data` (banco `app.db` e a chave de sessão).
Para trazer o histórico antigo de opções, copie `database/backtest_cache.db` para `./data/` antes do primeiro start.

- Login: defina `COPILOTO_PASSWORD` (obrigatório se o app ficar acessível na rede). Atrás de proxy reverso com HTTPS,
  use `TRUST_PROXY=true` e `COOKIE_SECURE=true`.
- Previsão TimesFM no container: `INSTALL_LAB: "true"` no `docker-compose.yml` (imagem ~1 GB maior).
- Um único worker do gunicorn: o monitor de sinais é uma thread do processo.

### Windows (local)

```bash
pip install -r requirements.txt
```

Copie `config/.env.example` para `config/.env`, preencha `TF_EMAIL`/`TF_PASSWORD` e rode `start_web.bat`
(ou `python web_app.py`). Abre em http://127.0.0.1:5000.

## O fluxo

| Etapa | Onde |
|---|---|
| Analista abre sinal → alerta (navegador, som, Telegram opcional) | monitor de sinais (sempre ativo) |
| Boleta pronta: quantidade, preço limite, máximo aceitável, custo, perda máxima, avisos | **Hoje** |
| Executar: no Home Broker (**Copiar boleta** → **Executei**) ou **Enviar ao MT5** (com confirmação) | **Hoje** / **Sinais** |
| Acompanhar posição: preço médio, P&L, retorno do sinal, vencimento, ordens abertas | **Carteira** |
| Analista encerra → **Saída pendente** com boleta de saída (ou envio ao MT5) | **Hoje** / **Carteira** |
| Importar a nota de corretagem → custos reais, IRRF e taxas calibradas | **Carteira** / **Resultados** |
| Resultado real, slippage vs. analista, IR/DARF, CSV | **Resultados** |
| Quem vale a pena seguir? Backtest de cópia, screeners, IA, base de conhecimento | **Laboratório** |

## Execução de ordens (Fase 6)

Modos (Configurações › Execução):

- **Desligado** — só manual (Home Broker).
- **Simulação** — "Enviar" manda a ordem para uma **conta simulada**: é preenchida quando a cotação atinge o limite.
  Fica separada da conta real (Carteira/Resultados têm a chave *Real | Simulação*). Use para testar a automação.
- **Real (MT5)** — ordens no MetaTrader 5. Exige a trava `EXECUTION_ENABLED=true` (Docker) ou `execution.enabled: true`
  no `settings.yaml`; a tela não consegue liberar sozinha.

Toda ordem manual passa por um modal de confirmação com as checagens de risco. Preenchimentos viram execuções
automaticamente (custos estimados até você importar a nota). Se o conector cair no meio do envio, a ordem fica
*sem confirmação* — confira no MT5 antes de reenviar.

**Automação** (precisa ser *armada*): envia sozinha as entradas de sinais novos e as saídas quando o analista encerra.
Só opções/ações, só analistas copiáveis (opcional), só sinais recém-vistos, com pregão aberto, sem posição/ordem no mesmo
ativo, preço dentro do slippage e limites diários (entradas/dia, perda do dia, valor por ordem, exposição). Cada decisão
fica registrada (Carteira › Decisões da automação). **Pânico** desarma e cancela tudo.

### MetaTrader 5 com o Copiloto no Docker

O pacote `MetaTrader5` só funciona no Windows, junto do terminal. Por isso existe o **agente MT5**:

1. No PC Windows com o MT5 aberto, logado e com *Algo Trading* ligado, defina `MT5_AGENT_TOKEN` em `config/.env`
   (gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Rode `start_mt5_agent.bat` (escuta na porta 8765; libere-a no firewall só para o IP do homelab).
3. No `.env` do Docker: `EXECUTION_BROKER=mt5_remote`, `MT5_AGENT_URL=http://<ip-do-windows>:8765` e o mesmo `MT5_AGENT_TOKEN`.

Rodando o Copiloto no próprio Windows, use `EXECUTION_BROKER=mt5_local` (sem agente).

## Notas de corretagem

Carteira ou Resultados › **Importar notas de corretagem**: envie os PDFs (XP, Genial ou outra corretora no padrão
SINACOR; PDF com senha é aceito — na XP são os 3 primeiros dígitos do CPF). O Copiloto:

- lê os negócios e o resumo financeiro (liquidação, registro, emolumentos, corretagem, ISS, IRRF);
- concilia com suas execuções do mesmo dia/ativo/lado, aplica os **custos reais** (rateados pelo valor) e corrige o preço;
- cria as execuções que faltam (importe as notas em ordem cronológica);
- recalcula as **taxas B3 e a corretagem estimadas** a partir das suas notas;
- usa o **IRRF real** das notas na apuração mensal.

Notas de BM&F (futuros) têm outro layout e não são lidas. Tickers de ações vêm do "nome de pregão"; se algum não for
reconhecido, a prévia pede para você digitar.

## Estrutura

```
web_app.py / wsgi.py       # servidor local / entrada do gunicorn (Docker)
Dockerfile, docker-compose.yml, .env.example
config/settings.yaml       # infraestrutura (API TF, monitor, trava de execução)
src/
  core/                    # config, banco + migrações, calendário B3, tickers/opções
  integrations/            # cliente TradingFloors + deduplicação única
  services/                # monitor, boleta, diário/posições, carteira, alertas, IR, resultados, notas de corretagem
  execution/               # Fase 6: ordens, risco, automação, conectores (simulação, MT5 local/remoto), agente MT5
  lab/                     # backtest de cópia, taxas BCB, TimesFM sob demanda
strategies/                # screeners, backtest de opções, base de conhecimento, ingestão YouTube
web/                       # Flask (app, auth, api/) + interface (templates/, static/)
tests/                     # pytest
```

Dados principais (`app.db`): `signals`, `executions` (contas `real`/`paper`), `orders`/`order_fills`, `notes`,
`decisions`, `alerts`, `automation_log`, `quotes`, `settings`. Posições e P&L são sempre recalculados das execuções
(preço médio com custos; day trade separado de swing por dia, como na apuração de IR).

## Testes

```bash
python -m pytest
```
