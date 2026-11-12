import pandas as pd

from dashboard_metrics import (
    build_attention_items,
    build_category_performance,
    build_dashboard_kpis,
    build_top_products,
    filter_product_catalog,
)
from publisher import score


BASE = {
    "id": 1,
    "nome": "Organizador de gaveta",
    "preco": "R$ 29,90",
    "link": "https://s.shopee.com.br/affiliate-code",
    "imagem_url": "https://down-br.img.susercontent.com/file/product.jpg",
    "categoria": "Casa",
    "ativo": True,
    "aprovado_publicacao": True,
    "status_publicacao": "pronto",
    "pinterest_status": "pendente",
    "cliques": 20,
    "pedidos": 1,
    "comissao_estimada": 4.5,
}


def test_dashboard_kpis_count_real_catalog_activity_and_attention():
    frame = pd.DataFrame([
        {**BASE, "id": 1, "pinterest_status": "enviado"},
        {
            **BASE,
            "id": 2,
            "nome": "Rascunho de brinquedo",
            "ativo": False,
            "aprovado_publicacao": False,
            "status_publicacao": "revisar",
            "pinterest_status": "enviado",
            "cliques": 0,
            "pedidos": 0,
            "comissao_estimada": 0,
        },
    ])

    result = build_dashboard_kpis(frame)

    assert result == {
        "products": 2,
        "active_approved": 1,
        "attention": 1,
        "clicks": 20,
        "orders": 1,
        "pinterest_pins": 2,
        "commission": 4.5,
    }


def test_attention_queue_explains_review_and_missing_product_data():
    frame = pd.DataFrame([
        {**BASE, "id": 2, "status_publicacao": "revisar", "pinterest_status": "revisar"},
        {
            **BASE,
            "id": 3,
            "nome": "",
            "preco": "",
            "link": "",
            "imagem_url": "",
            "ativo": False,
            "aprovado_publicacao": False,
        },
    ])

    attention = build_attention_items(frame, limit=1)
    assert len(attention) == 1
    assert attention.iloc[0]["ID"] == 2
    assert "Publicação em revisão" in attention.iloc[0]["Ponto de atenção"]
    assert "Pinterest precisa de revisão" in attention.iloc[0]["Ponto de atenção"]

    full = build_attention_items(frame, limit=None)
    missing_row = full[full["ID"] == 3].iloc[0]
    assert "Dados faltando: nome, preço, link afiliado" in missing_row["Ponto de atenção"]
    assert "Foto ausente para Pin" in missing_row["Ponto de atenção"]
    assert "Aguardando aprovação" in missing_row["Ponto de atenção"]
    assert "Inativo" in missing_row["Ponto de atenção"]


def test_top_products_use_the_same_score_as_the_publisher():
    lower = {**BASE, "id": 1, "nome": "Mais cliques", "cliques": 100, "pedidos": 1}
    higher = {**BASE, "id": 2, "nome": "Mais pedidos", "cliques": 4, "pedidos": 3}

    top = build_top_products(pd.DataFrame([lower, higher]), limit=1)

    assert top.iloc[0]["Produto"] == "Mais pedidos"
    assert top.iloc[0]["Pontuação"] == round(score(higher), 2)


def test_attention_queue_flags_an_in_progress_publication_for_manual_check():
    frame = pd.DataFrame([{**BASE, "status_publicacao": "enviando"}])

    attention = build_attention_items(frame)

    assert len(attention) == 1
    assert "Publicação em andamento" in attention.iloc[0]["Ponto de atenção"]


def test_category_performance_aggregates_only_persisted_clicks_and_orders():
    frame = pd.DataFrame([
        {**BASE, "categoria": "Casa", "cliques": 5, "pedidos": 1},
        {**BASE, "categoria": "Casa", "cliques": 7, "pedidos": 0},
        {**BASE, "categoria": "Pet", "cliques": 4, "pedidos": 2},
    ])

    categories = build_category_performance(frame).set_index("Categoria")

    assert categories.loc["Casa", "Cliques"] == 12
    assert categories.loc["Casa", "Pedidos"] == 1
    assert categories.loc["Pet", "Cliques"] == 4
    assert categories.loc["Pet", "Pedidos"] == 2


def test_empty_catalog_returns_zero_kpis_and_empty_visualization_frames():
    frame = pd.DataFrame()

    assert build_dashboard_kpis(frame)["products"] == 0
    assert build_attention_items(frame).empty
    assert build_top_products(frame).empty
    assert build_category_performance(frame).empty


def test_catalog_segments_filter_by_status_activity_missing_data_and_category():
    frame = pd.DataFrame([
        {**BASE, "id": 1, "categoria": "Casa", "pinterest_status": "pendente"},
        {
            **BASE,
            "id": 2,
            "categoria": "Pet",
            "pinterest_status": "enviado",
            "cliques": 0,
            "pedidos": 0,
            "comissao_estimada": 0,
        },
        {
            **BASE,
            "id": 3,
            "categoria": "Casa",
            "nome": "",
            "imagem_url": "",
            "ativo": False,
            "aprovado_publicacao": False,
            "pinterest_status": "revisar",
        },
    ])
    original = frame.copy(deep=True)

    assert filter_product_catalog(frame, "Ativos e aprovados")["id"].tolist() == [1, 2]
    assert filter_product_catalog(frame, "Com atividade registrada")["id"].tolist() == [1, 3]
    assert filter_product_catalog(frame, "Dados incompletos")["id"].tolist() == [3]
    assert filter_product_catalog(frame, "Pinterest pendente")["id"].tolist() == [1]
    assert filter_product_catalog(frame, "Pinterest enviado")["id"].tolist() == [2]
    assert filter_product_catalog(frame, "Pinterest em revisão")["id"].tolist() == [3]
    assert filter_product_catalog(frame, "Todos", category="cAsA")["id"].tolist() == [1, 3]
    pd.testing.assert_frame_equal(frame, original)


def test_attention_catalog_segment_uses_existing_attention_logic():
    frame = pd.DataFrame([
        {**BASE, "id": 1},
        {**BASE, "id": 2, "aprovado_publicacao": False},
    ])

    result = filter_product_catalog(frame, "Precisam de atenção")

    assert result["id"].tolist() == [2]
