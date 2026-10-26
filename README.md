# Axadinhos Vippe Bot V2

Este projeto adiciona:

- planilha editável dentro do Streamlit;
- banco persistente em `data/products.csv` no GitHub;
- link direto da imagem do produto;
- geração de anúncios;
- envio para Telegram;
- agendamento via GitHub Actions;
- regra inicial de repetição para produtos vencedores.

## Secrets

No Streamlit Cloud, configure:

- `github_token`
- `telegram_bot_token`
- `telegram_chat_id`

Para o GitHub Actions, configure:

- `GH_AUTOMATION_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Nunca coloque tokens no código ou no CSV.

## Importante sobre "produto vencedor"

A primeira versão usa cliques, pedidos e comissão que estejam registrados na planilha.
Ela não consegue adivinhar vendas da Shopee sem uma fonte oficial de métricas/API.
Quando tivermos acesso aos relatórios/API de afiliados, substituímos os campos manuais pela coleta automática.

## Agendamento

O GitHub Actions verifica a cada 6 horas se algum produto está vencido.
A frequência é adaptada:
- vencedor: 2 dias;
- em teste: 4 dias;
- novo: 3 dias.

Isso é uma regra inicial e pode ser ajustada depois com dados reais.

## Telegram

Crie o bot pelo @BotFather, adicione-o ao canal/grupo e use o chat ID correspondente.
