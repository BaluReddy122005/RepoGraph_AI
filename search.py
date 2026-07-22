"""
search.py — Keyword + semantic vector search over the knowledge graph.

Supports:
  1. Exact keyword/symbol lookup on node names and docstrings
  2. Fuzzy keyword matching via rapidfuzz
  3. Semantic vector search via sentence-transformers (all-MiniLM-L6-v2)

The search index is built from graph.json and persisted alongside it.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from rapidfuzz import fuzz, process

# ═══════════════════════════════════════════════════════════════════════
# Search Index
# ═══════════════════════════════════════════════════════════════════════

class SearchIndex:
    """
    Combined keyword + semantic search index over knowledge graph nodes.
    """

    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.node_texts: list[str] = []          # name + docstring + signature for each node
        self.node_names: list[str] = []           # just names for fuzzy name matching
        self.embeddings: np.ndarray | None = None # semantic vectors
        self.model = None                         # sentence-transformers model (lazy loaded)

    def build_from_graph(self, graph: dict[str, Any], embed: bool = True) -> None:
        """
        Build the search index from a loaded graph.

        Args:
            graph: The knowledge graph dict (with 'nodes' key).
            embed: Whether to compute semantic embeddings.
        """
        self.nodes = graph["nodes"]
        self.node_texts = []
        self.node_names = []

        for node in self.nodes:
            # Build searchable text: name + docstring + signature
            parts = [node.get("name", "")]
            if node.get("qualified_name"):
                parts.append(node["qualified_name"])
            if node.get("docstring"):
                parts.append(node["docstring"])
            if node.get("signature"):
                parts.append(node["signature"])
            if node.get("file"):
                parts.append(node["file"])

            self.node_texts.append(" | ".join(filter(None, parts)))
            self.node_names.append(node.get("qualified_name") or node.get("name", ""))

        if embed:
            self._compute_embeddings()

    def _compute_embeddings(self) -> None:
        """Compute semantic embeddings for all nodes using sentence-transformers."""
        try:
            from sentence_transformers import SentenceTransformer

            print("Loading sentence-transformers model (all-MiniLM-L6-v2)...")
            t0 = time.time()
            self.model = SentenceTransformer("all-MiniLM-L6-v2")
            self.embeddings = self.model.encode(
                self.node_texts,
                show_progress_bar=True,
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            print(f"✓ Embedded {len(self.node_texts)} nodes in {time.time() - t0:.1f}s")
        except ImportError:
            print("⚠ sentence-transformers not installed. Semantic search disabled.")
            self.embeddings = None
        except Exception as exc:
            print(f"⚠ Embedding failed: {exc}. Semantic search disabled.")
            self.embeddings = None

    def save(self, output_dir: str = ".") -> None:
        """Save the search index (embeddings + node mapping) to disk."""
        out = Path(output_dir)
        # Save node index
        index_data = {
            "node_texts": self.node_texts,
            "node_names": self.node_names,
            "node_ids": [n["id"] for n in self.nodes],
        }
        with open(out / "search_index.json", "w") as f:
            json.dump(index_data, f)

        # Save embeddings as numpy binary
        if self.embeddings is not None:
            np.save(str(out / "embeddings.npy"), self.embeddings)
            print(f"✓ Search index saved ({len(self.nodes)} nodes, embeddings: {self.embeddings.shape})")
        else:
            print(f"✓ Search index saved ({len(self.nodes)} nodes, no embeddings)")

    def load(self, graph: dict[str, Any], input_dir: str = ".") -> None:
        """Load a previously saved search index."""
        inp = Path(input_dir)
        self.nodes = graph["nodes"]

        with open(inp / "search_index.json") as f:
            index_data = json.load(f)

        self.node_texts = index_data["node_texts"]
        self.node_names = index_data["node_names"]

        emb_path = inp / "embeddings.npy"
        if emb_path.exists():
            self.embeddings = np.load(str(emb_path))
        else:
            self.embeddings = None

    # ──────────────────────────────────────────────────────────────────
    # Search methods
    # ──────────────────────────────────────────────────────────────────

    def keyword_search(
        self,
        query: str,
        top_k: int = 20,
        threshold: float = 50.0,
    ) -> list[dict[str, Any]]:
        """
        Fuzzy keyword/symbol search over node names and docstrings.

        Returns a list of {node, score, match_reason} dicts.
        """
        results = []

        # 1. Exact substring match on node names (highest priority)
        query_lower = query.lower()
        for i, name in enumerate(self.node_names):
            if query_lower in name.lower():
                results.append({
                    "node": self.nodes[i],
                    "score": 100.0,
                    "match_reason": f"exact name match: '{name}' contains '{query}'",
                })

        # 2. Fuzzy match on node names
        if self.node_names:
            fuzzy_matches = process.extract(
                query,
                self.node_names,
                scorer=fuzz.WRatio,
                limit=top_k * 2,
            )
            seen_ids = {r["node"]["id"] for r in results}
            for match_name, score, idx in fuzzy_matches:
                if score >= threshold and self.nodes[idx]["id"] not in seen_ids:
                    results.append({
                        "node": self.nodes[idx],
                        "score": score * 0.9,  # Slightly lower than exact
                        "match_reason": f"fuzzy name match: '{match_name}' ≈ '{query}' (score={score:.0f})",
                    })

        # 3. Keyword search in full text (docstrings, signatures)
        query_tokens = set(query_lower.split())
        seen_ids = {r["node"]["id"] for r in results}
        for i, text in enumerate(self.node_texts):
            if self.nodes[i]["id"] in seen_ids:
                continue
            text_lower = text.lower()
            matching_tokens = sum(1 for t in query_tokens if t in text_lower)
            if matching_tokens > 0:
                token_score = (matching_tokens / len(query_tokens)) * 80
                if token_score >= threshold:
                    results.append({
                        "node": self.nodes[i],
                        "score": token_score,
                        "match_reason": f"keyword match in text: {matching_tokens}/{len(query_tokens)} tokens matched",
                    })

        # Sort by score, take top_k
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def semantic_search(
        self,
        query: str,
        top_k: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Semantic vector similarity search.

        Returns a list of {node, score, match_reason} dicts.
        """
        if self.embeddings is None:
            return []

        # Lazy-load model for query encoding
        if self.model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                return []

        # Encode query
        query_vec = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        # Cosine similarity (embeddings are already normalized)
        similarities = (self.embeddings @ query_vec.T).flatten()

        # Get top-k indices
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score > 0.05:  # Minimum relevance threshold
                results.append({
                    "node": self.nodes[idx],
                    "score": score * 100,  # Scale to 0-100 range
                    "match_reason": f"semantic similarity: cosine={score:.3f}",
                })

        return results

    def hybrid_search(
        self,
        query: str,
        top_k: int = 15,
        keyword_weight: float = 0.4,
        semantic_weight: float = 0.6,
    ) -> list[dict[str, Any]]:
        """
        Combined keyword + semantic search with score fusion.

        Returns a merged, ranked list of {node, score, match_reason, keyword_score, semantic_score}.
        """
        keyword_results = self.keyword_search(query, top_k=top_k * 2)
        semantic_results = self.semantic_search(query, top_k=top_k * 2)

        # Build score maps
        scores: dict[str, dict[str, Any]] = {}

        for r in keyword_results:
            nid = r["node"]["id"]
            scores[nid] = {
                "node": r["node"],
                "keyword_score": r["score"],
                "semantic_score": 0.0,
                "keyword_reason": r["match_reason"],
                "semantic_reason": "",
            }

        for r in semantic_results:
            nid = r["node"]["id"]
            if nid in scores:
                scores[nid]["semantic_score"] = r["score"]
                scores[nid]["semantic_reason"] = r["match_reason"]
            else:
                scores[nid] = {
                    "node": r["node"],
                    "keyword_score": 0.0,
                    "semantic_score": r["score"],
                    "keyword_reason": "",
                    "semantic_reason": r["match_reason"],
                }

        # Fuse scores
        results = []
        for nid, data in scores.items():
            fused = (
                keyword_weight * data["keyword_score"]
                + semantic_weight * data["semantic_score"]
            )
            reasons = []
            if data["keyword_reason"]:
                reasons.append(data["keyword_reason"])
            if data["semantic_reason"]:
                reasons.append(data["semantic_reason"])

            results.append({
                "node": data["node"],
                "score": fused,
                "match_reason": " + ".join(reasons),
                "keyword_score": data["keyword_score"],
                "semantic_score": data["semantic_score"],
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


# ═══════════════════════════════════════════════════════════════════════
# CLI entry point
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python search.py build [graph.json]          — build search index")
        print("  python search.py query '<query>' [graph.json] — test search")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "build":
        graph_path = sys.argv[2] if len(sys.argv) > 2 else "graph.json"
        with open(graph_path) as f:
            graph = json.load(f)

        idx = SearchIndex()
        idx.build_from_graph(graph, embed=True)
        idx.save(os.path.dirname(graph_path) or ".")

    elif cmd == "query":
        if len(sys.argv) < 3:
            print("Usage: python search.py query '<query>' [graph.json]")
            sys.exit(1)

        query = sys.argv[2]
        graph_path = sys.argv[3] if len(sys.argv) > 3 else "graph.json"

        with open(graph_path) as f:
            graph = json.load(f)

        idx = SearchIndex()
        idx.load(graph, os.path.dirname(graph_path) or ".")

        print(f"\n🔍 Hybrid search for: '{query}'\n")
        results = idx.hybrid_search(query, top_k=10)
        for i, r in enumerate(results, 1):
            n = r["node"]
            print(f"  {i:2d}. [{n['type']:8s}] {n.get('qualified_name') or n['name']}")
            print(f"      File: {n['file']}:{n.get('line_start', '?')}")
            print(f"      Score: {r['score']:.1f} (kw={r.get('keyword_score', 0):.1f}, sem={r.get('semantic_score', 0):.1f})")
            print(f"      Reason: {r['match_reason']}")
            print()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
