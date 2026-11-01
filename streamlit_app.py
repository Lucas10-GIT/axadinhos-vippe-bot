import base64
import io

import pandas as pd
import requests
import streamlit as st
from product_importer import MAX_LINKS_PER_BATCH, import_product_links
from publish_telegram import ad as telegram_ad, parse_bool
from spreadsheet_exports import build_exports

OWNER = "Lucas10-GIT"
REPO = "axadinhos-vippe-bot"
BRANCH = "main"
DATA_PATH = "data/products.csv"

COLS = [
    "id", "nome", "preco", "link", "imagem_url", "categoria", "comissao",
    "ativo", "aprovado_publicacao", "status_publicacao", "frequencia_dias",
    "cliques", "pedidos", "comissao_estimada", "ultima_publicacao",
    "proxima_publicacao", "ultima_tentativa", "telegram_message_id",
]

st.set_page_config(page_title="Axadinhos Vippe", page_icon="👑", layout="wide")


def secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def clean(df):
    df = df.copy()
    defaults = {
        "id": "", "nome": "", "preco": "", "link": "", "imagem_url": "",
        "categoria": "", "comissao": 0, "ativo": True,
        "aprovado_publicacao": False, "status_publicacao": "pronto", "frequencia_dias": 3,
        "cliques": 0, "pedidos": 0, "comissao_estimada": 0,
        "ultima_publicacao": "", "proxima_publicacao": "",
        "ultima_tentativa": "", "telegram_message_id": "",
    }
    for column, default in defaults.items():
        if column not in df.columns:
            df[column] = default
    df = df[COLS]
    for column in ["id", "cliques", "pedidos"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0).astype(int)
    used_ids = set()
    next_id = max(1, int(df["id"].max()) + 1 if len(df) else 1)
    for index in df.index:
        product_id = int(df.at[index, "id"])
        if product_id <= 0 or product_id in used_ids:
            while next_id in used_ids:
                next_id += 1
            product_id = next_id
            next_id += 1
            df.at[index, "id"] = product_id
        used_ids.add(product_id)
    for column in ["comissao", "comissao_estimada", "frequencia_dias"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["frequencia_dias"] = df["frequencia_dias"].clip(1, 30).astype(int)
    df["ativo"] = df["ativo"].map(lambda value: parse_bool(value, default=True))
    df["aprovado_publicacao"] = df["aprovado_publicacao"].map(
        lambda value: parse_bool(value, default=False)
    )
    df["status_publicacao"] = df["status_publicacao"].fillna("pronto").astype(str).str.strip().str.casefold()
    return df


def gh_headers(token):
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def load():
    token = secret("github_token")
    if not token:
        return clean(pd.DataFrame(columns=COLS)), None, False
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}?ref={BRANCH}"
    response = requests.get(url, headers=gh_headers(token), timeout=20)
    if response.status_code == 404:
        return clean(pd.DataFrame(columns=COLS)), None, True
    response.raise_for_status()
    payload = response.json()
    raw = base64.b64decode(payload["content"]).decode("utf-8-sig")
    return clean(pd.read_csv(io.StringIO(raw))), payload["sha"], True


def save(df, sha):
    token = secret("github_token")
    if not token:
        return False, "Configure github_token nos Secrets."
    csv = clean(df).to_csv(index=False)
    content = base64.b64encode(csv.encode("utf-8")).decode("ascii")
    url = f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{DATA_PATH}"
    body = {"message": "Atualiza base de produtos", "content": content, "branch": BRANCH}
    if sha:
        body["sha"] = sha
    response = requests.put(url, headers=gh_headers(token), json=body, timeout=30)
    if not response.ok:
        return False, response.text
    return True, "Base salva."


def ad_preview(row):
    return telegram_ad(row)


def classify(row):
    clicks = int(row["cliques"])
    orders = int(row["pedidos"])
    if orders >= 2 or (orders >= 1 and clicks >= 20):
        return "🏆 Vencedor"
    if clicks >= 10:
        return "🟡 Em teste"
    return "⚪ Novo"


df, sha, cloud = load()

# Keep edits/import drafts between Streamlit reruns, but reload if the GitHub
# blob SHA changes so a scheduled publisher cannot be overwritten by a stale UI.
if "products_base_sha" not in st.session_state:
    st.session_state["products_base_sha"] = sha
    st.session_state["products_working_df"] = df.copy()
    st.session_state["products_editor_version"] = 0
