# Robô de Automação de Trades: TradingFloors -> MetaTrader 5 (B3)

Automação completa para sincronizar recomendações de trade da plataforma **TradingFloors** (Desafio Eleições, Opções e Futuros B3) diretamente para o **MetaTrader 5**.

---

## Recursos Principais

- **Captura em Tempo Real**: Conexão com a API da TradingFloors para identificar novos sinais e saídas de forma contínua.
- **Gestão de Risco e Dimensionamento**:
  - Alocação financeira em R$ máxima por trade (ex: R$ 1.000 por operação) convertendo para lotes padrão da B3 (múltiplos de 100).
  - Filtro por produtos (ex: apenas Opções / Desafio Eleições).
  - Filtro por analistas/traders específicos.
  - Limite de posições simultâneas e controle de desvio de preço (*slippage*).
- **Rastreamento Local e Idempotência**: Banco SQLite que mapeia o ID de cada sinal ao ticket da ordem no MT5, garantindo que saídas sejam encerradas com precisão e evitando duplicidades.
- **Modo Simulação (Dry-Run)**: Teste completo de todos os cálculos e fluxos com dados de mercado reais sem enviar ordens financeiras à corretora.

---

## Estrutura do Projeto

```
c:\Users\paulojr\Documents\trades\
├── config\
│   ├── settings.yaml          # Configurações de risco, limites e filtros
│   ├── .env                   # Credenciais (TradingFloors e MT5)
│   └── .env.example
├── src\
│   ├── client_tf.py           # Conexão com a API Supabase do TradingFloors
│   ├── risk_manager.py        # Validação de regras e dimensionamento de lotes
│   ├── order_tracker.py       # Banco SQLite local de tickets e posições
│   ├── mt5_bridge.py          # Conector MetaTrader 5 com suporte a Simulação
│   ├── engine.py              # Motor do loop de sincronização
│   └── logger.py              # Visualização em terminal com tabelas e logs
├── database\
│   └── trades_tracker.db      # Histórico de ordens e posições sincronizadas
├── main.py                    # Script principal de execução
├── test_dry_run.py            # Validação rápida de funcionamento
└── requirements.txt           # Dependências
```

---

## Como Executar

### 1. Teste de Validação Rápido (Modo Simulado)
Para testar a conexão com a plataforma e ver o cálculo dos lotes para as opções atualmente abertas:

```bash
python test_dry_run.py
```

### 2. Verificar Conexão e Ordens Ativas
Para visualizar a tabela de todas as ordens abertas no TradingFloors sem iniciar o robô:

```bash
python main.py --check-connection
```

### 3. Executar o Robô em Modo Simulação (Recomendado no início)
Monitora novos sinais e simula as ordens no terminal sem risco:

```bash
python main.py --dry-run
```

*Por padrão, o robô opera em modo `only_new`, aguardando novas recomendações. Se quiser simular a entrada imediata nas ordens já abertas na plataforma:*
```bash
python main.py --dry-run --sync-all
```

### 4. Consultar Histórico Local de Ordens Rastreadas
```bash
python main.py --status
```

---

## Passos para Operação em Conta Real (MetaTrader 5)

Quando estiver pronto para enviar ordens reais para sua corretora (Clear, XP, Genial, etc.):

1. **Instale o Terminal Desktop do MetaTrader 5**:
   - Baixe o instalador fornecido pela sua corretora ou em [MetaTrader 5](https://www.metatrader5.com/).
2. **Habilite a Negociação Automatizada**:
   - No MT5, acesse o menu superior: **Ferramentas > Opções > Expert Advisors**
   - Marque a caixa: **"Permitir negociação automatizada"** (Algo Trading).
   - O botão "Algo Trading" na barra superior do MT5 deve ficar **verde**.
3. **Faça login na conta da corretora no terminal MT5**.
4. **Ative a Conta Real no Robô**:
   - Altere no arquivo `config/settings.yaml`:
     ```yaml
     execution:
       dry_run: false
     ```
   - Ou execute via linha de comando:
     ```bash
     python main.py --live
     ```
