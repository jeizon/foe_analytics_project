"""Audit what FoE is providing through captured service payloads."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncpg

MODULE_IDEAS = {
    "player": [
        "Perfil consolidado do jogador, mundo, era e guilda.",
        "Historico de mudancas de nome/guilda/era.",
    ],
    "resources": [
        "Carteira em tempo real: moedas, mantimentos, diamantes, medalhas e recursos especiais.",
        "Variacao de recursos por acao, coleta, recompensa e gasto.",
    ],
    "city": [
        "Inventario da cidade e producao por edificio.",
        "Base para otimizacao de layout e eficiencia.",
    ],
    "gbg": [
        "Mapa CBG, donos de setores, progresso de conquista e logs pessoais.",
        "Base para velocidade inimiga, rogue hits e heatmaps em fases futuras.",
    ],
    "battle": [
        "Historico de batalhas, provincia, resultado e exercito usado.",
        "Analise de perdas, auto-battle e padroes de vitoria.",
    ],
    "guild": [
        "Dados de guilda, membros, ranking e atividades cooperativas.",
    ],
    "quests": [
        "Rastreamento de quests ativas, timers e recompensas.",
    ],
    "social": [
        "Mensagens, amigos, taverna e interacoes sociais.",
    ],
    "map": [
        "Mapa de campanha, setores, scouts e conquistas fora do CBG.",
    ],
    "events": [
        "Eventos sazonais, passes, recompensas ocultas e progresso.",
    ],
    "ranking": [
        "Rankings do jogador, guilda e competidores por periodo.",
    ],
    "system": [
        "Timers, boosts, avisos e sinais uteis para sincronizar snapshots.",
    ],
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit captured FoE data.")
    parser.add_argument("--limit-services", type=int, default=80)
    parser.add_argument("--limit-keys", type=int, default=30)
    args = parser.parse_args()

    load_env(PROJECT_ROOT / ".env")
    database_url = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://foe_analytics:foe_analytics_dev@localhost:5432/foe_analytics",
        )
    )
    asyncio.run(audit(database_url, args.limit_services, args.limit_keys))


async def audit(database_url: str, limit_services: int, limit_keys: int) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        await connection.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

        print("=== FoE Captured Data Audit ===")
        counts = await connection.fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM raw_packets) AS raw_packets,
              (SELECT COUNT(*) FROM routed_service_events) AS routed_events,
              (SELECT COUNT(*) FROM service_catalog) AS catalog_entries,
              (SELECT COUNT(*) FROM game_domain_snapshots) AS domain_snapshots,
              (SELECT COUNT(*) FROM player_profile_snapshots) AS profile_snapshots,
              (SELECT COUNT(*) FROM player_resource_snapshots) AS resource_snapshots,
              (SELECT COUNT(*) FROM player_identities) AS consolidated_identities,
              (SELECT COUNT(*) FROM player_wallet_balances) AS consolidated_wallet_balances,
              (SELECT COUNT(*) FROM player_wallet_snapshots) AS consolidated_wallet_snapshots
            """
        )
        for key, value in dict(counts).items():
            print(f"{key}: {value}")

        print("\n=== Domains ===")
        domains = await connection.fetch(
            """
            SELECT domain, COUNT(*) AS services, SUM(total_seen) AS events, MAX(last_seen_at) AS last_seen
            FROM service_catalog
            GROUP BY domain
            ORDER BY events DESC NULLS LAST
            """
        )
        for row in domains:
            print(f"{row['domain']}: services={row['services']} events={row['events']} last={row['last_seen']}")

        print("\n=== Services ===")
        services = await connection.fetch(
            """
            SELECT domain, service_name, method_name, total_seen, last_seen_at
            FROM service_catalog
            ORDER BY total_seen DESC, last_seen_at DESC
            LIMIT $1
            """,
            limit_services,
        )
        for row in services:
            print(
                f"{row['domain']}: {row['service_name']}.{row['method_name'] or '(unknown)'} "
                f"seen={row['total_seen']} last={row['last_seen_at']}"
            )

        print("\n=== Latest Player Profiles ===")
        profiles = await connection.fetch(
            """
            SELECT
                p.player_id,
                COALESCE(identity.player_name, p.player_name) AS player_name,
                p.guild_name,
                p.era,
                p.world_id,
                p.observed_at
            FROM player_profile_snapshots p
            LEFT JOIN player_identities identity
              ON identity.player_id = p.player_id
             AND identity.world_id = p.world_id
            WHERE p.player_id ~ '^[0-9]+$'
            ORDER BY p.observed_at DESC
            LIMIT 20
            """
        )
        if not profiles:
            print("No numeric player profile snapshots yet.")
        for row in profiles:
            print(dict(row))

        print("\n=== Consolidated Player Identities ===")
        identities = await connection.fetch(
            """
            SELECT player_id, player_name, guild_name, era, world_id, last_seen_at
            FROM player_identities
            ORDER BY last_seen_at DESC
            LIMIT 20
            """
        )
        if not identities:
            print("No consolidated identities yet.")
        for row in identities:
            print(dict(row))

        print("\n=== Consolidated Wallet Balances ===")
        balances = await connection.fetch(
            """
            SELECT
                w.player_id,
                identity.player_name,
                w.world_id,
                w.resource_name,
                w.amount_text,
                w.source_service,
                w.source_method,
                w.last_seen_at
            FROM player_wallet_balances w
            LEFT JOIN player_identities identity
              ON identity.player_id = w.player_id
             AND identity.world_id = w.world_id
            ORDER BY w.resource_name ASC
            LIMIT 40
            """
        )
        if not balances:
            print("No consolidated wallet balances yet.")
        for row in balances:
            print(dict(row))

        print("\n=== Latest Wallet Candidates ===")
        wallet = await connection.fetch(
            """
            SELECT DISTINCT ON (resource_name)
                   res.player_id,
                   identity.player_name,
                   res.world_id,
                   res.resource_name,
                   res.amount,
                   res.source_service,
                   res.source_method,
                   res.observed_at
            FROM player_resource_snapshots res
            LEFT JOIN player_identities identity
              ON identity.player_id = res.player_id
             AND identity.world_id = res.world_id
            WHERE lower(res.resource_name) IN (
                'money',
                'coins',
                'coin',
                'supplies',
                'supply',
                'strategy_points',
                'forge_points',
                'forgepoints',
                'premium',
                'diamonds',
                'medals',
                'population',
                'happiness'
            )
            ORDER BY res.resource_name, res.observed_at DESC
            LIMIT 40
            """
        )
        if not wallet:
            print("No wallet candidates yet.")
        for row in wallet:
            print(dict(row))

        print("\n=== Latest Resources ===")
        resources = await connection.fetch(
            """
            SELECT
                res.player_id,
                identity.player_name,
                res.world_id,
                res.resource_name,
                res.amount,
                res.source_service,
                res.source_method,
                res.observed_at
            FROM player_resource_snapshots res
            LEFT JOIN player_identities identity
              ON identity.player_id = res.player_id
             AND identity.world_id = res.world_id
            WHERE res.source_service NOT IN ('BattlefieldService', 'ArmyUnitManagementService')
            ORDER BY res.observed_at DESC
            LIMIT 40
            """
        )
        if not resources:
            print("No wallet/resource snapshots yet.")
        for row in resources:
            print(dict(row))

        print("\n=== Frequent Payload Keys By Domain ===")
        samples = await connection.fetch(
            """
            SELECT domain, payload
            FROM game_domain_snapshots
            ORDER BY captured_at DESC
            LIMIT 500
            """
        )
        key_counter_by_domain: dict[str, Counter[str]] = defaultdict(Counter)
        for row in samples:
            for key_path in walk_key_paths(row["payload"]):
                key_counter_by_domain[row["domain"]][key_path] += 1

        for domain, counter in sorted(key_counter_by_domain.items()):
            print(f"\n[{domain}]")
            for key, total in counter.most_common(limit_keys):
                print(f"  {key}: {total}")

        print("\n=== What We Can Build Next ===")
        seen_domains = {row["domain"] for row in domains}
        for domain in sorted(seen_domains):
            ideas = MODULE_IDEAS.get(domain, ["Exploracao e modelagem especifica para este dominio."])
            print(f"\n{domain}:")
            for idea in ideas:
                print(f"  - {idea}")
    finally:
        await connection.close()


def walk_key_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, nested_value in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.append(path)
            paths.extend(walk_key_paths(nested_value, path))
    elif isinstance(value, list) and value:
        paths.extend(walk_key_paths(value[0], f"{prefix}[]"))
    return paths


def load_env(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


if __name__ == "__main__":
    main()
