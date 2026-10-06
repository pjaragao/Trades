# Copiloto de Trades

App pessoal para seguir os sinais dos analistas do **TradingFloors**. Ele avisa quando um analista abre ou encerra
uma operação, entrega a boleta pronta, registra o que você executou (no Home Broker ou via MetaTrader 5),
importa as notas de corretagem e mostra se você está ganhando dinheiro de verdade (com custos reais, slippage e IR).

## Rodando

### Docker (homelab)

```bash
cp .env.example .env        # preencha COPILOTO_PASSWORD, TF_EMAIL, TF_PASSWORD (e BRAPI_TOKEN)
docker compose up -d --build
```

Acesse `http://<ip-do-homelab>:5000`. Os dados ficam em `./data` (banco `app.db` e a chave de sessão).
Para trazer o histórico antigo de opções, copie `database/backtest_cache.db` para `./data/` antes do primeiro start.

- Login: `COPILOTO_PASSWORD` é obrigatório. Atrás de proxy reverso com HTTPS, use `COOKIE_SECURE=true` e
  `TRUST_PROXY=<nº de proxies>` (1 = só o Coolify/Traefik; 2 = nginx na frente do Coolify).
- Previsão TimesFM no container: `INSTALL_LAB=true` (imagem ~1 GB maior).
- Um único worker do gunicorn: o monitor de sinais e o feed de cotações são threads do processo.
- O container começa como root só para ajustar o dono de `/data` e roda o app como usuário `copiloto` (uid 1000).

### Coolify (WSL + nginx)

1. Coolify › novo recurso › **Docker Compose** apontando para este repositório (branch `main`).
2. Em *Environment Variables*, preencha `COPILOTO_PASSWORD`, `TF_EMAIL`, `TF_PASSWORD`, `BRAPI_TOKEN`,
   `COOKIE_SECURE=true` e `TRUST_PROXY` (1 se só o Coolify; 2 se o nginx estiver na frente dele).
3. Associe o domínio ao serviço `copiloto`, porta 5000. O mapeamento `ports:` do compose é opcional no Coolify.
4. As cotações ao vivo usam **Server-Sent Events** (`/api/stream`). O app já manda `X-Accel-Buffering: no`; se o
   nginx tiver configuração própria para o site, garanta:

```nginx
location /api/stream {
    proxy_pass http://<upstream>;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_read_timeout 1h;
}
```

Se algum proxy segurar o stream mesmo assim, a tela percebe em ~45 s e passa a consultar `/api/quotes` a cada 3 s.

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
| Importar a nota de corretagem → histórico ajustado à nota (qtd, preço, data, custos), IRRF e taxas calibradas | **Notas e IR** / **Carteira** |
| Resultado real, slippage vs. analista, CSV | **Resultados** |
| IRPF mês a mês (fechado com notas x estimado), DARF, IR se encerrar tudo agora, resumo anual | **Notas e IR** |
| Quem vale a pena seguir? Backtest de cópia, screeners, IA, base de conhecimento | **Laboratório** |

## Baixa automática de sinais já executados

O aviso do analista costuma chegar antes no WhatsApp do que na API do TradingFloors (ex.: entrada 12:19, API 12:20:33).
Se você já executou e registrou a ordem, o Copiloto vincula a execução ao sinal e marca como **executado**:

- **sinal chega depois:** execuções do mesmo ativo e lado, sem sinal, feitas desde 30 min antes da entrada do analista
  (ou registradas nos últimos 30 min) — o alerta vira "Já executado" em vez de "Novo sinal"; ordens abertas no MT5 também
  são vinculadas;
- **você registra depois:** "Registrar operação" sem escolher sinal vincula ao sinal aberto do mesmo ativo e lado;
- **nota de corretagem:** execuções criadas pela nota também dão baixa nos sinais do mesmo pregão;
- a cada ciclo o monitor revisa execuções das últimas 72 h que ficaram sem sinal.

**Trade semelhante em aberto:** um sinal no mesmo ativo-objeto de uma posição sua (ex.: ROXOK135 da Sanita com ROXOJ12
do Ferri em carteira) continua aparecendo, com um aviso mostrando a posição parecida — mesma direção (aumenta a exposição),
direção contrária ou o mesmo ativo (com o atalho "É este trade — vincular").

Só entram execuções que abrem/aumentam posição no sentido do sinal. A janela é ajustável em Configurações › Quem seguir
(0 desliga).

## Cotações

| Fonte | O quê | Atraso | Quando |
|---|---|---|---|
| **MT5** (agente no Windows) | ações e opções, com compra × venda | tempo real (a cada 2 s) | se `MT5_AGENT_URL`/`MT5_AGENT_TOKEN` estiverem definidos |
| **brapi.dev** | só ações | até 30 min (plano gratuito) | se `BRAPI_TOKEN` estiver definido e a ação não tiver MT5 ao vivo |
| **TradingFloors** | opções abertas dos sinais | desconhecido | sempre (reserva) |
| manual | qualquer ativo | — | Carteira › clicar no preço |

Os preços mudam na tela sem recarregar (Hoje, Carteira, Sinais, boleta e confirmação de ordem), com a fonte e o horário
de cada cotação. Com MT5 ao vivo, a boleta usa a **oferta de venda** para compras e a **de compra** para vendas.
Se o MT5 cair, ações passam para a brapi e opções voltam ao TradingFloors em ~2 min — o chip *Cotações* e a boleta avisam.

