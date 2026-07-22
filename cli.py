"""
cli.py — Command-Line Interface for RepoGraph AI.

Usage:
  python cli.py index <repo_path> [output_dir]
    — Runs repo ingestion, graph construction, and search index embedding.
      Generates graph.json, SCHEMA.md reference, and search_index.json / embeddings.npy.

  python cli.py ask "<question>" [--json]
    — Performs graph-aware retrieval and LLM synthesis.
      Outputs answer, citations, confidence score, and reasoning trace.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from answerer import LLMAnswerer
from graph_builder import build_graph, print_summary, save_graph
from parser import parse_repo
from retriever import GraphRetriever
from search import SearchIndex


def cmd_index(repo_path: str, output_dir: str = ".") -> None:
    """Index a repository: parse -> graph -> search index."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    g_path = str(out_dir / "graph.json")

    print(f"🚀 [1/3] Ingesting repository Python files: {repo_path}")
    parsed = parse_repo(repo_path)
    print(f"   Parsed {len(parsed)} Python source files.")

    print(f"\n🕸  [2/3] Building Knowledge Graph (File, Class, Function nodes)...")
    graph = build_graph(parsed)
    print_summary(graph)
    save_graph(graph, g_path)

    print(f"\n🔍 [3/3] Building hybrid search index & semantic embeddings...")
    idx = SearchIndex()
    idx.build_from_graph(graph, embed=True)
    idx.save(str(out_dir))

    print(f"\n✅ Indexing complete! RepoGraph AI is ready for questions.")


def cmd_ask(question: str, graph_path: str = "graph.json", json_output: bool = False) -> None:
    """Ask a question about the indexed codebase."""
    if not Path(graph_path).exists():
        print(f"❌ Error: {graph_path} not found. Please run 'python cli.py index <repo_path>' first.")
        sys.exit(1)

    # 1. Graph Retrieval
    retriever = GraphRetriever(graph_path=graph_path)
    retrieved = retriever.retrieve(question)

    # 2. LLM Synthesis
    answerer = LLMAnswerer()
    result = answerer.answer(question, retrieved)

    if json_output:
        print(json.dumps(result, indent=2, default=str))
        return

    # Pretty print CLI output
    print("\n" + "═" * 70)
    print(f"❓ QUESTION: {result['question']}")
    print("═" * 70)
    print(f"📊 CONFIDENCE SCORE: {result['confidence']:.2f} / 1.0")
    print(f"💡 CONFIDENCE REASON: {result['confidence_justification']}")

    print("\n📝 ANSWER & CITATIONS:")
    print("-" * 70)
    print(result["answer"])

    print("\n📍 SOURCES & CITATIONS:")
    print("-" * 70)
    if result["sources"]:
        for s in result["sources"]:
            print(f"  • {s['file']}:{s['symbol']}:L{s.get('line', '?')}")
    else:
        print("  (No sources — insufficient evidence)")

    print("\n🧠 REASONING TRACE:")
    print("-" * 70)
    for step in result["reasoning_trace"]:
        print(f"  {step}")
    print("═" * 70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("RepoGraph AI CLI")
        print("Usage:")
        print("  python cli.py index <repo_path>")
        print("  python cli.py ask \"<question>\" [--json]")
        sys.exit(1)

    command = sys.argv[1]

    if command == "index":
        if len(sys.argv) < 3:
            print("Usage: python cli.py index <repo_path>")
            sys.exit(1)
        cmd_index(sys.argv[2])

    elif command == "ask":
        if len(sys.argv) < 3:
            print("Usage: python cli.py ask \"<question>\" [--json]")
            sys.exit(1)
        question = sys.argv[2]
        as_json = "--json" in sys.argv
        cmd_ask(question, json_output=as_json)

    else:
        print(f"Unknown command: {command}")
        print("Valid commands: index, ask")
        sys.exit(1)
