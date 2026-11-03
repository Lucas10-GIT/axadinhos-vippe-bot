# Configuração de Secrets — Axadinhos Vippe Bot

As credenciais ficam fora do repositório. **Não cole tokens no chat, na planilha, no código ou em commits.** Streamlit Cloud e GitHub Actions usam armazenamentos separados; configurar um Secret em um deles não o configura no outro. O único canal de publicação desta versão é o Pinterest.

## 1. Streamlit Cloud — importação e publicação manual

No Streamlit Cloud, abra **Manage app → Settings → Secrets**, adicione as entradas necessárias, salve e recarregue o app. O painel mostra apenas se cada valor está presente, nunca o valor.

### Pinterest e acesso ao CSV do GitHub

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
```

Use um token do GitHub restrito ao repositório, com permissão **Contents: read and write** para ler e gravar `data/products.csv`. O token Pinterest precisa permitir criar Pins no board indicado. O Board ID deve ser numérico.

Mantenha `pinterest_publish_enabled=false` durante a configuração: assim, o botão de publicação manual permanece bloqueado. Altere para `true` apenas quando estiver pronto para criar um Pin público real. Não existe modo de teste sem publicação nesse botão. Cada Pin usa a URL original de afiliado da Shopee como destino e inclui aviso de afiliado. O produto também precisa estar ativo, aprovado, pronto e com nome, preço, imagem pública HTTPS e link válido.

### Shopee Affiliate Open API (opcional)

Só adicione estas três entradas depois que a Shopee conceder acesso à Open API e fornecer App ID e App Secret:

```toml
shopee_affiliate_app_id = "APP_ID_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_secret = "APP_SECRET_FORNECIDO_PELA_SHOPEE"
shopee_affiliate_admin_pin = "ESCOLHA_UM_PIN_PRIVADO_E_FORTE"
```

O PIN administrativo é escolhido por você; não é uma chave emitida pela Shopee. Ele protege o botão de conexão no app público. Com os três valores salvos, abra **Produtos → Conectar API de Afiliados Shopee**, informe o PIN e use **Conectar / testar API**. Esse teste é somente leitura. Se a Shopee ainda não concedeu acesso, adicionar secrets não libera a API: use a importação pública best-effort enquanto aguarda. Produtos importados continuam inativos e sem aprovação.

## 2. GitHub Actions — publicação agendada

No repositório `Lucas10-GIT/axadinhos-vippe-bot`, abra **Settings → Secrets and variables → Actions**.

### Repository secrets

Configure:

- `PINTEREST_ACCESS_TOKEN`
- `PINTEREST_BOARD_ID`

O GitHub Actions usa o `GITHUB_TOKEN` temporário do próprio run para gravar o estado no CSV, com permissão limitada ao job. Não crie um PAT adicional com o nome `GITHUB_TOKEN`. A API de afiliados Shopee não é necessária para publicar produtos que já estão na tabela.

### Repository variables

A recorrência é bloqueada por padrão. Para habilitar a publicação agendada, configure **ambas** estas variáveis com o valor exato `true`:

- `AXADINHOS_AUTO_PUBLISH` — trava geral;
- `AXADINHOS_PINTEREST_AUTO_PUBLISH` — opt-in específico do Pinterest.

O workflow verifica a base a cada quatro horas e publica no máximo um Pin por execução, respeitando cooldown global mínimo de quatro horas. Antes de habilitar as variáveis, revise todos os produtos marcados **Ativo** e **Aprovado para publicação**. Produtos elegíveis podem ser publicados automaticamente.

Uma execução manual pelo formulário do Actions é avulsa e exige marcar `confirm_publish`. Ela também precisa dos dois repository secrets do Pinterest e de um produto elegível.

## 3. Ordem segura de ativação

1. Configure `github_token` e os valores Pinterest no Streamlit, mantendo `pinterest_publish_enabled=false`; confira apenas os indicadores de presença.
2. Se a Shopee tiver concedido acesso à Open API, configure os três Secrets Shopee e valide a conexão de leitura. Caso contrário, deixe-os ausentes e use a importação tradicional.
3. Importe poucos links e confira cuidadosamente nome, preço, foto e link de afiliado. Salve os produtos; novos itens permanecem inativos e sem aprovação.
4. Ative e aprove manualmente apenas produtos revisados. Confira se a imagem é pública e adequada ao Pinterest.
5. Para uma publicação manual, mude `pinterest_publish_enabled` para `true` e clique sabendo que o Pin ficará público no board configurado.
6. Habilite as duas variáveis do GitHub Actions somente se também quiser publicação agendada. A execução manual do workflow requer sua confirmação específica.

## 4. Diagnóstico rápido

- **Botão manual indisponível:** confira `github_token`, `pinterest_access_token`, `pinterest_board_id` e `pinterest_publish_enabled=true` no Streamlit; verifique também se o produto está ativo, aprovado, pronto e vencido.
- **Pin bloqueado antes do envio:** confira nome, preço, link HTTPS válido da Shopee, imagem pública HTTPS e Board ID numérico.
- **Workflow agendado não publica:** confira os dois Secrets Pinterest, `AXADINHOS_AUTO_PUBLISH=true`, `AXADINHOS_PINTEREST_AUTO_PUBLISH=true`, aprovação do produto e cooldown de quatro horas.
- **Workflow manual não inicia a publicação:** confirme `confirm_publish` no formulário do Actions e confira os Secrets.
- **Shopee Affiliate API recusada:** confirme primeiro se a conta recebeu acesso; Secrets não contornam a autorização da Shopee.
- **Produto em `revisar`:** confira manualmente o board antes de reabilitar o produto, para evitar Pin duplicado após uma resposta ambígua.
