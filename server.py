"""
server.py — FastAPI Web Server & REST API for RepoGraph AI.

Endpoints:
  - GET  /api/health       — System status
  - GET  /api/graph/stats  — Graph metadata, node & edge counts
  - GET  /api/graph/nodes  — Filterable node directory (query, type, file)
  - GET  /api/graph/vis    — Visualizer payload (nodes & edges for network graph)
  - POST /api/ask          — Q&A endpoint (runs graph retrieval + answer synthesis)
  - POST /api/index        — Trigger re-indexing of target repository
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from answerer import LLMAnswerer
from graph_builder import build_graph, save_graph
from parser import parse_repo
from retriever import GraphRetriever
from search import SearchIndex

app = FastAPI(title="RepoGraph AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GRAPH_FILE = "graph.json"


class AskRequest(BaseModel):
    question: str


class IndexRequest(BaseModel):
    repo_path: str = "target_repo"


def load_graph() -> dict[str, Any]:
    if not Path(GRAPH_FILE).exists():
        raise HTTPException(status_code=404, detail="Knowledge graph not found. Please index a repository first.")
    with open(GRAPH_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/health")
def health() -> dict[str, Any]:
    has_graph = Path(GRAPH_FILE).exists()
    return {
        "status": "healthy",
        "graph_indexed": has_graph,
        "pinned_repo": "pallets/flask",
        "commit_hash": "36e4a824f340fdee7ed50937ba8e7f6bc7d17f81",
    }


@app.get("/api/graph/stats")
def graph_stats() -> dict[str, Any]:
    graph = load_graph()
    meta = graph.get("metadata", {})
    return {
        "metadata": meta,
        "pinned_commit": "36e4a824f340fdee7ed50937ba8e7f6bc7d17f81",
        "repo": "pallets/flask",
    }


@app.get("/api/graph/nodes")
def graph_nodes(
    q: str | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    graph = load_graph()
    nodes = graph.get("nodes", [])

    filtered = []
    for n in nodes:
        if type and n.get("type") != type:
            continue
        if q:
            name = n.get("qualified_name") or n.get("name", "")
            fpath = n.get("file", "")
            if q.lower() not in name.lower() and q.lower() not in fpath.lower():
                continue
        filtered.append(n)

    return {
        "total_matched": len(filtered),
        "nodes": filtered[:limit],
    }


@app.get("/api/graph/vis")
def graph_vis(limit_nodes: int = 300) -> dict[str, Any]:
    """Returns graph nodes and edges optimized for interactive network visualization."""
    graph = load_graph()
    all_nodes = graph.get("nodes", [])
    all_edges = graph.get("edges", [])

    # Select representative nodes, deduplicating by ID
    seen_ids = set()
    selected_nodes = []
    for n in all_nodes:
        if n["id"] not in seen_ids and len(selected_nodes) < limit_nodes:
            seen_ids.add(n["id"])
            selected_nodes.append(n)

    selected_ids = {n["id"] for n in selected_nodes}

    vis_nodes = []
    for n in selected_nodes:
        vis_nodes.append({
            "id": n["id"],
            "label": n.get("name"),
            "group": n.get("type"),
            "title": f"[{n['type']}] {n.get('qualified_name') or n['name']}\nFile: {n['file']}:{n.get('line_start','?')}",
            "file": n.get("file"),
            "line": n.get("line_start"),
        })

    vis_edges = []
    for e in all_edges:
        if e["source"] in selected_ids and e["target"] in selected_ids:
            vis_edges.append({
                "from": e["source"],
                "to": e["target"],
                "label": e["type"],
                "type": e["type"],
            })

    return {
        "nodes": vis_nodes,
        "edges": vis_edges[:600],
    }


@app.get("/api/graph/node")
def get_node_detail(id: str = Query(..., description="Node ID to inspect")) -> dict[str, Any]:
    """Return full node properties and all connected edges for a given node ID."""
    node_id = id
    graph = load_graph()
    all_nodes = graph.get("nodes", [])
    all_edges = graph.get("edges", [])

    node = None
    for n in all_nodes:
        if n["id"] == node_id:
            node = n
            break

    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")

    # Gather all edges connected to this node
    connected_edges = []
    neighbor_ids = set()
    for e in all_edges:
        if e["source"] == node_id or e["target"] == node_id:
            connected_edges.append(e)
            neighbor_ids.add(e["source"] if e["target"] == node_id else e["target"])

    # Gather neighbor node summaries
    neighbors = []
    for n in all_nodes:
        if n["id"] in neighbor_ids:
            neighbors.append({
                "id": n["id"],
                "type": n.get("type"),
                "name": n.get("name"),
                "qualified_name": n.get("qualified_name"),
                "file": n.get("file"),
            })

    return {
        "node": node,
        "edges": connected_edges,
        "neighbors": neighbors,
    }


class AddNodeRequest(BaseModel):
    type: str  # File, Class, or Function
    name: str
    file: str
    line_start: int = 1
    line_end: int | None = None
    qualified_name: str | None = None
    signature: str | None = None
    docstring: str | None = None
    bases: list[str] | None = None


@app.post("/api/graph/nodes")
def add_node(req: AddNodeRequest) -> dict[str, Any]:
    """Add a new node to graph.json and return the created node."""
    if req.type not in ("File", "Class", "Function"):
        raise HTTPException(status_code=400, detail="Node type must be File, Class, or Function.")

    graph = load_graph()
    nodes = graph.get("nodes", [])

    # Generate a unique ID
    node_id = f"{req.type.lower()}:{req.file}:{req.name}"
    for n in nodes:
        if n["id"] == node_id:
            raise HTTPException(status_code=409, detail=f"Node '{node_id}' already exists.")

    new_node = {
        "id": node_id,
        "type": req.type,
        "name": req.name,
        "qualified_name": req.qualified_name or req.name,
        "file": req.file,
        "line_start": req.line_start,
        "line_end": req.line_end,
        "signature": req.signature,
        "docstring": req.docstring,
    }

    if req.type == "Class" and req.bases:
        new_node["bases"] = req.bases

    nodes.append(new_node)

    # Update metadata counts
    meta = graph.get("metadata", {})
    meta["total_nodes"] = len(nodes)
    nc = meta.get("node_counts", {})
    nc[req.type] = nc.get(req.type, 0) + 1
    meta["node_counts"] = nc
    graph["metadata"] = meta
    graph["nodes"] = nodes

    with open(GRAPH_FILE, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2)

    return {
        "message": f"Node '{node_id}' created successfully.",
        "node": new_node,
        "total_nodes": meta["total_nodes"],
    }


@app.post("/api/ask")
def ask_question(req: AskRequest) -> dict[str, Any]:
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    retriever = GraphRetriever(graph_path=GRAPH_FILE)
    retrieved = retriever.retrieve(req.question)

    answerer = LLMAnswerer()
    result = answerer.answer(req.question, retrieved)

    return result


@app.post("/api/index")
def trigger_index(req: IndexRequest) -> dict[str, Any]:
    if not Path(req.repo_path).exists():
        raise HTTPException(status_code=404, detail=f"Repo path '{req.repo_path}' does not exist.")

    parsed = parse_repo(req.repo_path)
    graph = build_graph(parsed)
    save_graph(graph, GRAPH_FILE)

    idx = SearchIndex()
    idx.build_from_graph(graph, embed=True)
    idx.save(".")

    return {
        "message": "Indexing completed successfully.",
        "metadata": graph["metadata"],
    }


# Serve static web application frontend if built
if Path("static").exists():
    if Path("static/assets").exists():
        app.mount("/assets", StaticFiles(directory="static/assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api"):
            raise HTTPException(status_code=404)
        file_path = Path("static") / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
