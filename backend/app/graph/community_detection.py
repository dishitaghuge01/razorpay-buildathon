"""Louvain community detection -> cluster candidates."""

from __future__ import annotations

import networkx as nx

try:
    import community as community_louvain
except Exception:  # pragma: no cover
    community_louvain = None

from app.graph.graph_builder import get_graph_snapshot


def detect_communities(graph: nx.Graph, algorithm: str = "louvain") -> dict[str, int]:
    """Returns {account_id: community_id}. Uses python-louvain
    (community_louvain.best_partition)."""
    if community_louvain is None:
        raise ImportError("python-louvain is required for community detection")
    if algorithm != "louvain":
        raise ValueError(f"Unsupported algorithm: {algorithm}")
    partition = community_louvain.best_partition(graph, weight="weight")
    return {str(account_id): int(cid) for account_id, cid in partition.items()}


def extract_cluster_candidates(run_id: str, tick: int, min_size: int = 3) -> list[dict]:
    """Calls get_graph_snapshot + detect_communities, filters
    communities with >= min_size members, returns
    [{ "member_account_ids": [...], "tick": tick }, ...]
    ready to be scored by both classifiers."""
    graph = get_graph_snapshot(run_id, tick)
    if graph.number_of_nodes() == 0:
        return []
    partition = detect_communities(graph)
    communities: dict[int, list[str]] = {}
    for account_id, community_id in partition.items():
        communities.setdefault(community_id, []).append(str(account_id))

    candidates: list[dict] = []
    for community_id, member_ids in communities.items():
        if len(member_ids) < min_size:
            continue
        candidates.append({
            "member_account_ids": sorted(member_ids),
            "tick": tick,
            "community_id": community_id,
        })
    return candidates
