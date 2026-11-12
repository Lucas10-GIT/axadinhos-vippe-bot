# Configurar Secrets — Axadinhos Vippe Bot

As credenciais ficam fora do repositório. Não cole tokens no chat, na planilha, no código ou em commits. Streamlit Cloud e GitHub Actions são armazenamentos separados: configurar um não configura o outro.

Amazon Associados e eBay Partner Network não exigem Secrets para importar links que você já gerou nos portais oficiais. O app não chama APIs de afiliados, não raspa páginas e não tenta criar/reconstruir tracking links. Amazon direto precisa de `tag` (ou link oficial `amzn.to`); eBay direto precisa do `campid` de 10 dígitos EPN (ou encurtador oficial `ebay.us`).

## 1. Streamlit Cloud

No Streamlit Cloud, abra **Manage app → Settings → Secrets**, adicione as entradas necessárias, salve e recarregue o app. A interface mostra apenas se a credencial está presente, nunca seu valor.

### GitHub e Pinterest

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
```

`github_token` dá acesso ao CSV do catálogo. O opt-in `pinterest_publish_enabled` começa desativado. A publicação cria um Pin público real; só ative após conferir credenciais, revisar o produto, aprovar manualmente e confirmar a autorização de uso da imagem. Um Pin exige título, link afiliado válido, imagem HTTPS autorizada e Board ID numérico. Preço estático Amazon é omitido.

### Dados Amazon e eBay

Cole apenas links de afiliado criados no portal do programa. O importador os preserva integralmente. Complete nome, categoria e imagem manualmente; os produtos começam inativos, sem aprovação e sem autorização de imagem.

Para Amazon, não copie preço/imagem de páginas ou fontes raspadas. A exibição de preço/disponibilidade e o uso de conteúdo de catálogo requerem a fonte/API autorizada pelo programa e conformidade com sua licença. A Creators API documenta requisitos próprios de elegibilidade, cadastro e credenciais. Para eBay, não edite os parâmetros EPN. A EPN prevê aprovação escrita para conteúdo promocional criado pelo publisher; marque a aprovação correspondente na tabela somente após recebê-la. O rascunho e o handoff WhatsApp de eBay exigem também aprovação escrita da EPN para mensageria.

### Webhook opcional de rascunhos WhatsApp

Configure somente se você controla um endpoint HTTPS e deseja encaminhar um rascunho manualmente. Deixe a opção em `false` durante a preparação. O endpoint não deve enviar mensagens ao receber o payload: ele precisa tratar `action=create_draft` e `send=false` como uma solicitação para criar ou atualizar um rascunho.

```toml
whatsapp_draft_webhook_enabled = false
whatsapp_draft_webhook_url = "https://SEU-ENDPOINT-HTTPS/webhook/SEU-ID"
whatsapp_draft_webhook_secret = "CHAVE_ALEATORIA_DE_PELO_MENOS_32_CARACTERES"
whatsapp_draft_webhook_admin_pin = "PIN_ALEATORIO_PRIVADO_DE_PELO_MENOS_16_CARACTERES"
```

A URL não aceita query string, credenciais embutidas, redirecionamento, porta não padrão ou destinos locais. O app envia o texto e dados do produto aprovado, sem telefone ou lista de contatos, e assina o corpo com HMAC-SHA256. O endpoint deve validar `X-Axadinhos-Timestamp`, `X-Axadinhos-Signature` e `Idempotency-Key`; não há repetição automática. Use um PIN aleatório privado de pelo menos 16 caracteres, diferente da chave HMAC; ele é exigido no app público em campo mascarado. Uma resposta HTTP 2xx confirma apenas que o endpoint aceitou o handoff, não que uma mensagem foi enviada ou entregue. A ação está disponível somente como botão manual para produto ativo e aprovado, com PIN e confirmação explícita. Ela não é usada pelo GitHub Actions. Para eBay, o handoff só aparece se a coluna de aprovação de mensageria EPN estiver marcada.

Para validar a assinatura, calcule HMAC-SHA256 da concatenação `timestamp + "." + corpo HTTP bruto` usando a chave compartilhada e compare com o valor hexadecimal de `X-Axadinhos-Signature` depois do prefixo `sha256=`. Rejeite timestamps fora de uma janela curta (por exemplo, 5 minutos) e deduplique `Idempotency-Key`. O corpo inclui `event=axadinhos.whatsapp.draft.created`, `action=create_draft`, `send=false`, o produto e o texto do rascunho; não inclui destinatário. O receptor deve recusar qualquer payload diferente desse contrato e nunca transformar esse evento em comando de envio.

Este webhook não é o webhook de eventos da Meta e não se conecta à WhatsApp Cloud API. Um envio futuro exigirá integração oficial separada, número empresarial elegível, consentimento prévio por categoria, opt-out e respeito aos templates/janelas aplicáveis. Não conecte o endpoint a disparos para contatos sem opt-in. Consulte [requisitos de opt-in](https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in), [webhooks oficiais da Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview) e [envio de mensagens pela Cloud API](https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages).

## 2. GitHub Actions

No repositório `Lucas10-GIT/axadinhos-vippe-bot`, abra **Settings → Secrets and variables → Actions**.

### Repository secrets

Configure para publicação de Pins:

- `PINTEREST_ACCESS_TOKEN`
- `PINTEREST_BOARD_ID`

O workflow usa o `GITHUB_TOKEN` temporário do próprio run para gravar o estado no CSV, com permissão limitada ao job. Não crie um PAT adicional chamado `GITHUB_TOKEN`.

### Repository variables para cron

O cron verifica a fila a cada quatro horas, mas fica bloqueado por padrão. A ativação agendada requer as duas variáveis abaixo com valor exato `true`:

- `AXADINHOS_AUTO_PUBLISH` — trava geral;
- `AXADINHOS_PINTEREST_AUTO_PUBLISH` — opt-in agendado do Pinterest.

Um Secret configurado não liga o cron. O workflow processa no máximo uma oferta elegível por execução e aplica cooldown global. Revise todos os produtos **Ativos** e **Aprovados para publicação** antes de habilitar os opt-ins. WhatsApp, Instagram e TikTok não são alvos desse workflow.

Uma execução avulsa pelo formulário do Actions exige marcar `confirm_publish` e selecionar `publish_pinterest`. Ela pode criar conteúdo público real.

## 3. Ordem segura de ativação

1. Configure `github_token` no Streamlit e confira apenas o indicador de presença.
2. Configure os Secrets Pinterest necessários e mantenha `pinterest_publish_enabled=false`.
3. Importe poucos links Amazon/EPN já gerados nos portais oficiais. Preencha os metadados manualmente; confira que o link tem tag/campid e não altere seus parâmetros.
4. Confirme que a imagem/arte pode ser usada no Pinterest. Para eBay, obtenha a aprovação escrita EPN apropriada antes de marcar os campos de promoção ou mensageria.
5. Salve os produtos; novos itens permanecem inativos e não aprovados. Prepare os formatos em **Anúncios** e verifique consentimento antes de compartilhar no WhatsApp.
6. Ative e aprove manualmente somente produtos revisados.
7. Habilite `pinterest_publish_enabled=true` apenas quando estiver pronto para um Pin real; o botão manual publica exclusivamente no Pinterest.
8. Configure variáveis do Actions somente se desejar o cron automático de Pinterest.

## 4. Diagnóstico rápido

- **Link rejeitado:** confira HTTPS, domínio permitido e rastreamento (`tag` Amazon ou `campid` EPN de 10 dígitos). Encurtadores admitidos: `amzn.to` e `ebay.us`.
- **Rascunho Amazon sem preço:** comportamento esperado; o app não usa preço estático sem fonte/API licenciada.
- **Conteúdo ou Pin eBay bloqueado:** confira a aprovação escrita EPN para promoção/conteúdo; para WhatsApp, confira também aprovação de mensageria.
- **Pin bloqueado:** confira nome, link afiliado, URL pública HTTPS da imagem, confirmação de direito de uso, Board ID e, para eBay, aprovação de promoção.
- **Webhook WhatsApp desativado/incompleto:** confira `whatsapp_draft_webhook_enabled`, URL HTTPS, segredo HMAC e PIN administrativo nos Streamlit Secrets. O botão não envia mensagens e só aparece habilitado para produto ativo e aprovado.
- **Webhook aceitou, mas não há mensagem:** comportamento esperado; o endpoint recebe somente um rascunho (`send=false`). Qualquer envio real deve ser implementado à parte pela WhatsApp Business Platform com opt-in e opt-out.
- **Pinterest indisponível:** confira `github_token`, `pinterest_publish_enabled=true`, token e Board ID; o produto também precisa estar ativo, aprovado, elegível e fora do cooldown.
- **Cron não publica:** confira as duas variáveis de ativação, Secrets, aprovação do produto e cooldown.
- **Falha ambígua ou estado `revisar`:** confira no Pinterest se o Pin foi criado antes de alterar o estado; o sistema não tenta novamente automaticamente.
