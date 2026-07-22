"""
retriever.py — Graph-aware retriever for RepoGraph AI.

Given a natural language question:
  1. Retrieves candidate seed nodes via hybrid (keyword + semantic) search.
  2. Traverses graph edges (CALLS, CONTAINS, IMPORTS) 1-2 hops to pull in context.
  3. Returns a ranked list of nodes with explicit reasoning traces for each retrieval step.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from search import SearchIndex


class GraphRetriever:
    """
    Combines hybrid search with graph neighborhood traversal.
    """

    def __init__(self, graph_path: str = "graph.json", index_dir: str = ".") -> None:
        self.graph_path = graph_path
        self.index_dir = index_dir

        with open(graph_path, "r", encoding="utf-8") as f:
            self.graph = json.load(f)

        # Build fast lookup indexes
        self.nodes_by_id: dict[str, dict[str, Any]] = {n["id"]: n for n in self.graph["nodes"]}

        # Adjacency lists for graph expansion
        self.outgoing_edges: dict[str, list[dict[str, Any]]] = {} # source_id -> [edge]
        self.incoming_edges: dict[str, list[dict[str, Any]]] = {} # target_id -> [edge]

        for edge in self.graph["edges"]:
            src = edge["source"]
            tgt = edge["target"]
            self.outgoing_edges.setdefault(src, []).append(edge)
            self.incoming_edges.setdefault(tgt, []).append(edge)

        # Initialize search index
        self.search_index = SearchIndex()
        if (Path(index_dir) / "search_index.json").exists():
            self.search_index.load(self.graph, input_dir=index_dir)
        else:
            self.search_index.build_from_graph(self.graph, embed=True)
            self.search_index.save(output_dir=index_dir)

    def retrieve(
        self,
        query: str,
        top_k_seeds: int = 5,
        max_hops: int = 1,
        max_total_nodes: int = 12,
    ) -> dict[str, Any]:
        """
        Perform graph-aware retrieval for a query.

        Returns:
            {
              "query": str,
              "nodes": list of node dicts (ranked with score & retrieval_reason),
              "reasoning_trace": list of strings describing retrieval steps
            }
        """
        reasoning_trace: list[str] = []
        retrieved_map: dict[str, dict[str, Any]] = {} # node_id -> {node, score, reason, hop}

        reasoning_trace.append(f"Step 1: Running hybrid search (keyword + semantic) for query: '{query}'")

        # 1. Seed search
        seeds = self.search_index.hybrid_search(query, top_k=top_k_seeds)
        if not seeds:
            reasoning_trace.append("No seed nodes matched the search criteria.")
            return {
                "query": query,
                "nodes": [],
                "reasoning_trace": reasoning_trace,
            }

        for idx, seed in enumerate(seeds, 1):
            n = seed["node"]
            score = seed["score"]
            reason = f"Seed match #{idx} (score={score:.1f}): {seed['match_reason']}"
            reasoning_trace.append(f"  Found seed node [{n['type']}] {n.get('qualified_name') or n['name']} in {n['file']} ({reason})")
            retrieved_map[n["id"]] = {
                "node": n,
                "score": score,
                "reason": reason,
                "hop": 0,
            }

        # 2. Graph expansion (1 to max_hops)
        for hop in range(1, max_hops + 1):
            reasoning_trace.append(f"Step {hop + 1}: Expanding graph neighborhood (Hop {hop})")
            current_ids = [nid for nid, item in retrieved_map.items() if item["hop"] == hop - 1]

            new_additions = 0
            for nid in current_ids:
                curr_item = retrieved_map[nid]
                curr_node = curr_item["node"]
                base_score = curr_item["score"]

                # Outgoing edges (e.g. CONTAINS children, CALLS target, IMPORTS target)
                for edge in self.outgoing_edges.get(nid, []):
                    target_id = edge["target"]
                    edge_type = edge["type"]
                    if target_id not in self.nodes_by_id:
                        continue

                    target_node = self.nodes_by_id[target_id]
                    decay = 0.7 if edge_type == "CONTAINS" else (0.6 if edge_type == "CALLS" else 0.4)
                    new_score = base_score * decay

                    reason = f"Hop {hop} via {edge_type} from [{curr_node['type']}] {curr_node.get('qualified_name') or curr_node['name']}"

                    if target_id not in retrieved_map or retrieved_map[target_id]["score"] < new_score:
                        retrieved_map[target_id] = {
                            "node": target_node,
                            "score": new_score,
                            "reason": reason,
                            "hop": hop,
                        }
                        reasoning_trace.append(f"  Expanded -> [{target_node['type']}] {target_node.get('qualified_name') or target_node['name']} ({reason})")
                        new_additions += 1

                # Incoming edges (e.g. CONTAINS parent class/file, caller function)
                for edge in self.incoming_edges.get(nid, []):
                    src_id = edge["source"]
                    edge_type = edge["type"]
                    if src_id not in self.nodes_by_id:
                        continue

                    src_node = self.nodes_by_id[src_id]
                    # Parent containers or callers are valuable context
                    decay = 0.75 if edge_type == "CONTAINS" else (0.65 if edge_type == "CALLS" else 0.4)
                    new_score = base_score * decay

                    reason = f"Hop {hop} incoming {edge_type} from [{src_node['type']}] {src_node.get('qualified_name') or src_node['name']}"

                    if src_id not in retrieved_map or retrieved_map[src_id]["score"] < new_score:
                        retrieved_map[src_id] = {
                            "node": src_node,
                            "score": new_score,
                            "reason": reason,
                            "hop": hop,
                        }
                        reasoning_trace.append(f"  Expanded -> [{src_node['type']}] {src_node.get('qualified_name') or src_node['name']} ({reason})")
                        new_additions += 1

            if new_additions == 0:
                reasoning_trace.append(f"  No new nodes discovered in Hop {hop}.")

        # 3. Sort and cap results
        sorted_items = sorted(retrieved_map.values(), key=lambda x: x["score"], reverse=True)
        final_items = sorted_items[:max_total_nodes]

        ranked_nodes = []
        for item in final_items:
            n = dict(item["node"])
            n["retrieval_score"] = round(item["score"], 2)
            n["retrieval_reason"] = item["reason"]
            n["hop"] = item["hop"]
            ranked_nodes.append(n)

        reasoning_trace.append(f"Retrieved {len(ranked_nodes)} total context nodes for LLM synthesis.")

        return {
            "query": query,
            "nodes": ranked_nodes,
            "reasoning_trace": reasoning_trace,
        }


# ═══════════════════════════════════════════════════════════════════════
# CLI Entry Point for testing
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python retriever.py '<question>' [graph.json]")
        sys.exit(1)

    query = sys.argv[1]
    g_path = sys.argv[2] if len(sys.argv) > 2 else "graph.json"

    retriever = GraphRetriever(graph_path=g_path)
    res = retriever.retrieve(query)

    print(f"\n🔍 Graph Retrieval for: '{res['query']}'\n")
    print("--- REASONING TRACE ---")
    for step in res["reasoning_trace"]:
        print(f"  {step}")

    print("\n--- RETRIEVED NODES ---")
    for i, n in enumerate(res["nodes"], 1):
        name = n.get("qualified_name") or n["name"]
        print(f"{i:2d}. [{n['type']:8s}] {name:40s} | {n['file']}:{n.get('line_start','?')} | score={n['retrieval_score']}")
        print(f"    Reason: {n['retrieval_reason']}")