elif st.session_state["products_base_sha"] != sha:
    st.session_state["products_base_sha"] = sha
    st.session_state["products_working_df"] = df.copy()
    st.session_state["products_editor_version"] += 1
    st.session_state["products_remote_refresh"] = True

st.title("👑 Axadinhos Vippe")
st.caption("Produtos, aprovação de ofertas, anúncios e desempenho")
if st.session_state.pop("products_remote_refresh", False):
    st.warning("A base mudou no GitHub. Recarregamos os dados mais recentes para evitar sobrescrever atualizações.")
if not cloud:
    st.warning("A visualização está disponível, mas github_token precisa estar configurado para salvar produtos.")

panel, products, ads, telegram = st.tabs(["📊 Painel", "📋 Produtos", "📢 Anúncios", "📲 Telegram"])

with panel:
    product_col, active_col, orders_col, commission_col = st.columns(4)
    product_col.metric("Produtos", len(df))
    active_col.metric("Ativos", int(df["ativo"].sum()) if len(df) else 0)
    orders_col.metric("Pedidos", int(df["pedidos"].sum()) if len(df) else 0)
    commission_col.metric(
        "Comissão", f"R$ {df['comissao_estimada'].sum():.2f}" if len(df) else "R$ 0,00"
    )
    if len(df):
        summary = df.copy()
        summary["status"] = summary.apply(classify, axis=1)
        summary["score"] = (
            summary["pedidos"] * 5
            + summary["comissao_estimada"]
            + (summary["pedidos"] / summary["cliques"].replace(0, 1)) * 100
        )
        st.dataframe(
            summary[["nome", "cliques", "pedidos", "comissao_estimada", "status", "score"]]
            .sort_values("score", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Adicione seu primeiro produto na aba Produtos.")

with products:
    st.subheader("📋 Planilha de produtos")
    st.caption(
        "Cole links HTTPS da Shopee em lote. O importador tenta ler título, preço e foto "
        "dos metadados públicos; se a Shopee bloquear ou omitir dados, revise e preencha a tabela. "
        "Links originais de afiliado são preservados."
    )
    st.info(
        "Importações novas entram como inativas e sem aprovação. Confira nome, preço, imagem e destino; "
        "ative e aprove cada produto somente depois da revisão. Máximo de "
        f"{MAX_LINKS_PER_BATCH} links por lote."
    )

    editor_key = f"products_editor_{st.session_state['products_editor_version']}"
    working_df = clean(st.session_state["products_working_df"])
    edited = st.data_editor(
        working_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=editor_key,
        column_config={
            "link": st.column_config.LinkColumn("Link Shopee"),
            "imagem_url": st.column_config.LinkColumn("Link da foto"),
            "ativo": st.column_config.CheckboxColumn("Ativo"),
            "aprovado_publicacao": st.column_config.CheckboxColumn("Aprovado para publicação"),
            "status_publicacao": st.column_config.SelectboxColumn(
                "Estado da publicação", options=["pronto", "enviando", "enviado", "revisar"]
            ),
            "frequencia_dias": st.column_config.NumberColumn("Dias", min_value=1, max_value=30),
            "comissao_estimada": st.column_config.NumberColumn("Comissão", format="R$ %.2f"),
        },
        disabled=["id", "ultima_publicacao", "proxima_publicacao", "ultima_tentativa", "telegram_message_id"],
    )
    edited = clean(edited)
    st.session_state["products_working_df"] = edited

    with st.form("bulk_import_form", clear_on_submit=True):
        pasted_links = st.text_area(
            "Links da Shopee (um por linha ou separados por espaço/vírgula)",
            height=150,
            placeholder="https://s.shopee.com.br/...\nhttps://shp.ee/...",
        )
        import_submitted = st.form_submit_button("🔎 Buscar dados e adicionar à tabela")

    if import_submitted:
        result = import_product_links(pasted_links, existing_links=edited["link"].tolist())
        if result["products"]:
            additions = pd.DataFrame(result["products"])
            combined = pd.concat([edited, additions], ignore_index=True)
            st.session_state["products_working_df"] = clean(combined)
            st.session_state["products_editor_version"] += 1
            st.session_state["bulk_import_report"] = {
                "added": len(result["products"]),
                "duplicates": result["duplicates"],
                "invalid": result["invalid"],
                "incomplete": result["incomplete"],
                "limit_reached": result["limit_reached"],
            }
            st.rerun()
        else:
            if not pasted_links.strip():
                st.warning("Cole pelo menos um link para importar.")
            elif result["duplicates"] or result["invalid"]:
                st.warning(
                    f"Nenhum produto novo adicionado. Duplicados: {len(result['duplicates'])}; "
                    f"links que não são HTTPS da Shopee: {len(result['invalid'])}."
                )
            else:
                st.warning("Nenhum link Shopee novo foi encontrado no lote.")
            if result["invalid"]:
                st.caption("Links ignorados por domínio/formato:")
                st.code("\n".join(result["invalid"][:10]))

    report = st.session_state.pop("bulk_import_report", None)
    if report:
        st.success(
            f"{report['added']} produto(s) adicionado(s) à tabela como inativos e não aprovados. "
            "Revise os dados e clique em Salvar produtos quando estiver pronto."
        )
        if report["incomplete"]:
            st.warning(
                f"Metadados incompletos em {len(report['incomplete'])} link(s); preencha nome e preço manualmente antes de aprovar."
            )
        if report["duplicates"]:
            st.info(f"{len(report['duplicates'])} link(s) duplicado(s) foram ignorados.")
        if report["invalid"]:
            st.warning(f"{len(report['invalid'])} link(s) que não são Shopee foram ignorados.")
            st.code("\n".join(report["invalid"][:10]))
        if report["limit_reached"]:
            st.info(f"O lote foi limitado a {MAX_LINKS_PER_BATCH} links. Envie o restante em outro lote.")

    if st.button("💾 Salvar produtos", type="primary"):
        ok, message = save(edited, sha)
        (st.success if ok else st.error)(message)
        if ok:
            st.rerun()

    st.caption("Baixe a tabela nos formatos CSV, Excel, TSV ou JSON.")
    exports = build_exports(clean(edited))
    download_columns = st.columns(len(exports))
    for column, (format_name, export) in zip(download_columns, exports.items()):
        column.download_button(
            f"⬇️ {format_name}",
            data=export["data"],
            file_name=export["file_name"],
            mime=export["mime"],
            key=f"download_products_{format_name.casefold()}",
            use_container_width=True,
        )

with ads:
    if len(df):
        selected_name = st.selectbox("Produto", df["nome"].tolist())
        selected_row = df[df["nome"] == selected_name].iloc[0]
        st.markdown(ad_preview(selected_row), unsafe_allow_html=True)
    else:
        st.info("Cadastre produtos primeiro.")

with telegram:
    st.subheader("📲 Telegram")
    st.write("O envio usa o Bot API oficial do Telegram.")
    st.write("Token:", "✅" if secret("telegram_bot_token") else "❌")
    st.write("Chat/Canal:", "✅" if secret("telegram_chat_id") else "❌")
    if len(df):
        selected_name = st.selectbox("Produto para teste", df["nome"].tolist(), key="telegram_test")
        selected_row = df[df["nome"] == selected_name].iloc[0]
        can_send_test = (
            parse_bool(selected_row.get("ativo", True), default=True)
            and parse_bool(selected_row.get("aprovado_publicacao", False), default=False)
        )
        if not can_send_test:
            st.warning("O teste de envio fica bloqueado: ative e aprove este produto primeiro.")
        if st.button("🚀 Enviar teste agora", disabled=not can_send_test):
            token = secret("telegram_bot_token")
            chat_id = secret("telegram_chat_id")
            if not token or not chat_id:
                st.error("Configure telegram_bot_token e telegram_chat_id.")
            else:
                base_url = f"https://api.telegram.org/bot{token}"
                try:
                    image_url = str(selected_row["imagem_url"]).strip()
                    if image_url:
                        response = requests.post(
                            f"{base_url}/sendPhoto",
                            data={
                                "chat_id": chat_id,
                                "photo": image_url,
                                "caption": telegram_ad(selected_row),
                                "parse_mode": "HTML",
                            },
                            timeout=30,
                        )
                    else:
                        response = requests.post(
                            f"{base_url}/sendMessage",
                            data={
                                "chat_id": chat_id,
                                "text": telegram_ad(selected_row),
                                "parse_mode": "HTML",
                            },
                            timeout=30,
                        )
                    payload = response.json()
                    if response.ok and payload.get("ok"):
                        st.success("Enviado!")
                    else:
                        st.error(payload.get("description", "Telegram recusou a mensagem."))
                except requests.RequestException:
                    st.error("Falha de conexão com Telegram. Confira o status do serviço e tente novamente.")
                except ValueError:
                    st.error("Telegram retornou uma resposta inválida.")
