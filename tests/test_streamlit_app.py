from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def test_app_renders_and_imports_amazon_ebay_as_inactive_manual_drafts():
    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "📊 Painel",
        "📋 Produtos",
        "📢 Anúncios",
        "📣 Canais",
    ]

    app.text_area[0].set_value("https://amzn.to/test123\nhttps://ebay.us/test456")
    app.form_submit_button[0].click()
    app.run()

    assert not app.exception
    assert any("2 produto(s) adicionado(s)" in item.value for item in app.success)
    catalog = app.data_editor[0].value
    assert catalog["programa"].tolist() == ["Amazon Associados", "eBay Partner Network"]
    assert catalog["ativo"].tolist() == [False, False]
    assert catalog["aprovado_publicacao"].tolist() == [False, False]
    assert catalog["imagem_autorizada"].tolist() == [False, False]
