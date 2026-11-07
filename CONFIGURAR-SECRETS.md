# Configurar Secrets — Axadinhos Vippe Bot

As credenciais ficam fora do repositório. Não cole tokens no chat, na planilha, no código ou em commits. Streamlit Cloud e GitHub Actions são armazenamentos separados: configurar um não configura o outro.

WhatsApp, Instagram e TikTok são somente geradores de conteúdo copiável neste projeto. Não precisam de tokens e não enviam nem publicam conteúdo por API. O app também não armazena contatos ou consentimentos.

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
5. Prepare conteúdo copiável em **Anúncios**. Verifique consentimento antes de compartilhar no WhatsApp; confira o destino de bio no Instagram; no TikTok, use a opção de divulgação comercial do próprio app e não inclua o link no vídeo.
6. Ative e aprove manualmente somente produtos revisados.
7. Habilite `pinterest_publish_enabled=true` apenas quando estiver pronto para um Pin real. O botão manual publica exclusivamente no Pinterest.
8. Configure variáveis do Actions somente se desejar o cron automático de Pinterest.

## 4. Diagnóstico rápido

- **Texto manual incompleto:** confira nome, preço, URL HTTPS Shopee e chamada opcional na aba Produtos.
- **Pinterest indisponível:** confira `github_token`, `pinterest_publish_enabled=true`, token e Board ID; o produto também precisa estar ativo, aprovado, elegível e fora do cooldown.
- **Pin bloqueado na pré-validação:** confira nome, preço, URL Shopee, imagem pública HTTPS e Board ID numérico.
- **Cron não publica:** confira as duas variáveis de ativação, Secrets, aprovação do produto e cooldown.
- **Execução avulsa não publica:** marque `confirm_publish` e `publish_pinterest`; confira os Secrets selecionados.
- **Estado `revisar` ou falha ambígua:** confira no Pinterest se o Pin foi criado antes de alterar o estado para pendente. O sistema não tenta novamente automaticamente.
- **API Shopee recusada:** confirme primeiro se a conta recebeu acesso; Secrets não contornam a autorização da Shopee.