**brapi no plano gratuito** (1 ativo por requisição, dados renovados a cada 30 min, 15.000 requisições numa janela
móvel de 30 dias). O Copiloto dimensiona as consultas para não estourar:

- no máximo `BRAPI_DAILY_BUDGET=450` requisições por dia (90% de 15.000/30), contadas no banco;
- só ações acompanhadas (posições, ordens, sinais abertos dos analistas seguidos, boleta aberta) e sem MT5 ao vivo;
- no pregão, cada ação no máximo a cada 30 min; com muitas ações o intervalo cresce para o teto durar até o fechamento
  (até ~30 ações a cada 30 min cabem no teto); depois do pregão, uma consulta por ação para o fechamento;
- lê o saldo da janela de 30 dias informado pela brapi e pausa até o dia seguinte se restarem menos de 1.000, ou se ela
  responder 429. Uso e saldo aparecem em Configurações › Cotações.

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

O MetaTrader 5 não tem versão nativa para Linux (só via Wine, que o Copiloto não usa), e o pacote Python
`MetaTrader5` só funciona no Windows, junto do terminal. Por isso existe o **agente MT5**, que roda no Windows — num
homelab com WSL, o próprio Windows que hospeda o WSL:

1. No Windows, com o MT5 aberto e logado (e *Algo Trading* ligado, se for enviar ordens), defina `MT5_AGENT_TOKEN`
   em `config/.env` (gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"`).
2. Rode `start_mt5_agent.bat` — ou `start_mt5_agent.bat --readonly` para **só cotações** (o agente recusa ordens).
   Ele escuta na porta 8765; libere-a no Firewall do Windows (PowerShell como administrador):
   `New-NetFirewallRule -DisplayName "Copiloto MT5" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -RemoteAddress LocalSubnet`
3. No Docker/Coolify: `MT5_AGENT_URL=http://<ip-do-windows-na-rede>:8765` e o mesmo `MT5_AGENT_TOKEN`.
   Use o IP do Windows na rede local (o IP interno do WSL muda a cada boot). Com `networkingMode=mirrored` no
   `.wslconfig`, ative também `hostAddressLoopback=true` para os containers alcançarem o IP do próprio host.

O horário dos ticks/negócios do MT5 vem no fuso do servidor da corretora (Brasília nas corretoras da B3;
`MT5_SERVER_UTC_OFFSET=-3`). Rodando o Copiloto no próprio Windows, use `EXECUTION_BROKER=mt5_local` (sem agente).

## Notas de corretagem

**Notas e IR** (ou Carteira) › **Importar notas de corretagem**: envie os PDFs (XP, Genial ou outra corretora no padrão
SINACOR; PDF com senha é aceito — na XP são os 3 primeiros dígitos do CPF). **A nota é a verdade** e o histórico é
ajustado a ela:

- quantidade, preço (de entrada e de saída), data do pregão e **custos reais** (rateados pelo valor) passam a ser os da nota;
- várias execuções no mesmo dia: usa as que somam a quantidade da nota (cada uma com o preço do seu negócio, quando dá);
  se não bater, elas viram uma só com os números da nota;
- execução registrada em outro dia (até 7 dias, sem nota própria) tem a data corrigida para o pregão da nota;
- o que falta é criado (inclusive vendas que abrem posição, ex.: lançamento de opções);
- o que você registrou no pregão mas não está na nota aparece para **manter** (pode ser de outra corretora) ou **excluir**;
- recalcula as **taxas B3 e a corretagem estimadas** a partir das suas notas e guarda o **IRRF** de cada pregão;
- **desfazer** devolve as execuções ao estado anterior. Importe as notas em ordem cronológica.

Notas de BM&F (futuros) têm outro layout e não são lidas. Tickers de ações vêm do "nome de pregão"; se algum não for
reconhecido, a prévia pede para você digitar.

## Imposto de renda (Notas e IR)

- **Apuração mês a mês** com memória de cálculo: ações (isenção até R$ 20 mil de vendas no mês), opções e outros
  (sem isenção), day trade, prejuízos a compensar (swing e day trade separados), IRRF, DARF 6015 e vencimento.
- **Só fecha com nota:** o mês fica *Fechado com notas* quando todos os pregões com operações têm nota importada; caso
  contrário o valor aparece como *Estimado*, com a lista dos pregões sem nota.
- **Se eu encerrar tudo agora:** simula vender/recomprar todas as posições abertas ao preço atual (com custos estimados)
  e mostra o IR do mês antes e depois, posição por posição — incluindo day trade de quem foi comprado hoje e a perda
  da isenção se as vendas de ações passarem de R$ 20 mil.
- **Resumo anual** para a declaração: lucro isento com ações, resultados tributáveis, DARF, IRRF e prejuízo a compensar.

Simplificações: FIIs, ETFs e BDRs entram como ações. Confira com seu contador.

## Estrutura

```
web_app.py / wsgi.py       # servidor local / entrada do gunicorn (Docker)
Dockerfile, docker-compose.yml, .env.example
config/settings.yaml       # infraestrutura (API TF, monitor, trava de execução)
src/
  core/                    # config, banco + migrações, calendário B3, tickers/opções
  integrations/            # cliente TradingFloors + deduplicação única, fontes de cotação (MT5, brapi)
  services/                # monitor, cotações ao vivo, boleta, diário/posições, carteira, alertas, IR, resultados, notas
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
