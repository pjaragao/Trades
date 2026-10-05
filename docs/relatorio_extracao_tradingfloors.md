# Relatório Técnico: Extração Integral de Trades da TradingFloors

Este documento detalha o processo de engenharia reversa, autenticação e mineração de dados utilizado para extrair **100% das operações históricas e em tempo real da plataforma TradingFloors**, explicando como foi possível acessar operações que **não pertencem ao "Desafio Eleições"**, além de apresentar o catálogo completo e estatístico de todos os dados obtidos por categoria.

---

## 1. Arquitetura da Plataforma TradingFloors

A plataforma TradingFloors opera sob a seguinte arquitetura tecnológica:
- **Frontend**: Aplicação web desenvolvida em React/Next.js que consome dados via chamadas HTTP REST e WebSocket.
- **Backend (BaaS)**: Instância do **Supabase (PostgreSQL + PostgREST)** hospedada no cluster:
  - **URL Base**: `https://ayvqtffpfmfescxzqifp.supabase.co`
  - **Autenticação**: Supabase Auth (protocolo GoTrue com tokens JWT padrão RFC 7519).

---

## 2. Como foi possível puxar TODOS os trades (inclusive os que NÃO são de eleições)

Na interface do usuário (UI) original do TradingFloors, a visualização comum é segmentada em salas ou módulos comerciais (como o *"Desafio Eleições"* ou salas restritas de mentoria). No entanto, a infraestrutura de dados por trás da plataforma permite a extração integral devido aos seguintes fatores técnicos:

### A. Descoberta das Credenciais de Acesso e Endpoints
Ao inspecionar o código-fonte empacotado (*bundles* JavaScript) do frontend da TradingFloors, foram identificados os parâmetros de inicialização do cliente Supabase:
- `supabase_url`: `https://ayvqtffpfmfescxzqifp.supabase.co`
- `supabase_anon_key`: Chave pública `anon` com permissão de handshake.
- Endpoint de Autenticação: `POST /auth/v1/token?grant_type=password`

Com o e-mail e senha da conta do usuário, o sistema realiza login direto via API:
```python
auth_url = f"{supabase_url}/auth/v1/token?grant_type=password"
resp = requests.post(auth_url, headers={"apikey": anon_key}, json={"email": email, "password": password})
access_token = resp.json()["access_token"]
```
Isso gera um **token JWT autenticado de usuário (`Bearer <JWT>`)**, que concede acesso às tabelas da base com o contexto de usuário logado.

---

### B. O "Mito" da Restrição: Filtros Client-Side vs. RLS Permissivo
No frontend web comercial do TradingFloors, o usuário só vê a sala que clicou porque o código JavaScript do navegador injeta parâmetros de filtro na URL, por exemplo:
`.../rest/v1/trades?produto=eq.Desafio%20Eleições`

Porém, ao auditar as regras de segurança no nível do banco (**Row Level Security - RLS** do PostgreSQL), constatou-se que:
> [!IMPORTANT]
> **As políticas de RLS não restringem os registros por produto ou sala para usuários autenticados.**  
> Qualquer usuário logado possui permissão de leitura (`SELECT`) sobre **todas as linhas** das tabelas `trades` e `opcoes_trades`, independentemente do produto ou trader que postou o sinal.

Dessa forma, ao efetuar a requisição **sem o filtro de produto**:
```http
GET /rest/v1/trades?select=* HTTP/1.1
Host: ayvqtffpfmfescxzqifp.supabase.co
apikey: <SUPABASE_ANON_KEY>
Authorization: Bearer <USER_ACCESS_TOKEN>
```
O servidor Supabase retorna **todas as operações de todas as salas e analistas da história da plataforma**.

---

### C. Paginação em Lote (Bypass do Limite de 1.000 Registros)
O PostgREST possui uma trava padrão que limita as consultas a no máximo 1.000 linhas por requisição (`max-rows: 1000`). Para capturar a base completa de mais de 2.000 operações, desenvolvemos um mecanismo de paginação baseado em *cursor/offset*:

```python
offset = 0
step = 1000
all_trades = []

while True:
    url = f"{supabase_url}/rest/v1/trades?select=*&order=timestamp_entrada.asc&offset={offset}&limit={step}"
    resp = requests.get(url, headers=headers)
    data = resp.json()
    if not data:
        break
    all_trades.extend(data)
    if len(data) < step:
        break
    offset += step
```
Esse mecanismo permitiu extrair o histórico ininterrupto desde **24/06/2025 até o momento presente**.

---

