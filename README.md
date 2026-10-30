# Axadinhos Vippe Bot

Aplicativo Streamlit para manter uma lista de produtos, gerar textos de divulgação e, quando configurado, enviar uma publicação ao Telegram. Os dados são armazenados em `data/products.csv` no GitHub.

## O que está pronto

- cadastro e edição de produtos pelo Streamlit;
- persistência da planilha no arquivo `data/products.csv`;
- geração de texto para divulgação;
- envio manual de uma mensagem de teste pela aba Telegram;
- publicador reutilizável em `publish_telegram.py`;
- testes automatizados sem tokens ou envio real, executados pelo GitHub Actions;
- smoke test real do Telegram acionado manualmente, com confirmação explícita.

A seleção de produtos usa os cliques, pedidos e comissões preenchidos na planilha. O bot não busca métricas de vendas da Shopee automaticamente.

## Primeiro teste automatizado

Os testes locais não precisam de tokens e não enviam mensagens. Com Python 3.12 ou compatível:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

O GitHub Actions também executa os testes em push para `main`, pull requests e acionamento manual. O workflow de testes tem apenas permissão de leitura do repositório e não publica no Telegram.

## Configuração do Streamlit

Configure estes valores em **Streamlit Cloud → App settings → Secrets**:

```toml
github_token = "TOKEN_COM_ACESSO_AO_CONTEUDO_DO_REPOSITORIO"
telegram_bot_token = "TOKEN_DO_BOT"
telegram_chat_id = "ID_DO_CHAT_OU_CANAL"
```

O `github_token` precisa de permissão para ler e gravar `data/products.csv`. Sem ele, o aplicativo abre com uma lista vazia e não consegue persistir alterações. Para o envio, adicione o bot ao grupo/canal e conceda as permissões necessárias.

## Publicador e segredos

O script `publish_telegram.py` só executa quando chamado diretamente; importá-lo em testes não faz chamadas de rede. Para execução real, configure:

- `GH_AUTOMATION_TOKEN` (preferido) ou `GITHUB_TOKEN`, com acesso de gravação ao conteúdo do repositório;
- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_CHAT_ID`.

Nunca inclua tokens no código, em arquivos `.csv`, em commits ou em logs. O envio atualiza a data de publicação no CSV somente após o Telegram confirmar sucesso.

## Teste real de envio via GitHub Actions

Os secrets de repositório `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` já estão configurados. O workflow `.github/workflows/telegram-smoke-test.yml` usa esses secrets somente quando acionado manualmente na branch `main`; não roda em push nem em pull request. Não é necessário inserir os valores dos tokens no workflow ou no código.

Para iniciar: abra **Actions → Teste real de envio Telegram → Run workflow**, selecione `main` e marque `confirm_send`. Isso envia uma única mensagem silenciosa (`disable_notification`) ao destino guardado em `TELEGRAM_CHAT_ID`. O teste não publica produto, não chama `publish_telegram.py` e não modifica `data/products.csv`. O `GH_AUTOMATION_TOKEN` não é usado por esse smoke test.

Texto enviado:

> TESTE TÉCNICO — Axadinhos Vippe  
> Mensagem de validação enviada pelo GitHub Actions.  
> Este não é um anúncio de produto.

## Publicação automática

Nenhuma publicação agendada está habilitada por padrão. Antes de ativar um agendamento ou enviar uma mensagem real, valide o chat de destino e o produto que será divulgado. Frequência inicial do publicador: produto vencedor (2 ou mais pedidos), a cada 2 dias; produto em teste (10 ou mais cliques), a cada 4 dias; demais produtos, a cada 3 dias.
