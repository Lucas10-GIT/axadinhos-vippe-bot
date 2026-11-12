"""Data-only summaries used by the Streamlit operations dashboard."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from publisher import parse_bool, score
from affiliate_links import affiliate_program, explicit_true, is_valid_affiliate_link


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def _sum_column(frame: pd.DataFrame, column: str) -> float:
    if column not in frame.columns or frame.empty:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def build_attention_items(frame: pd.DataFrame, limit: int | None = 6) -> pd.DataFrame:
    """List products needing review, approval, activation, or missing data."""
    columns = ["ID", "Produto", "Ponto de atenção"]
    items: list[dict[str, Any]] = []

    for _, row in frame.iterrows():
        reasons: list[str] = []
        status = _text(row.get("status_publicacao")).casefold()
        pinterest_status = _text(row.get("pinterest_status")).casefold()
        review_needed = (
            status in {"revisar", "enviando"}
            or pinterest_status == "revisar"
        )
        if status == "revisar":
            reasons.append("Publicação em revisão")
        if status == "enviando":
            reasons.append("Publicação em andamento — confira o resultado")
        if pinterest_status == "revisar":
            reasons.append("Pinterest precisa de revisão")

        missing = [label for field, label in (("nome", "nome"), ("link", "link afiliado")) if not _text(row.get(field))]
        invalid_link = bool(_text(row.get("link"))) and not is_valid_affiliate_link(row.get("link"))
        if missing:
            reasons.append("Dados faltando: " + ", ".join(missing))
        if invalid_link:
            reasons.append("Link afiliado inválido ou sem rastreamento reconhecido")
        if not _text(row.get("imagem_url")) and pinterest_status != "enviado":
            reasons.append("Foto ausente para Pin")
        elif pinterest_status != "enviado" and not explicit_true(row.get("imagem_autorizada", False)):
            reasons.append("Confirme autorização da imagem/arte para Pinterest")

        if (
            affiliate_program(row.get("link")) == "ebay"
            and not explicit_true(row.get("epn_promocao_aprovada", False))
        ):
            reasons.append("Aguardando aprovação escrita EPN para promoção/conteúdo")

        approved = parse_bool(row.get("aprovado_publicacao", False), default=False)
        active = parse_bool(row.get("ativo", False), default=False)
        if not approved:
            reasons.append("Aguardando aprovação")
        if not active:
            reasons.append("Inativo")

        if not reasons:
            continue

        priority = 0 if review_needed else 1 if missing or invalid_link else 2 if not approved else 3
        items.append({
            "_priority": priority,
            "ID": int(_number(row.get("id"))),
            "Produto": _text(row.get("nome")) or "(sem nome)",
            "Ponto de atenção": " · ".join(reasons),
        })

    if not items:
        return pd.DataFrame(columns=columns)
    result = pd.DataFrame(items).sort_values(["_priority", "ID"])
    if limit is not None:
        result = result.head(max(0, limit))
    return result[columns].reset_index(drop=True)


CATALOG_SEGMENTS = (
    "Todos",
    "Precisam de atenção",
    "Ativos e aprovados",
    "Com atividade registrada",
    "Dados incompletos",
    "Pinterest pendente",
    "Pinterest enviado",
    "Pinterest em revisão",
)


def filter_product_catalog(
    frame: pd.DataFrame,
    segment: str = "Todos",
    category: str | None = None,
) -> pd.DataFrame:
    """Return a read-only catalog view; this never changes publish eligibility or state."""
    if frame.empty:
        return frame.copy()

    selected = str(segment or "Todos")
    attention_ids: set[int] = set()
    if selected == "Precisam de atenção":
        attention = build_attention_items(frame, limit=None)
        attention_ids = set(attention["ID"].astype(int).tolist())

    keep = []
    for _, row in frame.iterrows():
        active = parse_bool(row.get("ativo", False), default=False)
        approved = parse_bool(row.get("aprovado_publicacao", False), default=False)
        pinterest_status = _text(row.get("pinterest_status")).casefold()
        bad_link = bool(_text(row.get("link"))) and not is_valid_affiliate_link(row.get("link"))
        missing = (
            any(not _text(row.get(field)) for field in ("nome", "link"))
            or bad_link
            or (pinterest_status != "enviado" and not _text(row.get("imagem_url")))
            or (pinterest_status != "enviado" and not explicit_true(row.get("imagem_autorizada", False)))
            or (
                affiliate_program(row.get("link")) == "ebay"
                and not explicit_true(row.get("epn_promocao_aprovada", False))
            )
        )
        activity = any(
            _number(row.get(field)) > 0
            for field in ("cliques", "pedidos", "comissao_estimada")
        )

        if selected == "Precisam de atenção":
            matches_segment = int(_number(row.get("id"))) in attention_ids
        elif selected == "Ativos e aprovados":
            matches_segment = active and approved
        elif selected == "Com atividade registrada":
            matches_segment = activity
        elif selected == "Dados incompletos":
            matches_segment = missing
        elif selected == "Pinterest pendente":
            matches_segment = pinterest_status == "pendente"
        elif selected == "Pinterest enviado":
            matches_segment = pinterest_status == "enviado"
        elif selected == "Pinterest em revisão":
            matches_segment = pinterest_status == "revisar"
        else:
            matches_segment = True

        if category and _text(row.get("categoria")).casefold() != category.strip().casefold():
            matches_segment = False
        keep.append(matches_segment)

    return frame.loc[keep].copy()


def build_dashboard_kpis(frame: pd.DataFrame) -> dict[str, int | float]:
    """Summarize persisted catalog counts without inventing time-series data."""
    if frame.empty:
        return {
            "products": 0,
            "active_approved": 0,
            "attention": 0,
            "clicks": 0,
            "orders": 0,
            "pinterest_pins": 0,
            "commission": 0.0,
        }

    active_approved = sum(
        parse_bool(row.get("ativo", False), default=False)
        and parse_bool(row.get("aprovado_publicacao", False), default=False)
        for _, row in frame.iterrows()
    )
    pinterest_pins = sum(
        _text(value).casefold() == "enviado"
        for value in frame.get("pinterest_status", pd.Series(index=frame.index, dtype=object))
    )
    return {
        "products": int(len(frame)),
        "active_approved": int(active_approved),
        "attention": int(len(build_attention_items(frame, limit=None))),
        "clicks": int(round(_sum_column(frame, "cliques"))),
        "orders": int(round(_sum_column(frame, "pedidos"))),
        "pinterest_pins": int(pinterest_pins),
        "commission": round(_sum_column(frame, "comissao_estimada"), 2),
    }


def build_top_products(frame: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    """Rank products with recorded activity using the publisher's exact score."""
    columns = ["Produto", "Cliques", "Pedidos", "Comissão estimada", "Pontuação"]
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        clicks = max(0.0, _number(row.get("cliques")))
        orders = max(0.0, _number(row.get("pedidos")))
        commission = max(0.0, _number(row.get("comissao_estimada")))
        if clicks == 0 and orders == 0 and commission == 0:
            continue
        records.append({
            "Produto": _text(row.get("nome")) or "(sem nome)",
            "Cliques": int(round(clicks)),
            "Pedidos": int(round(orders)),
            "Comissão estimada": round(commission, 2),
            "Pontuação": round(score(row), 2),
        })
    if not records:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(records)
        .sort_values(
            ["Pontuação", "Pedidos", "Comissão estimada", "Cliques"],
            ascending=False,
        )
        .head(max(0, limit))
        .reset_index(drop=True)
    )


def build_category_performance(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only recorded clicks and orders by category."""
    columns = ["Categoria", "Cliques", "Pedidos"]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    work = pd.DataFrame(index=frame.index)
    if "categoria" in frame.columns:
        work["Categoria"] = frame["categoria"].map(_text).replace("", "Sem categoria")
    else:
        work["Categoria"] = "Sem categoria"
    for metric in ("cliques", "pedidos"):
        work[metric.capitalize()] = (
            pd.to_numeric(frame[metric], errors="coerce").fillna(0)
            if metric in frame.columns
            else 0
        )

    grouped = (
        work.groupby("Categoria", as_index=False)[["Cliques", "Pedidos"]]
        .sum()
        .assign(_total=lambda data: data["Cliques"] + data["Pedidos"])
        .sort_values(["_total", "Pedidos", "Cliques"], ascending=False)
    )
    return grouped[columns].reset_index(drop=True)
