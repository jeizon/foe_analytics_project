"""Streamlit dashboard for FoE Python Analytics."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from sqlalchemy.exc import SQLAlchemyError

from dashboard_ui.data_access import (
    ALL_CONTEXT,
    fetch_capture_overview,
    fetch_contexts,
    fetch_domain_summary,
    fetch_latest_player_profiles,
    fetch_latest_resources,
    fetch_latest_sectors,
    fetch_overview,
    fetch_player_identities,
    fetch_recent_actions,
    fetch_service_catalog,
    fetch_wallet_balances,
    fetch_wallet_candidates,
    fetch_wallet_history,
)
from database.db_manager import DEFAULT_DATABASE_URL, DatabaseManager


def main() -> None:
    """Render the FoE analytics dashboard."""

    st.set_page_config(page_title="FoE Python Analytics", layout="wide")
    st.title("FoE Python Analytics Dashboard")

    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    db_manager = _get_database(database_url)

    try:
        _run(db_manager.create_schema())
        contexts = _run(fetch_contexts(db_manager))
    except SQLAlchemyError as exc:
        st.error("Banco de dados indisponivel ou schema ainda nao criado.")
        st.caption(str(exc))
        return

    player_options = _distinct_options(contexts, "player_id")
    world_options = _distinct_options(contexts, "world_id")
    player_labels = _player_labels(contexts)

    with st.sidebar:
        st.header("Contexto")
        selected_world = st.selectbox("Mundo", world_options, format_func=_format_option)
        selected_player = st.selectbox(
            "Jogador",
            player_options,
            format_func=lambda value: _format_player_option(value, player_labels),
        )
        row_limit = st.slider("Linhas", min_value=25, max_value=300, value=100, step=25)

    try:
        capture_overview = _run(
            fetch_capture_overview(db_manager, selected_player, selected_world)
        )
        domain_summary = _run(fetch_domain_summary(db_manager, selected_player, selected_world))
        profiles = _run(
            fetch_latest_player_profiles(db_manager, selected_player, selected_world, row_limit)
        )
        identities = _run(fetch_player_identities(db_manager, selected_player, selected_world))
        wallet_balances = _run(fetch_wallet_balances(db_manager, selected_player, selected_world))
        wallet_history = _run(
            fetch_wallet_history(db_manager, selected_player, selected_world, row_limit)
        )
        wallet = _run(fetch_wallet_candidates(db_manager, selected_player, selected_world))
        latest_resources = _run(
            fetch_latest_resources(db_manager, selected_player, selected_world, row_limit)
        )
        service_catalog = _run(fetch_service_catalog(db_manager, row_limit))
        cbg_overview = _run(fetch_overview(db_manager, selected_player, selected_world))
        latest_sectors = _run(
            fetch_latest_sectors(db_manager, selected_player, selected_world, row_limit)
        )
        recent_actions = _run(
            fetch_recent_actions(db_manager, selected_player, selected_world, row_limit)
        )
    except SQLAlchemyError as exc:
        st.error("Nao foi possivel carregar os dados capturados.")
        st.caption(str(exc))
        return

    capture_tab, player_tab, services_tab, cbg_tab = st.tabs(
        ["Captura", "Jogador & Carteira", "Servicos", "CBG"]
    )

    with capture_tab:
        _render_capture_metrics(capture_overview)
        st.subheader("Dominios capturados")
        if domain_summary:
            st.dataframe(domain_summary, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando snapshots universais do jogo.")

    with player_tab:
        cols = st.columns([1, 2])
        with cols[0]:
            st.subheader("Identidade consolidada")
            if identities:
                st.dataframe(identities, use_container_width=True, hide_index=True)
            else:
                st.info("Aguardando identidade consolidada.")
        with cols[1]:
            st.subheader("Carteira consolidada")
            if wallet_balances:
                st.dataframe(wallet_balances, use_container_width=True, hide_index=True)
            else:
                st.info("Aguardando saldos consolidados.")

        st.subheader("Historico de carteira")
        if wallet_history:
            st.dataframe(wallet_history, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando historico de carteira.")

        st.subheader("Perfil exploratorio")
        if profiles:
            st.dataframe(profiles, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando perfil exploratorio.")

        st.subheader("Carteira provavel exploratoria")
        if wallet:
            st.dataframe(wallet, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando moedas, mantimentos, diamantes ou PFs.")

        st.subheader("Recursos recentes exploratorios")
        if latest_resources:
            st.dataframe(latest_resources, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando snapshots de recursos.")

    with services_tab:
        st.subheader("Servicos descobertos")
        if service_catalog:
            st.dataframe(service_catalog, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando catalogo de servicos.")

    with cbg_tab:
        _render_cbg_metrics(cbg_overview)

        st.subheader("Setores CBG")
        if latest_sectors:
            st.dataframe(latest_sectors, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando snapshots de setores CBG.")

        st.subheader("Log pessoal")
        if recent_actions:
            st.dataframe(recent_actions, use_container_width=True, hide_index=True)
        else:
            st.info("Aguardando batalhas ou negociacoes CBG.")


@st.cache_resource
def _get_database(database_url: str) -> DatabaseManager:
    return DatabaseManager(database_url=database_url)


@st.cache_resource
def _get_event_loop() -> asyncio.AbstractEventLoop:
    return asyncio.new_event_loop()


def _run(awaitable: Any) -> Any:
    return _get_event_loop().run_until_complete(awaitable)


def _distinct_options(rows: list[dict[str, Any]], key: str) -> list[str]:
    values = sorted({str(row[key]) for row in rows if row.get(key)})
    return [ALL_CONTEXT, *values]


def _format_option(value: str) -> str:
    if value == ALL_CONTEXT:
        return "Todos"
    return value


def _format_player_option(value: str, labels: dict[str, str]) -> str:
    if value == ALL_CONTEXT:
        return "Todos"

    player_name = labels.get(value)
    if player_name:
        return f"{player_name} ({value})"

    return value


def _player_labels(rows: list[dict[str, Any]]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for row in rows:
        player_id = row.get("player_id")
        player_name = row.get("player_name")
        if player_id and player_name:
            labels[str(player_id)] = str(player_name)
    return labels


def _render_capture_metrics(overview: dict[str, Any]) -> None:
    cols = st.columns(6)
    cols[0].metric("Pacotes brutos", overview["raw_packets"])
    cols[1].metric("Eventos roteados", overview["routed_events"])
    cols[2].metric("Servicos", overview["catalog_entries"])
    cols[3].metric("Snapshots", overview["domain_snapshots"])
    cols[4].metric("Perfis", overview["profile_snapshots"])
    cols[5].metric("Recursos", overview["resource_snapshots"])

    if overview.get("latest_capture"):
        st.caption(f"Ultima captura universal: {overview['latest_capture']}")


def _render_cbg_metrics(overview: dict[str, Any]) -> None:
    cols = st.columns(6)
    cols[0].metric("Pacotes CBG", overview["cbg_packets"])
    cols[1].metric("Setores", overview["tracked_sectors"])
    cols[2].metric("Snapshots", overview["sector_snapshots"])
    cols[3].metric("Acoes", overview["total_actions"])
    cols[4].metric("Batalhas", overview["battles"])
    cols[5].metric("Negociacoes", overview["negotiations"])


if __name__ == "__main__":
    main()
