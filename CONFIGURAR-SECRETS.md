# Configurar Secrets — Axadinhos Vippe Bot

As credenciais ficam fora do repositório. Não cole tokens no chat, na planilha, no código ou em commits. Streamlit Cloud e GitHub Actions são armazenamentos separados: configurar um não configura o outro.

Instagram e TikTok são somente geradores de conteúdo copiável neste projeto e não têm conexão de API. WhatsApp também gera texto copiável; há um webhook opcional que só encaminha manualmente um rascunho aprovado a um endpoint seu. Ele vem desativado, não envia mensagens, não usa cron e não recebe contatos. O app não armazena listas de contatos ou registros de consentimento.

## 1. Streamlit Cloud

No Streamlit Cloud, abra **Manage app → Settings → Secrets**, adicione as entradas necessárias, salve e recarregue o app. A interface mostra apenas se a credencial está presente, nunca seu valor.

### GitHub e Pinterest

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
```

`github_token` dá acesso ao CSV do catálogo. O opt-in `pinterest_publish_enabled` começa desativado. A publicação cria um Pin público real; só ative depois de conferir as credenciais e revisar produtos aprovados. Um Pin exige link Shopee HTTPS original, nome, preço, imagem pública HTTPS e Board ID numérico.

### Shopee Affiliate Open API (opcional)

Adicione estes valores somente depois que a Shopee conceder acesso à Open API:

```toml
shopee_affiliate_app_id = "APP_ID_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_secret = "APP_SECRET_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_admin_pin = "ESCOLHA_UM_PIN_PRIVADO_E_FORTE"
```

O PIN é escolhido por você; não é emitido pela Shopee. Ele protege o botão de conexão no app público. O teste de conexão é somente leitura. Se a Shopee ainda não concedeu acesso, adicionar Secrets não libera a API; use a importação pública best-effort enquanto aguarda. Produtos importados continuam inativos e sem aprovação.

### Webhook opcional de rascunhos WhatsApp

Configure somente se você controla um endpoint HTTPS e deseja encaminhar um rascunho manualmente. Deixe a opção em `false` durante a preparação. O endpoint não deve enviar mensagens ao receber o payload: ele precisa tratar `action=create_draft` e `send=false` como uma solicitação para criar ou atualizar um rascunho.

```toml
whatsapp_draft_webhook_enabled = false
whatsapp_draft_webhook_url = "https://SEU-ENDPOINT-HTTPS/webhook/SEU-ID"
whatsapp_draft_webhook_secret = "CHAVE_ALEATORIA_DE_PELO_MENOS_32_CARACTERES"
whatsapp_draft_webhook_admin_pin = "PIN_ALEATORIO_PRIVADO_DE_PELO_MENOS_16_CARACTERES"
```

A URL não aceita query string, credenciais embutidas, redirecionamento, porta não padrão ou destinos locais. O app envia o texto e dados do produto aprovado, sem telefone ou lista de contatos, e assina o corpo com HMAC-SHA256. O endpoint deve validar `X-Axadinhos-Timestamp`, `X-Axadinhos-Signature` e `Idempotency-Key`; não há repetição automática. Use um PIN aleatório privado de pelo menos 16 caracteres, diferente da chave HMAC; ele é exigido no app público em campo mascarado. Uma resposta HTTP 2xx confirma apenas que o endpoint aceitou o handoff, não que uma mensagem foi enviada ou entregue. A ação está disponível somente como botão manual para produto ativo e aprovado, com PIN e confirmação explícita. Ela não é usada pelo GitHub Actions.

Para validar a assinatura, calcule HMAC-SHA256 da concatenação `timestamp + "." + corpo HTTP bruto` usando a chave compartilhada e compare com o valor hexadecimal de `X-Axadinhos-Signature` depois do prefixo `sha256=`. Rejeite timestamps fora de uma janela curta (por exemplo, 5 minutos) e deduplique `Idempotency-Key`. O corpo inclui `event=axadinhos.whatsapp.draft.created`, `action=create_draft`, `send=false`, o produto e o texto do rascunho; não inclui destinatário. O receptor deve recusar qualquer payload diferente desse contrato e nunca transformar esse evento em comando de envio.

Este webhook não é o webhook de eventos da Meta e não se conecta à WhatsApp Cloud API. Um envio futuro exigirá integração oficial separada, número empresarial elegível, consentimento prévio por categoria, opt-out e respeito aos templates/janelas aplicáveis. Não conecte o endpoint a disparos para contatos sem opt-in. Consulte [requisitos de opt-in](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in), [webhooks oficiais da Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview) e [envio de mensagens pela Cloud API](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages).

## 2. GitHub Actions

No repositório `Lucas10-GIT/axadinhos-vippe-bot`, abra **Settings → Secrets and variables → Actions**.

### Repository secrets

Configure para publicação de Pins:

- `PINTEREST_ACCESS_TOKEN`
- `PINTEREST_BOARD_ID`

O workflow usa o `GITHUB_TOKEN` temporário do próprio run para gravar o estado no CSV, com permissão limitada ao job. Não crie um PAT adicional chamado `GITHUB_TOKEN`. A API de afiliados Shopee não é necessária para publicar produtos já importados.

### Repository variables para cron

O cron verifica a fila a cada quatro horas, mas fica bloqueado por padrão. A ativação agendada requer as duas variáveis abaixo com valor exato `true`:

- `AXADINHOS_AUTO_PUBLISH` — trava geral;
- `AXADINHOS_PINTEREST_AUTO_PUBLISH` — opt-in agendado do Pinterest.

Um Secret configurado não liga o cron. O workflow processa no máximo uma oferta elegível por execução e aplica cooldown global. Revise todos os produtos **Ativos** e **Aprovados para publicação** antes de habilitar os opt-ins. WhatsApp, Instagram e TikTok não são alvos desse workflow.

Uma execução avulsa pelo formulário do Actions exige marcar `confirm_publish` e selecionar `publish_pinterest`. Ela pode criar conteúdo público real.

## 3. Ordem segura de ativação

1. Configure `github_token` no Streamlit e confira apenas o indicador de presença.
2. Configure os Secrets Pinterest necessários e mantenha `pinterest_publish_enabled=false`.
3. Se a Shopee concedeu acesso à Open API, configure os três Secrets Shopee e valide a conexão de leitura; caso contrário, deixe-os ausentes e use a importação tradicional.
4. Importe poucos links e confira nome, preço, imagem e link afiliado. Salve os produtos; novos itens permanecem inativos, sem aprovação e pendentes no Pinterest.
5. Prepare os formatos otimizados em **Anúncios**. Verifique consentimento antes de compartilhar no WhatsApp; atualize manualmente o link da bio no Instagram; no TikTok, use a opção de divulgação comercial do próprio app e coloque a URL somente em uma superfície permitida.
6. Ative e aprove manualmente somente produtos revisados.
7. Habilite `pinterest_publish_enabled=true` apenas quando estiver pronto para um Pin real. O botão manual publica exclusivamente no Pinterest.
8. Configure variáveis do Actions somente se desejar o cron automático de Pinterest.

## 4. Diagnóstico rápido

- **Texto manual incompleto:** confira nome, preço, URL HTTPS Shopee e chamada opcional na aba Produtos.
- **Webhook WhatsApp desativado/incompleto:** confira `whatsapp_draft_webhook_enabled`, URL HTTPS, segredo HMAC e PIN administrativo nos Streamlit Secrets. O botão não envia mensagens e só aparece habilitado para produto ativo e aprovado.
- **Webhook aceitou, mas não há mensagem:** comportamento esperado; o endpoint recebe somente um rascunho (`send=false`). Qualquer envio real deve ser implementado à parte pela WhatsApp Business Platform com opt-in e opt-out.
- **Pinterest indisponível:** confira `github_token`, `pinterest_publish_enabled=true`, token e Board ID; o produto também precisa estar ativo, aprovado, elegível e fora do cooldown.
- **Pin bloqueado na pré-validação:** confira nome, preço, URL Shopee, imagem pública HTTPS e Board ID numérico.
- **Cron não publica:** confira as duas variáveis de ativação, Secrets, aprovação do produto e cooldown.
- **Execução avulsa não publica:** marque `confirm_publish` e `publish_pinterest`; confira os Secrets selecionados.
- **Estado `revisar` ou falha ambígua:** confira no Pinterest se o Pin foi criado antes de alterar o estado para pendente. O sistema não tenta novamente automaticamente.
- **API Shopee recusada:** confirme primeiro se a conta recebeu acesso; Secrets não contornam a autorização da Shopee.
