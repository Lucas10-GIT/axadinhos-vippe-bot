# Axadinhos Vippe Bot

Aplicativo Streamlit para importar e revisar ofertas da Shopee e publicar Pins linkados no Pinterest. A base oficial fica em `data/products.csv` no GitHub. O Pinterest é o único canal de publicação incluído nesta versão.

## Importar links Shopee em lote

Na aba **Produtos**, cole até 20 links HTTPS da Shopee por lote, separados por linha, espaço ou vírgula. O importador tenta obter nome, preço, foto e categoria pela API de afiliados quando as credenciais autorizadas estão disponíveis; caso contrário, usa leitura best-effort de metadados públicos, HTML e JSON embutido. A Shopee pode omitir os dados ou bloquear a leitura, então revise e complete os campos manualmente.

O link original é preservado para manter o rastreamento de afiliado. Links fora dos domínios HTTPS aceitos e duplicatas são ignorados. A importação adiciona os produtos à sessão do Streamlit; **Salvar produtos** grava a tabela no GitHub. Todo item novo começa **inativo** e **sem aprovação**. Revise nome, preço, imagem e destino antes de ativá-lo e aprová-lo.

O acesso à Shopee Affiliate Open API depende de concessão da própria Shopee. Sem acesso, a importação tradicional continua disponível e não tenta contornar a autorização.

## Publicação Pinterest

Cada publicação cria um Pin de imagem pela API oficial v5, com:

- a URL original de afiliado da Shopee no campo de destino do Pin, sem substituição;
- aviso de que o link é de afiliado e pode gerar comissão sem custo adicional;
- produto ativo, aprovado manualmente e com nome, preço, imagem pública HTTPS e link Shopee válidos.

O app não aprova produtos automaticamente. O botão do Streamlit cria um Pin público real, não um rascunho ou teste. Ele permanece desativado até `pinterest_publish_enabled=true` e até que os Secrets estejam configurados.

O publicador escolhe no máximo uma oferta elegível por execução. Existe um intervalo global mínimo de quatro horas entre publicações registradas, além da frequência por produto: 2 dias para produtos com pelo menos 2 pedidos, 4 dias para produtos com 10 ou mais cliques e 3 dias nos demais casos. Quando mais de um item estiver elegível, o maior score, baseado em pedidos, comissão estimada e conversão de cliques, tem prioridade.

Antes de chamar o Pinterest, o publicador registra `status_publicacao=enviando` no CSV. Se houver falha ambígua, o produto fica em `revisar` e não é reenviado automaticamente. Confira manualmente o board antes de alterar esse estado.

Cliques, pedidos e comissão estimada são preenchidos manualmente; o bot não importa métricas da Shopee. A aba **Produtos** permite baixar a tabela em CSV, Excel (`.xlsx`), TSV ou JSON.

## Agendamento no GitHub Actions

O workflow `.github/workflows/publish-offers.yml` verifica produtos a cada quatro horas (`0 */4 * * *`, UTC) e publica no máximo um Pin por execução. A recorrência fica bloqueada por padrão e exige as duas variáveis do repositório:

- `AXADINHOS_AUTO_PUBLISH=true` — trava geral da automação;
- `AXADINHOS_PINTEREST_AUTO_PUBLISH=true` — autorização específica para publicação agendada no Pinterest.

Sem ambas as variáveis, o cron não publica. A execução manual do workflow é separada: exige que o usuário marque `confirm_publish` no formulário do GitHub Actions. Antes de ativar o cron, revise todos os produtos ativos e aprovados, pois qualquer produto elegível pode ser escolhido.

O workflow usa o `GITHUB_TOKEN` temporário do run, com permissão de gravação restrita ao job de publicação, e os secrets `PINTEREST_ACCESS_TOKEN` e `PINTEREST_BOARD_ID`. Tokens nunca são registrados no CSV ou nos logs.

## Configuração

Consulte o [guia de Secrets](CONFIGURAR-SECRETS.md) para configurar o Streamlit Cloud, o GitHub Actions e, quando disponível, a Shopee Affiliate Open API. Os armazenamentos do Streamlit e do GitHub são separados.

Para publicação manual pelo Streamlit, os Secrets têm estes nomes:

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
```

Mantenha `pinterest_publish_enabled=false` enquanto configura. Altere-o para `true` somente quando estiver pronto para publicar Pins reais.

## Testes locais

Os testes não precisam de tokens e usam sessões falsas; não fazem chamadas reais ao GitHub, à Shopee ou ao Pinterest.

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```
