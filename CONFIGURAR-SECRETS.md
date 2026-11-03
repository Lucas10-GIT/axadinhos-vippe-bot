# Configuração de Secrets — Axadinhos Vippe Bot

As credenciais ficam fora do repositório. **Não cole tokens no chat, na planilha, no código ou em commits.** Streamlit Cloud e GitHub Actions usam armazenamentos separados; configurar um Secret em um deles não configura o outro. Telegram e Pinterest são opcionais e têm opt-ins independentes, desativados por padrão.

## 1. Streamlit Cloud — importação e publicação manual

No Streamlit Cloud, abra **Manage app → Settings → Secrets**, adicione as entradas necessárias, salve e recarregue o app. O painel mostra somente se cada credencial está presente, nunca o valor.

### GitHub, Telegram e Pinterest

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"

# Telegram: use o token do bot novo criado pelo @BotFather.
telegram_publisher_bot_token = "TOKEN_DO_NOVO_BOT"
telegram_publisher_chat_id = "@SEU_CANAL_OU_ID_NUMERICO"
telegram_publish_enabled = false

# Pinterest: opcional.
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
```

Para configurar Telegram, crie o bot no @BotFather e **não compartilhe o token**. Adicione o bot como administrador do canal ou grupo que você administra/está autorizado a usar, com a permissão necessária para publicar. O destino pode ser o `@username` público ou o ID numérico do chat. Este sistema publica no destino configurado; não faz envio em massa de mensagens diretas.

A integração lê apenas `telegram_publisher_bot_token` e `telegram_publisher_chat_id`. Ela **não usa** os Secrets antigos `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`, evitando reaproveitar acidentalmente o token anterior. Um bot novo não contorna suspensões ou restrições da plataforma.

Mantenha `telegram_publish_enabled=false` e `pinterest_publish_enabled=false` durante a configuração. Altere para `true` somente o canal que estiver pronto para criar conteúdo público real. A presença de token não habilita publicação. O produto também precisa estar ativo, aprovado manualmente, elegível e com dados válidos. No Pinterest, são obrigatórios nome, preço, imagem pública HTTPS, board ID numérico e link Shopee; o Pin usa o link original de afiliado.

### Shopee Affiliate Open API (opcional)

Só adicione estas três entradas depois que a Shopee conceder acesso à Open API e fornecer App ID e App Secret:

```toml
shopee_affiliate_app_id = "APP_ID_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_secret = "APP_SECRET_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_admin_pin = "ESCOLHA_UM_PIN_PRIVADO_E_FORTE"
```

O PIN administrativo é escolhido por você; não é uma chave emitida pela Shopee. Ele protege o botão de conexão no app público. Com os três valores salvos, abra **Produtos → Conectar API de Afiliados Shopee**, informe o PIN e use **Conectar / testar API**. Esse teste é somente leitura. Se a Shopee ainda não concedeu acesso, adicionar Secrets não libera a API: use a importação pública best-effort enquanto aguarda. Produtos importados continuam inativos e sem aprovação.

## 2. GitHub Actions — publicação agendada ou avulsa

No repositório `Lucas10-GIT/axadinhos-vippe-bot`, abra **Settings → Secrets and variables → Actions**.

### Repository secrets

Configure apenas os canais que pretende usar:

- Telegram: `TELEGRAM_PUBLISHER_BOT_TOKEN` e `TELEGRAM_PUBLISHER_CHAT_ID` — credenciais do **bot novo** e destino autorizado.
- Pinterest: `PINTEREST_ACCESS_TOKEN` e `PINTEREST_BOARD_ID`.

O GitHub Actions usa o `GITHUB_TOKEN` temporário do próprio run para gravar o estado no CSV, com permissão limitada ao job. Não crie um PAT adicional chamado `GITHUB_TOKEN`. A API de afiliados Shopee não é necessária para publicar produtos que já estão na tabela.

### Repository variables para o agendamento

O cron é bloqueado por padrão. Para habilitar publicação automática, configure a trava geral e pelo menos um opt-in de canal, cada um com o valor exato `true`:

- `AXADINHOS_AUTO_PUBLISH` — trava geral;
- `AXADINHOS_TELEGRAM_AUTO_PUBLISH` — opt-in agendado específico do Telegram;
- `AXADINHOS_PINTEREST_AUTO_PUBLISH` — opt-in agendado específico do Pinterest.

Um Secret configurado não liga o cron. Sem a variável específica do Telegram, o Telegram não publica no agendamento. O workflow verifica a base a cada quatro horas e processa no máximo uma oferta elegível por execução, respeitando cooldown global mínimo de quatro horas. Revise todos os produtos **Ativos** e **Aprovados para publicação** antes de habilitar qualquer opt-in, pois a próxima execução pode publicar uma oferta.

Uma execução manual pelo formulário do Actions é avulsa: marque `confirm_publish` e selecione explicitamente `publish_telegram`, `publish_pinterest` ou ambos. Só os canais selecionados recebem publicação; os Secrets correspondentes precisam estar configurados. A publicação entre canais é sequencial, não simultânea.

## 3. Ordem segura de ativação

1. Configure `github_token` no Streamlit e confira apenas o indicador de presença.
2. Para Telegram, crie o novo bot no @BotFather, mantenha o token privado, adicione o bot como administrador ao destino autorizado e informe os dois novos Secrets. Deixe `telegram_publish_enabled=false` enquanto configura.
3. Para Pinterest, configure os Secrets necessários e mantenha `pinterest_publish_enabled=false` até validar token e board.
4. Se a Shopee tiver concedido acesso à Open API, configure os três Secrets Shopee e valide a conexão de leitura; caso contrário, deixe-os ausentes e use a importação tradicional.
5. Importe poucos links e confira cuidadosamente nome, preço, foto e link afiliado. Salve os produtos; novos itens permanecem inativos, sem aprovação e pendentes nos dois destinos.
6. Ative e aprove manualmente somente produtos revisados. Faça a prévia dos canais e confirme se o destino está correto.
7. Habilite `telegram_publish_enabled=true` ou `pinterest_publish_enabled=true` apenas quando estiver pronto para um envio manual real. Um clique publica nos canais habilitados.
8. Configure as variáveis de Actions somente se quiser cron. A confirmação manual do workflow exige marcar a confirmação e selecionar os destinos.

## 4. Diagnóstico rápido

- **Botão manual indisponível:** confira `github_token`, o opt-in `*_publish_enabled=true` do canal pretendido, os Secrets daquele destino e se o produto está ativo, aprovado, elegível e fora do cooldown.
- **Telegram não reconhece destino:** use `@username` público válido ou ID numérico; confira se o novo bot foi adicionado ao canal/grupo com permissão para publicar.
- **Telegram credenciais ausentes:** configure `telegram_publisher_bot_token` e `telegram_publisher_chat_id` no Streamlit; para Actions, configure `TELEGRAM_PUBLISHER_BOT_TOKEN` e `TELEGRAM_PUBLISHER_CHAT_ID`. Os nomes antigos não são lidos.
- **Pin bloqueado antes do envio:** confira nome, preço, link HTTPS válido da Shopee, imagem pública HTTPS e Board ID numérico.
- **Workflow agendado não publica:** confira `AXADINHOS_AUTO_PUBLISH=true`, o opt-in do canal específico, Secrets, aprovação do produto e cooldown de quatro horas.
- **Workflow manual não publica:** marque `confirm_publish` e escolha ao menos um destino; confira os Secrets selecionados.
- **Falha ou estado `revisar`:** confira manualmente cada destino antes de mudar o status do canal para `pendente`. O sistema não repete automaticamente um envio cujo resultado seja ambíguo.
- **Shopee Affiliate API recusada:** confirme primeiro se a conta recebeu acesso; Secrets não contornam a autorização da Shopee.
