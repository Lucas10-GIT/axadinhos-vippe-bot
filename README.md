# Axadinhos Vippe Bot

Aplicativo Streamlit para manter uma lista de produtos, gerar textos de divulgação e publicar ofertas aprovadas no Telegram. A base vive em `data/products.csv` no GitHub.

## Estado da automação

- O publicador lê o CSV, valida cada produto e escolhe no máximo uma oferta elegível por execução.
- Um produto precisa estar **Ativo** e com **Aprovado para publicação** marcado, ter nome, preço e link HTTPS da Shopee, estar vencido pela frequência e não estar em estado de revisão.
- O produto de maior score entre os elegíveis é selecionado. O score usa pedidos, comissão estimada e conversão de cliques.
- Frequência inicial após envio: produto com 2 ou mais pedidos, 2 dias; produto com 10 ou mais cliques, 4 dias; demais, 3 dias.
- Cada anúncio informa que o link é de afiliado e que preço/disponibilidade podem mudar na Shopee.
- Antes de chamar o Telegram, o publicador grava `status_publicacao=enviando` no CSV. Se o envio tiver resultado ambíguo ou a gravação final falhar, a oferta fica bloqueada para evitar repetição automática; verifique o canal antes de mudar o estado para `pronto`.

Cliques, pedidos e comissão estimada são informados manualmente no CSV; o bot não importa métricas da Shopee. O workflow automático envia no máximo uma oferta por dia e as publicações usam as notificações normais do Telegram.

O CSV está inicialmente vazio (apenas o cabeçalho). Cadastre ofertas reais no aplicativo e revise nome, preço, link, imagem e métricas. A aprovação é individual; itens novos não são publicados até marcar **Aprovado para publicação**.

## Agendamento e ativação

O workflow `.github/workflows/publish-offers.yml` faz uma varredura diária às **13:00 no horário de Brasília (UTC-3)** e publica no máximo uma oferta vencida. O agendamento fica **desativado por padrão**: só publica se a Actions Variable `AXADINHOS_AUTO_PUBLISH` estiver definida como `true`. Enquanto a variável estiver ausente ou diferente de `true`, os disparos agendados não executam o job de publicação.

A execução manual também exige marcar `confirm_publish` no formulário de Actions. Não acione essa opção até haver produtos reais revisados no CSV e o destino Telegram confirmado. Para ativar a rotina recorrente, configure conscientemente a variável de repositório em **Settings → Secrets and variables → Actions → Variables → New repository variable**, com nome `AXADINHOS_AUTO_PUBLISH` e valor `true`. Não habilite a variável antes de cadastrar e revisar ao menos uma oferta aprovada.

O workflow usa o `GITHUB_TOKEN` de curta duração do próprio run com permissão de gravação apenas no job de publicação e os secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`. Não coloque tokens no CSV, no código, em commits ou em logs. Erros do publicador redigem os tokens antes de serem impressos.

## Configuração do Streamlit

Em **Streamlit Cloud → App settings → Secrets**, configure:

```toml
github_token = "TOKEN_COM_ACESSO_AO_CONTEUDO_DO_REPOSITORIO"
telegram_bot_token = "TOKEN_DO_BOT"
telegram_chat_id = "ID_DO_CHAT_OU_CANAL"
```

O `github_token` precisa ler e gravar `data/products.csv`. O bot do Telegram precisa ter permissão para publicar no canal. Não compartilhe os valores dos secrets.

## Testes

Os testes locais não precisam de tokens e não fazem chamadas reais:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

O workflow `Tests` também roda nos pushes/pull requests e não publica no Telegram. O smoke test técnico de uma única mensagem permanece separado em `.github/workflows/telegram-smoke-test.yml`.
