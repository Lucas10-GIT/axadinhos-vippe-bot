# Axadinhos Vippe Bot

Aplicativo Streamlit para organizar produtos Shopee, revisar ofertas e publicar no Telegram. A base oficial fica em `data/products.csv` no GitHub.

## Importar vários links Shopee

Na aba **Produtos**, cole até 20 links HTTPS da Shopee por lote, separados por linha, espaço ou vírgula. O app tenta obter título, preço e foto dos metadados públicos da página. A Shopee pode omitir esses metadados ou bloquear a leitura; nesse caso, o link entra na tabela, mas os campos indisponíveis ficam vazios para preenchimento manual.

O link original é mantido para preservar o rastreamento de afiliado. Links que não sejam HTTPS da Shopee e duplicatas são ignorados. A importação apenas adiciona rascunhos à tabela local da sessão: clique em **Salvar produtos** para persistir no GitHub. Todo produto novo começa **inativo** e **sem aprovação**. Revise nome, preço, foto e destino Shopee; só então marque **Ativo** e **Aprovado para publicação**.

## Regras de publicação

- O publicador escolhe no máximo uma oferta elegível por execução.
- Exige produto **Ativo**, **Aprovado para publicação**, com nome, preço e link HTTPS Shopee válido, vencido pela frequência individual e fora de estado de revisão.
- Existe também um intervalo global mínimo de quatro horas entre publicações registradas, para que atrasos do agendador não aproximem os disparos.
- O produto elegível de maior score é selecionado. O score considera pedidos, comissão estimada e conversão de cliques.
- Frequência individual após um envio: produto com 2 ou mais pedidos, 2 dias; produto com 10 ou mais cliques, 4 dias; demais, 3 dias.
- Cada anúncio informa que o link é de afiliado e que preço e disponibilidade podem mudar na Shopee.
- Antes do envio, o publicador grava `status_publicacao=enviando` no CSV. Se o resultado do Telegram for ambíguo ou a gravação final falhar, o produto permanece bloqueado para revisão, evitando repetição automática.

Cliques, pedidos e comissão estimada são preenchidos manualmente; o bot não importa métricas da Shopee. Na aba **Produtos**, a tabela pode ser baixada em CSV, Excel (`.xlsx`), TSV ou JSON.

## Agendamento e ativação

O workflow `.github/workflows/publish-offers.yml` verifica ofertas a cada quatro horas (`0 */4 * * *`, UTC). O GitHub Actions pode iniciar uma execução agendada com atraso; o publicador ainda respeita o intervalo global mínimo de quatro horas e envia no máximo uma oferta por execução. Havendo produtos elegíveis em todas as janelas, isso pode resultar em até seis ofertas por dia.

A publicação recorrente fica **desativada por padrão**: o job agendado só pode publicar se a Actions Variable `AXADINHOS_AUTO_PUBLISH` estiver definida como `true`. Enquanto ela estiver ausente ou diferente de `true`, os disparos agendados não publicam. O workflow manual também exige marcar `confirm_publish` no formulário de Actions.

Antes de habilitar `AXADINHOS_AUTO_PUBLISH`, revise todos os produtos ativos e aprovados: qualquer item elegível pode ser selecionado assim que uma execução for habilitada. Configure a variável conscientemente em **Settings → Secrets and variables → Actions → Variables → New repository variable**, com nome `AXADINHOS_AUTO_PUBLISH` e valor `true`. Não coloque tokens no CSV, no código, em commits ou em logs.

O workflow usa o `GITHUB_TOKEN` temporário do próprio run, com permissão de gravação apenas no job de publicação, e os secrets `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`. O cross-post agendado no Pinterest é opcional e exige também `PINTEREST_ACCESS_TOKEN`, `PINTEREST_BOARD_ID` e a variável independente `AXADINHOS_PINTEREST_CROSSPOST_ENABLED=true`. O código redige tokens antes de imprimir mensagens de erro.

## Configuração de credenciais

Consulte o [guia de configuração de secrets](CONFIGURAR-SECRETS.md) para obter os nomes exatos de cada valor no Streamlit Cloud e no GitHub Actions, saber quais são opcionais e ativar os canais com segurança.

Para publicar manualmente no Telegram, em **Streamlit Cloud → App settings → Secrets**, configure:

```toml
github_token = "TOKEN_COM_ACESSO_AO_CONTEUDO_DO_REPOSITORIO"
telegram_bot_token = "TOKEN_DO_BOT"
telegram_chat_id = "ID_DO_CHAT_OU_CANAL"
```

O `github_token` precisa ler e gravar `data/products.csv`. O bot do Telegram precisa ter permissão para publicar no canal. Para publicar no Pinterest ou consultar a Shopee Affiliate Open API, consulte o guia: são credenciais opcionais, ficam em campos separados e a API da Shopee depende de acesso concedido pela própria Shopee.

## Testes

Os testes locais não precisam de tokens e não fazem chamadas reais:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```

O workflow `Tests` roda em pushes, pull requests e manualmente; ele não publica no Telegram. O smoke test técnico de uma mensagem continua separado em `.github/workflows/telegram-smoke-test.yml`.
