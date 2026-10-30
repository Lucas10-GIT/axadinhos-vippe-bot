import base64
import io
import os

import pandas as pd
import requests
import streamlit as st
from publish_telegram import ad as telegram_ad, parse_bool

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

st.title("👑 Axadinhos Vippe")
st.caption("Produtos, aprovação de ofertas, anúncios e desempenho")

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
        "Cadastre ofertas reais; confira preço, destino Shopee e foto. "
        "Novos produtos não são publicados até você marcar a aprovação."
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
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
    if st.button("💾 Salvar produtos", type="primary"):
        ok, message = save(edited, sha)
        (st.success if ok else st.error)(message)
        if ok:
            st.rerun()
    st.download_button(
        "⬇️ Baixar CSV",
        edited.to_csv(index=False).encode("utf-8"),
        "axadinhos_vippe_produtos.csv",
        "text/csv",
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
        if st.button("🚀 Enviar teste agora"):
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
