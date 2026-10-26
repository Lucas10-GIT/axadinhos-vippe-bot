import streamlit as st

st.set_page_config(
    page_title="Axadinhos Vippe",
    page_icon="👑",
    layout="centered"
)

st.title("👑 Axadinhos Vippe")
st.subheader("🤖 Bot de Ofertas")

st.write("Bem-vindo ao painel do Axadinhos Vippe!")

st.divider()

st.header("📦 Cadastrar produto")

link = st.text_input(
    "🔗 Link do produto Shopee",
    placeholder="Cole aqui o link do produto"
)

nome = st.text_input(
    "🛍️ Nome do produto",
    placeholder="Digite o nome do produto"
)

preco = st.text_input(
    "💰 Preço",
    placeholder="Ex: R$ 49,90"
)

if st.button("🤖 Gerar anúncio", type="primary"):

    if not link or not nome:
        st.warning("⚠️ Preencha pelo menos o nome e o link do produto.")

    else:
        st.success("✅ Produto recebido!")

        st.divider()

        st.subheader("📢 Prévia do anúncio")

        st.markdown(f"""
### 🔥 ACHADINHO DO DIA!

🛍️ **{nome}**

💰 **{preco if preco else "Confira o preço"}**

👉 **Compre na Shopee:**
{link}

👑 **Axadinhos Vippe**

*Se é útil, é achadinho!*
""")
