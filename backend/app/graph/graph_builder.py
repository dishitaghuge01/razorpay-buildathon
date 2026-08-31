"""Edge computation + networkx snapshot builder."""

from __future__ import annotations

import math
from collections import defaultdict

import networkx as nx

from app.db import supabase

REFUND_DELAY_TICKS = 3
TIMING_WINDOW_TICKS = 2
TIMING_DECAY_TAU = 1.5


def _extract_first_row(response):
    if response is None:
        return {}
    data = getattr(response, "data", response)
    if isinstance(data, list):
        return data[0] if data else {}
    if isinstance(data, dict):
        return data
    return {}


def _normalize_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def build_edges_for_tick(run_id: str, tick: int) -> list[dict]:
    """Pulls all accounts/transactions/reviews for run_id up to `tick`.
    Computes and inserts edges rows for:
      - device_overlap: weight=1.0 if exact device_fingerprint match else 0
      - ip_overlap: weight=1.0 if exact ip_subnet match else 0
      - payout_overlap: weight=1.0 if exact payout_account match else 0
      - timing_correlation: weight=exp(-delta_ticks/TIMING_DECAY_TAU) for
        any two accounts whose transactions/reviews land within
        TIMING_WINDOW_TICKS of each other on the SAME merchant
      - reciprocal_review: weight=1.0 if A reviewed a merchant B also
        transacted with AND B reviewed a merchant A also transacted with,
        within TIMING_WINDOW_TICKS
    Only inserts edges with weight > 0.15 (noise floor) to keep the
    graph panel legible. Returns inserted rows."""
    account_response = supabase.table("accounts").select("id, device_fingerprint, ip_subnet, payout_account").eq("run_id", run_id).lte("created_tick", tick).execute()
    accounts = getattr(account_response, "data", account_response) or []
    if not accounts:
        return []

    inserted: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def add_edge(account_a_id: str, account_b_id: str, edge_type: str, weight: float):
        if weight <= 0.15:
            return
        key = (account_a_id, account_b_id, edge_type)
        if key in seen:
            return
        seen.add(key)
        row = {
            "run_id": run_id,
            "account_a_id": min(account_a_id, account_b_id),
            "account_b_id": max(account_a_id, account_b_id),
            "edge_type": edge_type,
            "weight": float(weight),
            "tick": tick,
        }
        response = supabase.table("edges").insert(row).execute()
        inserted.append(_extract_first_row(response))

    by_device: dict[str, list[str]] = defaultdict(list)
    by_ip: dict[str, list[str]] = defaultdict(list)
    by_payout: dict[str, list[str]] = defaultdict(list)
    for account in accounts:
        by_device[account["device_fingerprint"]].append(account["id"])
        by_ip[account["ip_subnet"]].append(account["id"])
        by_payout[account["payout_account"]].append(account["id"])

    for group in by_device.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                add_edge(group[i], group[j], "device_overlap", 1.0)
    for group in by_ip.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                add_edge(group[i], group[j], "ip_overlap", 1.0)
    for group in by_payout.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                add_edge(group[i], group[j], "payout_overlap", 1.0)

    tx_response = supabase.table("transactions").select("id, buyer_account_id, merchant_id, tick").eq("run_id", run_id).lte("tick", tick).execute()
    tx_rows = getattr(tx_response, "data", tx_response) or []
    review_response = supabase.table("reviews").select("id, reviewer_account_id, merchant_id, tick").eq("run_id", run_id).lte("tick", tick).execute()
    review_rows = getattr(review_response, "data", review_response) or []

    merchant_events: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for tx in tx_rows:
        merchant_events[tx["merchant_id"]].append((tx["buyer_account_id"], int(tx["tick"]), "transaction"))
    for review in review_rows:
        merchant_events[review["merchant_id"]].append((review["reviewer_account_id"], int(review["tick"]), "review"))

    for merchant_id, events in merchant_events.items():
        for i in range(len(events)):
            account_a, tick_a, _ = events[i]
            for j in range(i + 1, len(events)):
                account_b, tick_b, _ = events[j]
                if account_a == account_b:
                    continue
                delta = abs(tick_a - tick_b)
                if delta <= TIMING_WINDOW_TICKS:
                    weight = math.exp(-delta / TIMING_DECAY_TAU)
                    add_edge(account_a, account_b, "timing_correlation", weight)

    # Reciprocal review interpretation: two accounts are linked when A and B both
    # have merchant activity in the same time window, with A buying from a merchant
    # that B reviewed and B buying from a merchant that A reviewed. This captures
    # the core "I bought from you, you reviewed me, and the reverse also happened"
    # collusion pattern without requiring a direct edges table for it.
    account_ids = {a["id"] for a in accounts}
    for merchant_id, events in merchant_events.items():
        buyers = {account_id for account_id, _, kind in events if kind == "transaction"}
        reviewers = {account_id for account_id, _, kind in events if kind == "review"}
        for account_a in sorted(account_ids & buyers):
            for account_b in sorted(account_ids & reviewers):
                if account_a == account_b:
                    continue
                a_tx_hits = [e for e in tx_rows if e["buyer_account_id"] == account_a and e["merchant_id"] == merchant_id and int(e["tick"]) <= tick]
                b_review_hits = [e for e in review_rows if e["reviewer_account_id"] == account_b and e["merchant_id"] == merchant_id and int(e["tick"]) <= tick]
                if not a_tx_hits or not b_review_hits:
                    continue
                # also require the reverse relationship within the same timing window
                for tx in a_tx_hits:
                    tx_tick = int(tx["tick"])
                    for review in b_review_hits:
                        if abs(tx_tick - int(review["tick"])) <= TIMING_WINDOW_TICKS:
                            add_edge(account_a, account_b, "reciprocal_review", 1.0)
                            break
    return inserted


def get_graph_snapshot(run_id: str, tick: int) -> nx.Graph:
    """Builds an in-memory networkx.Graph from the edges + accounts
    tables for run_id at <= tick. Node attributes: account_type
    (ground truth, used ONLY for the UI's ground-truth reveal toggle,
    never passed into feature extraction)."""
    account_response = supabase.table("accounts").select("id, account_type").eq("run_id", run_id).lte("created_tick", tick).execute()
    accounts = getattr(account_response, "data", account_response) or []
    graph = nx.Graph()
    for account in accounts:
        graph.add_node(account["id"], account_type=account.get("account_type"))

    edge_response = supabase.table("edges").select("account_a_id, account_b_id, weight, edge_type").eq("run_id", run_id).lte("tick", tick).execute()
    edges = getattr(edge_response, "data", edge_response) or []
    for row in edges:
        if row.get("account_a_id") is None or row.get("account_b_id") is None:
            continue
        if graph.has_edge(row["account_a_id"], row["account_b_id"]):
            existing = graph.get_edge_data(row["account_a_id"], row["account_b_id"])
            graph[row["account_a_id"]][row["account_b_id"]]["weight"] = max(existing.get("weight", 0.0), float(row.get("weight", 0.0)))
            existing_types = existing.get("edge_types", [])
            if row.get("edge_type") not in existing_types:
                existing_types.append(row["edge_type"]) 
                graph[row["account_a_id"]][row["account_b_id"]]["edge_types"] = existing_types
            continue
        graph.add_edge(
            row["account_a_id"],
            row["account_b_id"],
            weight=float(row.get("weight", 0.0)),
            edge_types=[row.get("edge_type")],
        )
    return graph
