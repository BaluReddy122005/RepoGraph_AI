# RepoGraph AI — Code Understanding Assistant

**RepoGraph AI** is a developer assistant that understands codebases by constructing a semantic knowledge graph using pure AST parsing, executing hybrid retrieval (keyword string matching + dense vector similarity + graph neighborhood edge expansion), and synthesizing natural-language answers with mandatory, traceable `[file:symbol:line]` citations.

---

## 🎯 Target Repository Scope & Pinned Commit

- **Target Repository**: [`pallets/flask`](https://github.com/pallets/flask)
- **Pinned Commit Hash**: `36e4a824f340fdee7ed50937ba8e7f6bc7d17f81`
- **Scope Metrics**: **82 parsed files** across **18,236 lines of code** (satisfies the required 50–300 files and 5k–30k lines of code constraint).
- **AST Ingestion Engine**: 100% parsed using Python's native `ast` module (`parser.py`, zero regex parsing).
- **Knowledge Graph Size**: **974 Nodes** (82 `File`, 63 `Class`, 829 `Function`) and **2,360 Edges** (916 `CONTAINS`, 1,305 `CALLS`, 139 `IMPORTS`). Persisted as `graph.json` and included in submission unexcerpted.

---

## 🚀 Quickstart & Setup Guide

### 1. Installation

Install all required Python dependencies:

```bash
pip install -r requirements.txt
```

### 2. Reproduce & Index Target Repository

To clone the pinned target repository and build the graph and search index from scratch:

```bash
# Clone pinned commit
git clone https://github.com/pallets/flask.git target_repo
cd target_repo && git checkout 36e4a824f340fdee7ed50937ba8e7f6bc7d17f81 && cd ..

# Run ingestion, graph building, and embedding indexer
python3 cli.py index target_repo
```

This generates:
- `graph.json` — Persisted knowledge graph.
- `search_index.json` & `embeddings.npy` — Hybrid dense vector (`sentence-transformers/all-MiniLM-L6-v2`) and keyword index.

---

## 💻 CLI Interface

Ask natural language questions about the codebase using `cli.py ask`:

```bash
python3 cli.py ask "Which functions are registered as HTTP routes, and where are application configuration constants populated?"
```

For structured JSON output (ideal for programmatic integration and testing):
```bash
python3 cli.py ask "Explain how application context and request context are created and pushed." --json
```

### CLI Output Anatomy
Every response includes:
1. **Grounded Answer**: Prose with mandatory embedded inline `[file:symbol:line]` citations.
2. **Confidence Score**: Dynamic score (0.0 to 1.0) with justification.
3. **Traceable Sources**: Verified source pointer list (`file:symbol:line`).
4. **Reasoning Trace**: Step-by-step log of seed retrieval and 1–2 hop graph neighborhood traversal.

---

## 🌐 Web Application & REST API

RepoGraph AI includes a React + Vite web application with a 3D WebGL force-directed graph visualizer, Ask AI prompt launcher, node inspector panel, and searchable directory.

Start the web server:

```bash
python3 server.py
```

Open your browser at: **`http://localhost:8000`**

### Key REST API Endpoints
- `GET  /api/graph/stats` — Node & edge count metrics.
- `GET  /api/graph/nodes` — Searchable & filterable AST node directory.
- `GET  /api/graph/node?id=...` — Node properties, docstrings, and connected edges.
- `POST /api/graph/nodes` — Add new nodes dynamically.
- `GET  /api/graph/vis` — WebGL 3D network visualization payload.
- `POST /api/ask` — Natural language query synthesis with citations.

---

## 📸 Recommended Screenshots Guide for Evaluation Submission

To demonstrate your submission, capture **5 key screenshots** from the running CLI and Web UI:

| # | Screenshot Name | What to Capture & How to Take It | What it Demonstrates |
|---|---|---|---|
| **1** | `01_cli_query_citations.png` | Run `python3 cli.py ask "Which functions are registered as HTTP routes..."` in your terminal. Take a screenshot showing the answer prose, inline `[file:symbol:line]` citations, and dynamic confidence score. | **Requirement 4 & 5**: Grounded Q&A with strict citations, confidence scoring, and source list. |
| **2** | `02_cli_reasoning_trace.png` | Scroll down on the same CLI output to capture the **Reasoning Trace** section showing seed matching and 1-2 hop graph edge traversal steps. | **Requirement 5**: Explainability & transparent retrieval trace. |
| **3** | `03_out_of_scope_idk.png` | Run `python3 cli.py ask "Which functions publish Kafka event messages?"`. Capture the response showing **0.0 confidence** and the explicit **"I don't know"** fallback answer. | **Evaluation Safeguard**: Failure handling without hallucinating plausible code. |
| **4** | `04_web_3d_graph_explorer.png` | Open `http://localhost:8000`, click the **Graph Explorer** tab, and take a screenshot of the **3D WebGL Force Graph** showing floating nodes, labels, and connecting directional arrows. | **Bonus**: 3D WebGL knowledge graph visualizer (`3d-force-graph` + Three.js). |
| **5** | `05_web_node_inspector.png` | Click on any node sphere (e.g. `Flask` class or `app.py`) in the 3D graph to open the **Node Inspector Panel** on the right side. Capture the node properties, line range, docstrings, and connected edges list. | **Graph Structure**: Inspection of node attributes, signatures, and graph relationships. |

---

## 📄 Required Assessment Documentation

The following required documentation files are included in this repository:

1. [./ARCHITECTURE.md](./ARCHITECTURE.md) — End-to-end architecture diagram, data flow, component breakdown, and hybrid score fusion strategy.
2. [./SCHEMA.md](./SCHEMA.md) — Formal graph schema specification detailing node types (`File`, `Class`, `Function`), edge types (`CONTAINS`, `CALLS`, `IMPORTS`), and route/config attributes.
3. [./qa_examples.md](./qa_examples.md) — 10 actual, unedited system Q&A evaluation pairs generated by `run_eval.py` (including 2 out-of-scope negative test cases).
4. [./DESIGN_AND_LIMITATIONS.md](./DESIGN_AND_LIMITATIONS.md) — Design choices, trade-offs, empirical failure modes (e.g., Werkzeug `LocalProxy` dynamic dispatch), and LLM usage disclosure statement.
