# Axadinhos Vippe Bot

Aplicativo Streamlit para importar e revisar ofertas da Shopee, preparar conteúdo para Pinterest, WhatsApp, Instagram e TikTok, e criar Pins linkados quando explicitamente autorizado. A base fica em `data/products.csv` no GitHub. O webhook opcional de WhatsApp só encaminha rascunhos mediante ação manual; nenhuma API social envia ou publica automaticamente em WhatsApp, Instagram ou TikTok, e o app não armazena contatos.

## Importar links da Shopee

Na aba **Produtos**, cole até 20 links HTTPS da Shopee por lote. O importador tenta obter nome, preço, foto e categoria pela API de afiliados quando há credenciais autorizadas; sem elas, usa leitura best-effort de metadados públicos, HTML e JSON embutido. A Shopee pode omitir os dados ou bloquear a leitura, então revise e complete os campos manualmente.

O link de afiliado submetido é preservado. Links fora dos domínios HTTPS aceitos e duplicatas são ignorados. A importação adiciona itens à sessão do Streamlit; **Salvar produtos** grava a tabela no GitHub. Todo produto novo começa **inativo**, **sem aprovação** e com Pinterest em estado `pendente`. Revise nome, preço, imagem e destino antes de ativá-lo e aprová-lo.

O acesso à Shopee Affiliate Open API depende de concessão da própria Shopee. Sem acesso, a importação tradicional continua disponível e não tenta contornar a autorização.

## Preparar conteúdo para copiar

Na aba **Produtos**, o campo opcional **Chamada personalizada** aceita uma frase curta de até 180 caracteres. A aba **Anúncios** inclui também a composição para Pinterest — título, descrição e link de destino — igual ao payload do Pin publicado. WhatsApp recebe link no corpo; Instagram usa CTA para a bio e mostra a URL à parte; TikTok usa CTA para o perfil e mantém a URL separada. Hashtags são limitadas e derivadas da categoria.

No WhatsApp, o texto inclui o link original. Compartilhe somente com pessoas que aceitaram receber ofertas e respeite pedidos para parar. O app não importa listas de contatos nem automatiza envios.

Na legenda do Instagram, o CTA aponta para a bio e a URL afiliada original aparece em bloco separado para atualização manual do perfil. O texto não afirma que URLs na legenda do feed são clicáveis.

Para TikTok, a URL afiliada é mostrada em um campo separado e não é inserida no texto do vídeo/legenda. Use-a somente em uma superfície de link permitida. Antes de publicar, ative no próprio TikTok a divulgação de conteúdo comercial aplicável à oferta. O app não carrega nem publica fotos ou vídeos no TikTok.

Todos os rascunhos incluem disclosure de afiliado. Preço, estoque e disponibilidade podem mudar na Shopee; confira esses dados antes de publicar. No Pinterest, mantenha Pins originais e relevantes e evite publicações afiliadas repetitivas ou em grande volume.

Opcionalmente, é possível configurar um webhook HTTPS próprio para encaminhar manualmente o rascunho de WhatsApp de um produto ativo e aprovado. A opção vem desligada (`whatsapp_draft_webhook_enabled=false`), não roda no cron e exige PIN administrativo e confirmação no botão. O payload usa assinatura HMAC, chave de idempotência, `send=false` e não contém telefone ou lista de contatos. Isso é apenas um handoff para uma fila de rascunhos: não chama a WhatsApp Cloud API nem confirma envio ou entrega. Configure somente um endpoint que você controla e que respeite esses campos. Para envio real, seria necessária uma integração oficial separada, com opt-in, opt-out e demais requisitos da Meta.

## Publicação no Pinterest

A aba **Canais** pode criar um Pin público pela API oficial v5. O Pin leva a URL original de afiliado no campo de destino e contém a chamada, o aviso de afiliado e a ressalva de preço/disponibilidade. Exige produto ativo e aprovado manualmente, nome, preço, imagem pública HTTPS, board ID numérico, credenciais válidas e opt-in manual ativo.

O workflow do GitHub Actions pode publicar somente no Pinterest. O cron de quatro horas é bloqueado por padrão e requer tanto a trava geral quanto o opt-in específico do Pinterest. Nenhum conteúdo real é publicado pelo CI de testes.

O publicador reserva o produto no CSV antes do envio, registra o ID do Pin e não repete automaticamente um resultado ambíguo. Registros históricos `enviado` sem recibo de Pin são colocados em revisão para impedir duplicação até a confirmação humana.

## Painel

O **Painel** reúne tamanho do catálogo, produtos ativos e aprovados, pendências, comissão estimada, cliques, pedidos e Pins registrados. **Atenção agora** mostra revisão, envio em andamento, falta de aprovação/ativação, dados ausentes e fotos faltantes. O ranking usa a mesma pontuação do publicador; o gráfico por categoria aparece somente quando existem cliques ou pedidos registrados. A fila estimada do Pinterest é somente leitura e separada do cron.

## Configuração

Consulte [CONFIGURAR-SECRETS.md](CONFIGURAR-SECRETS.md) para configurar Streamlit Cloud, GitHub Actions, o webhook opcional de rascunhos e, quando disponível, a Shopee Affiliate Open API. Streamlit e GitHub usam armazenamentos separados. Instagram e TikTok não têm integração API neste projeto; o webhook de WhatsApp apenas encaminha rascunhos e não envia mensagens.

Exemplo de Secrets do Streamlit:

```toml
github_token = "TOKEN_COM_ACESSO_AO_REPOSITORIO"
pinterest_access_token = "TOKEN_OAUTH_DO_PINTEREST"
pinterest_board_id = "ID_NUMERICO_DO_BOARD"
pinterest_publish_enabled = false
whatsapp_draft_webhook_enabled = false
```

Mantenha `pinterest_publish_enabled=false` até estar pronto para publicar Pins reais. A presença de credenciais não ativa o cron.

## Testes locais

Os testes usam sessões falsas e não fazem chamadas reais ao GitHub, Pinterest, Shopee ou webhook. Também verificam a formatação por canal, a preservação do link afiliado, disclosures, assinatura HMAC e bloqueios de aprovação/ativação.

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
```
