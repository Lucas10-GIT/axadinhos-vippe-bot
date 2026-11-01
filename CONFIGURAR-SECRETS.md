# Configuração de secrets — Axadinhos Vippe Bot

O código está preparado para receber as credenciais sem colocá-las no repositório. **Nunca cole tokens no chat, na planilha, no código ou em commits.** Streamlit Cloud e GitHub Actions têm armazenamentos separados: cadastrar um segredo em um deles não o cadastra no outro.

## 1. Streamlit Cloud — operação manual pelo app

Abra o app no Streamlit Cloud, escolha **Manage app → Settings → Secrets** e adicione os valores necessários. Depois salve e recarregue o app. O painel mostra somente indicadores de presença; não imprime os valores.

### Obrigatórios para publicar manualmente no Telegram

```toml
github_token = "COLE_AQUI_UM_TOKEN_COM_ACESSO_AO_REPOSITORIO"
telegram_bot_token = "COLE_AQUI_O_TOKEN_DO_BOT"
telegram_chat_id = "COLE_AQUI_O_ID_DO_CHAT_OU_CANAL"
```

Substitua os textos de exemplo pelos valores reais antes de salvar. Use um token GitHub de acesso fino restrito a este repositório, com permissão **Contents: read and write**; o app não precisa de permissão Actions. O bot precisa ter permissão de publicação no chat/canal. A publicação manual continua exigindo produto ativo e aprovado.

### Opcionais para publicar também no Pinterest pelo botão manual

```toml
pinterest_access_token = "COLE_AQUI_O_TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "COLE_AQUI_O_ID_DO_BOARD"
pinterest_publish_enabled = false
```

Mantenha `false` durante a configuração. Para publicar também no Pinterest em uma ação manual, altere para `true` depois de conferir o token e o board. **Não existe modo de teste sem publicação para essa chamada:** ao clicar no botão com Pinterest habilitado, o Pin será criado de verdade. A mesma ação envia ao Telegram e ao Pinterest. Para Telegram somente, mantenha `false`.

O token precisa estar válido e ter acesso para criar Pins no board indicado. O produto precisa ter nome, preço, link HTTPS da Shopee e imagem pública HTTPS. O texto do Pin contém aviso de link de afiliado; o endereço original de afiliado é mantido.

### Opcionais para leitura pela Shopee Affiliate Open API

Só adicione estas três entradas depois que a Shopee conceder acesso à Open API e fornecer o App ID e o App Secret:

```toml
shopee_affiliate_app_id = "APP_ID_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_secret = "APP_SECRET_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_admin_pin = "ESCOLHA_UM_PIN_PRIVADO_E_FORTE"
```

O PIN administrativo é escolhido por você; não é uma chave emitida pela Shopee. Ele protege o botão de conexão no app público. Com os três valores salvos, abra **Produtos → Conectar API de Afiliados Shopee**, informe o PIN e use **Conectar / testar API**. Esse teste é somente leitura. Se o portal da Shopee ainda mostrar que a conta não tem acesso ou só exibir o Guia de Usuário, inserir valores não concederá permissão: aguarde a liberação da Shopee. Enquanto isso, a importação continua usando leitura pública best-effort do HTML; novos produtos seguem inativos e sem aprovação.

## 2. GitHub Actions — publicação agendada

Abra o repositório `Lucas10-GIT/axadinhos-vippe-bot` e vá a **Settings → Secrets and variables → Actions**.

### Repository secrets

Para o agendamento no Telegram, configure:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Para incluir Pinterest nos disparos, configure também:

- `PINTEREST_ACCESS_TOKEN`
- `PINTEREST_BOARD_ID`

Os secrets de Telegram já usados pelo workflow podem continuar como estão. A Open API da Shopee não é necessária para o workflow publicar produtos já salvos no CSV. O GitHub Actions usa o `GITHUB_TOKEN` temporário interno do próprio run, com permissão de escrita limitada ao job; **não crie um PAT `GITHUB_TOKEN` adicional** para o workflow.

### Repository variables — travas separadas dos secrets

As variáveis abaixo não são tokens e não substituem os secrets:

- `AXADINHOS_AUTO_PUBLISH=true` habilita a publicação automática agendada no Telegram. Sem essa variável definida exatamente como `true`, o cron não publica.
- `AXADINHOS_PINTEREST_CROSSPOST_ENABLED=true` permite incluir Pinterest nos runs do workflow quando os dois secrets Pinterest acima também estiverem configurados. Sem essa variável, Pinterest permanece desligado nos disparos do GitHub Actions.

O workflow verifica ofertas a cada quatro horas e respeita um cooldown global mínimo de quatro horas. A ativação de `AXADINHOS_AUTO_PUBLISH` é uma decisão separada: antes de defini-la como `true`, revise todos os produtos marcados **Ativo** e **Aprovado para publicação**. A execução automática pode publicar um desses produtos assim que ele estiver elegível. O workflow manual também exige confirmação explícita em `confirm_publish`.

## 3. Ordem segura de ativação

1. Preencha os secrets do Streamlit e confira os indicadores de presença no app; isso não publica nada.
2. Se a Shopee já tiver liberado a Open API, adicione os três secrets Shopee e faça o teste de leitura. Caso contrário, deixe-os ausentes e use a importação HTML best-effort.
3. Para Pinterest, adicione os dois valores de Pinterest no destino desejado. Comece com publicação manual desativada (`pinterest_publish_enabled = false`) e com a variável agendada ausente.
4. Importe poucos links, revise nome, preço, imagem e link de afiliado; salve os produtos e aprove manualmente apenas os que estiverem corretos.
5. Se quiser testar Pinterest, habilite o segredo booleano do Streamlit e publique manualmente um produto revisado, sabendo que o Pin ficará público no board configurado.
6. Só depois de validar os canais e revisar a base, decida se configura as variáveis de Actions para publicação agendada. Telegram automático e inclusão do Pinterest são controles independentes.

## 4. Diagnóstico rápido

- **Telegram manual bloqueado:** confira `github_token`, `telegram_bot_token` e `telegram_chat_id` no Streamlit.
- **Pinterest manual indisponível:** confira `pinterest_access_token`, `pinterest_board_id` e `pinterest_publish_enabled = true`; o produto também precisa estar ativo e aprovado.
- **Pinterest não aparece no workflow:** confira os dois secrets Pinterest e `AXADINHOS_PINTEREST_CROSSPOST_ENABLED=true` em Actions Variables.
- **Cron não publica:** confira `AXADINHOS_AUTO_PUBLISH=true`, o estado de aprovação, os campos obrigatórios do produto e o cooldown de quatro horas.
- **Shopee Affiliate API recusada:** confirme primeiro se a conta recebeu acesso; secrets não contornam a autorização da Shopee.
- **Falha de canal com estado `revisar`:** confira manualmente o destino antes de mudar o status para `pendente`, para não duplicar uma publicação que talvez tenha sido entregue.