### D. Descoberta e Unificação da Tabela Oculta `opcoes_trades`
Durante a análise das rotas da API, descobriu-se que a plataforma mantém duas tabelas separadas para armazenar operações:
1. `trades`: Tabela principal contendo operações de Futuros (Índice, Dólar, S&P 500), Ações B3, Forex, Cripto e Commodities.
2. `opcoes_trades`: Tabela especializada contendo opções de compra (CALL) e venda (PUT), com campos adicionais de `strike`, `opcao_tipo`, `preco_atual` (marcado a mercado) e `desafio_eleicoes`.

Para criar uma base uniforme sem duplicatas, implementamos um algoritmo de **chave composta**:
$$\text{Chave} = (\text{ticker}, \text{trader\_nome}, \text{lado}, \text{data\_entrada})$$
Quando o mesmo trade existe em ambas as tabelas (por exemplo, `PETRV480` postado na sala e registrado em opções), o sistema mescla os dados, preservando a cotação em tempo real e os dados de strike.

---

## 3. Balanço Geral dos Dados Extraídos

| Métrica | Quantidade | Observação |
| :--- | :---: | :--- |
| **Registros Brutos em `trades`** | **2.282** | Futuros, Ações, Forex, Cripto, Commodities |
| **Registros Brutos em `opcoes_trades`** | **137** | Opções com cotação atual e gregas |
| **Total Bruto Extraído** | **2.419** | Total de linhas consultadas no Supabase |
| **Total Único Consolidado (Cache Local)** | **2.266** | Após mesclagem e deduplicação inteligente |
| **Operações FORA do Desafio Eleições** | **2.149 (94,8%)** | Sala Trading Floor Geral, Futuros, Day Trade, etc. |
| **Operações do Desafio Eleições** | **117 (5,2%)** | Trades específicos com tag de Eleições |
| **Janela Temporal Coberta** | **24/06/2025 a 14/09/2026** | **Mais de 1 ano e 2 meses de dados reais** |
| **Resultado Financeiro Histórico Acumulado** | **+R$ 80.147,38** | Lucro líquido consolidado de todos os analistas |
| **Taxa de Acerto Geral (Win Rate)** | **44,0%** | 985 Wins / 576 Losses / 677 Empates (Zero a Zero) |

> [!NOTE]
> As operações que **não pertencem às eleições representam quase 95% de todo o histórico da TradingFloors**, cobrindo o dia a dia regular de Day Trade e Swing Trade de todos os analistas da casa.

---

## 4. Resumo de Dados por Categoria

### A. Por Produto / Sala da Plataforma

| Produto | Total Trades | Fechados | Abertos | Taxa Acerto | PnL Acumulado (R$) | Perfil de Operação |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Trading Floor (Sala Geral)** | **2.095** | 2.084 | 11 | 42,6% | **+R$ 25.685,68** | Day Trade em Mini-índice (`WINFUT`) e Mini-dólar (`WDOFUT`), Ações e Forex. |
| **Desafio Eleições / Opções** | **117** | 102 | 15 | 70,6% | **+R$ 47.210,56** | Estratégias direcionais em Opções B3 (`PETR`, `VALE`, `MGLU`, `EMBR`). |
| **Opções (Fluxo Contínuo)** | **54** | 54 | 0 | 79,6% | **+R$ 7.251,14** | Operações estruturadas de opções fora do escopo do desafio eleitoral. |

---

### B. Por Classe de Ativo (`tipo_ativo`)

| Classe de Ativo | Total | Fechados | Abertos | Win Rate | PnL Acumulado (R$) | Principais Tickers |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Futuros (B3)** | **1.679** | 1.670 | 9 | 42,4% | **+R$ 21.245,44** | `WINFUT` (1.366), `WDOFUT` (253), `WSPFUT` (57) |
| **Ações / FIIs / BDRs (B3)** | **176** | 176 | 0 | 53,4% | **+R$ 2.092,00** | `PETR4`, `MDNE3`, `VALE3`, `PRIO3`, `WEGE3` |
| **Opções (B3)** | **133** | 118 | 15 | **81,4%** | **+R$ 54.431,14** | `PETRV480`, `MGLUJ584`, `EMBJJ100`, `VALEJ785` |
| **Forex** | **89** | 88 | 1 | 10,2% | **+R$ 821,01** | `EURUSD`, `GBPUSD`, `USDJPY`, `USDCAD` |
| **Commodities** | **80** | 80 | 0 | 43,8% | **+R$ 454,58** | `XAUUSD` (Ouro Spot) |
| **Índices Internacionais / CFDs** | **78** | 78 | 0 | 37,2% | **+R$ 1.057,93** | `SP500FT`, `NAS100FT`, `BVSPX` |
| **Criptomoedas** | **29** | 28 | 1 | 50,0% | **+R$ 45,28** | `BTCUSD` (Bitcoin) |
| *Outros / Fora de Regra* | 2 | 2 | 0 | 0,0% | R$ 0,00 | Testes de conectividade |

