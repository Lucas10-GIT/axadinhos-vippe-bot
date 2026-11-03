# Axadinhos Vippe Bot

Aplicativo Streamlit para importar e revisar ofertas da Shopee e publicá-las, quando autorizadas, no Telegram e/ou Pinterest. A base oficial fica em `data/products.csv` no GitHub. Os dois canais são opcionais e possuem opt-ins independentes; nenhum token, por si só, libera publicações.

## Importar links Shopee em lote

Na aba **Produtos**, cole até 20 links HTTPS da Shopee por lote, separados por linha, espaço ou vírgula. O importador tenta obter nome, preço, foto e categoria pela API de afiliados quando as credenciais autorizadas estão disponíveis; caso contrário, usa leitura best-effort de metadados públicos, HTML e JSON embutido. A Shopee pode omitir os dados ou bloquear a leitura, então revise e complete os campos manualmente.

O link original é preservado para manter o rastreamento de afiliado. Links fora dos domínios HTTPS aceitos e duplicatas são ignorados. A importação adiciona os produtos à sessão do Streamlit; **Salvar produtos** grava a tabela no GitHub. Todo item novo começa **inativo**, **sem aprovação** e com os dois destinos em estado `pendente`. Revise nome, preço, imagem e destino antes de ativá-lo e aprová-lo.

O acesso à Shopee Affiliate Open API depende de concessão da própria Shopee. Sem acesso, a importação tradicional continua disponível e não tenta contornar a autorização.

## Publicação Telegram e Pinterest

A aba **Canais** informa se os Secrets estão presentes e se a publicação manual foi habilitada. Cada canal é independente:

- **Telegram:** usa a API oficial de bots para publicar em um canal ou grupo configurado, com link de afiliado original e aviso de afiliado. Não envia DMs em massa.
- **Pinterest:** cria um Pin de imagem pela API oficial v5, usando a URL original de afiliado no campo de destino e incluindo aviso de afiliado. Exige board ID, imagem pública HTTPS e dados revisados.

Crie um bot novo pelo @BotFather se desejar usar Telegram; mantenha o token privado e dê ao bot apenas as permissões necessárias no canal/grupo que você administra ou está autorizado a usar. A integração não lê os Secrets antigos `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`; ela usa somente `TELEGRAM_PUBLISHER_BOT_TOKEN` e `TELEGRAM_PUBLISHER_CHAT_ID`. Um bot diferente não contorna restrições da plataforma.

O botão do Streamlit publica apenas nos canais com opt-in manual habilitado. Se os dois estiverem ativos, o envio é **sequencial**, não simultâneo nem atômico. Antes do primeiro post, os destinos selecionados passam por pré-validação. A reserva do produto e o recibo de cada canal são gravados no CSV. Se um canal publicar e o outro falhar, o sucesso é preservado e a falha fica para revisão; não há retry automático de resultado ambíguo.

Todo produto precisa estar ativo e aprovado manualmente. O publicador processa no máximo uma oferta elegível por execução, aplica cooldown global mínimo de quatro horas e respeita a frequência por produto: 2 dias para produtos com pelo menos 2 pedidos, 4 dias para produtos com 10 ou mais cliques e 3 dias nos demais casos. Quando mais de um item estiver elegível, o maior score, baseado em pedidos, comissão estimada e conversão de cliques, tem prioridade.

## Agendamento no GitHub Actions

O workflow `.github/workflows/publish-offers.yml` verifica ofertas a cada quatro horas (`0 */4 * * *`, UTC), mas fica bloqueado até que haja opt-in explícito. São necessárias:

- `AXADINHOS_AUTO_PUBLISH=true` — trava geral;
- `AXADINHOS_TELEGRAM_AUTO_PUBLISH=true` — opt-in agendado específico do Telegram;
- `AXADINHOS_PINTEREST_AUTO_PUBLISH=true` — opt-in agendado específico do Pinterest.

A trava geral precisa estar ativa junto de pelo menos um opt-in de canal. O agendamento processa no máximo uma oferta por execução. Antes de ativá-lo, confira todos os produtos marcados **Ativo** e **Aprovado para publicação**, pois uma oferta elegível pode ser publicada automaticamente.

A execução manual pelo GitHub Actions exige marcar `confirm_publish` e selecionar explicitamente `publish_telegram`, `publish_pinterest` ou ambos. O workflow usa o `GITHUB_TOKEN` temporário do próprio run, com permissão de gravação restrita ao job, além dos Secrets dos canais selecionados.

## Configuração

Consulte o [guia de Secrets](CONFIGURAR-SECRETS.md) para configurar o Streamlit Cloud, GitHub Actions e, quando disponível, a Shopee Affiliate Open API. Os armazenamentos do Streamlit e do GitHub são separados. Os opt-ins manuais e agendados começam desativados por padrão.

Exemplo para os Secrets do Streamlit:

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"
telegram_publisher_bot_token = "TOKEN_DO_NOVO_BOT"
telegram_publisher_chat_id = "@SEU_CANAL_OU_ID_NUMERICO"
telegram_publish_enabled = false
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
```

Mantenha `telegram_publish_enabled` e `pinterest_publish_enabled` em `false` enquanto configura. Altere apenas o canal que estiver pronto para publicar conteúdo real.

## Testes locais

Os testes usam sessões falsas e não fazem chamadas reais ao GitHub, Telegram, Pinterest ou Shopee. Cobrem importação, aprovação, preservação de links, payloads, opt-ins, cooldown, prevenção de duplicatas e falhas parciais entre canais.

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```