---

### C. Por Analista / Trader (Ranking de Operações e Performance)

O sistema conta com algoritmo de normalização inteligente que unificou variações de nomes (`FERRI`/`ferri` $\rightarrow$ **Ferri**, `SANITA`/`Sanita` $\rightarrow$ **Sanita**):

| Analista / Trader | Trades Totais | Trades Fechados | Trades Vencedores | Win Rate (%) | PnL Acumulado (R$) | Ativo Principal |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Brondi** | 666 | 666 | 223 | 33,5% | +R$ 3.942,96 | `WINFUT` (Scalping / Day Trade) |
| **Calvete** | 499 | 499 | 236 | 47,3% | +R$ 7.952,79 | `WINFUT` e `WDOFUT` (Tendência) |
| **Alexandre** | 206 | 205 | 62 | 30,2% | +R$ 371,29 | `WINFUT` (Momentum) |
| **Sanita** | 202 | 195 | 119 | **61,0%** | **+R$ 28.734,84** | Opções B3 (`PETR`, `VALE`, `EMBR`) |
| **Amilton** | 138 | 137 | 89 | **65,0%** | +R$ 1.741,00 | Futuros e Ações |
| **Pedro Prado** | 120 | 119 | 27 | 22,7% | +R$ 811,04 | Futuros |
| **Guilherme** | 108 | 105 | 76 | **72,4%** | +R$ 3.374,11 | Futuros e Ações B3 |
| **Artur Horta** | 78 | 74 | 42 | 56,8% | +R$ 6.417,59 | Opções e Swing Trade |
| **Luis Fontes** | 55 | 51 | 24 | 47,1% | +R$ 335,54 | Futuros |
| **Felipe Corleta** | 52 | 52 | 34 | **65,4%** | +R$ 1.235,46 | Swing Trade Ações |
| **Guto** | 52 | 52 | 25 | 48,1% | +R$ 296,60 | Ações e Futuros |
| **Saviola** | 25 | 24 | 5 | 20,8% | +R$ 18,20 | Futuros |
| **Ferri** | 19 | 15 | 14 | **93,3%** | **+R$ 24.455,00** | Opções B3 (`PETRV480`, `VALEJ785`) |
| **Wanderson Assis** | 16 | 16 | 7 | 43,8% | +R$ 370,00 | Futuros |
| **Ademar** | 12 | 12 | 1 | 8,3% | -R$ 0,04 | Futuros |
| **Leon Suhett** | 12 | 12 | 1 | 8,3% | +R$ 91,00 | Futuros |
| **Relatórios** | 6 | 6 | 0 | 0,0% | R$ 0,00 | Sinais institucionais |

---

### D. Top 15 Ativos Mais Operados na História da Plataforma

| Ticker | Classe | Total de Trades | PnL Acumulado (R$) | Características |
| :--- | :--- | :---: | :---: | :--- |
| **WINFUT** | Futuros (B3) | **1.366** | +R$ 17.798,63 | Mini-índice B3. Principal instrumento de day trade da sala. |
| **WDOFUT** | Futuros (B3) | **253** | +R$ 3.241,69 | Mini-dólar B3. Segundo ativo com maior liquidez e volume. |
| **XAUUSD** | Commodities | **77** | +R$ 455,34 | Ouro spot internacional. Operado em horários alternativos. |
| **WSPFUT** | Futuros (B3) | **57** | +R$ 139,52 | Futuro do S&P 500 negociado na B3. |
| **SP500FT** | Índices/CFDs | **48** | -R$ 124,82 | CFD do S&P 500 internacional. |
| **BTCUSD** | Cripto | **29** | +R$ 45,28 | Bitcoin contra dólar. |
| **EURUSD** | Forex | **25** | +R$ 1,05 | Par cambial Euro / Dólar. |
| **GBPUSD** | Forex | **22** | R$ 0,00 | Par cambial Libra / Dólar. |
| **NAS100FT** | Índices/CFDs | **18** | -R$ 18,63 | Futuro / CFD do Nasdaq 100. |
| **USDJPY** | Forex | **13** | +R$ 844,03 | Dólar contra Iene japonês. |
| **USDCAD** | Forex | **11** | -R$ 2,99 | Dólar americano contra Dólar canadense. |
| **BVSPX** | Índices/CFDs | **10** | +R$ 1.110,38 | Índice Bovespa à vista. |
| **USDCHF** | Forex | **7** | R$ 0,00 | Dólar contra Franco suíço. |
| **PETR4** | Ações B3 | **6** | +R$ 42,00 | Petrobras PN (operações diretas à vista). |
| **MDNE3** | Ações B3 | **5** | +R$ 274,00 | Moura Dubeux ON (Swing trade acionário). |
