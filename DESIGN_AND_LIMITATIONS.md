# RepoGraph AI — Design Decisions & Limitations Document

## Target Repository Scope & Graph Size

- **Repository**: `pallets/flask` (pinned commit `36e4a824f340fdee7ed50937ba8e7f6bc7d17f81`)
- **Scope Metrics**: **82 parsed files** | **18,236 lines of code**
- **Graph Size**: **998 Nodes** | **2,360 Edges**
- **Submission Artifact**: The complete `graph.json` file is included in this submission as-is (unexcerpted, 998 nodes and 2,360 edges).

---

## 1. Key Architecture Decisions & Rationale

### AST Parsing over Regex
We strictly used Python's native `ast` module (in `parser.py`) rather than regular expressions. Code structures such as nested class definitions, method decorators, type hints, and docstrings cannot be accurately parsed with regex without introducing fragile edge-case bugs. `ast` provides exact syntax tree nodes, line start/end bounds (`lineno`, `end_lineno`), and precise symbol definitions.

### Hybrid Retrieval Strategy (Keyword + Semantic Vector + Graph Expansion)
Pure vector search often misses exact symbol names (e.g. `Flask.route` or `RequestContext.push`), while pure keyword search misses conceptual queries ("Explain how application context is pushed"). We implemented a documented score fusion approach combining:
1. **RapidFuzz Keyword Match**: Fuzzy & exact symbol lookup on node names, docstrings, and signatures.
2. **Dense Vector Embeddings**: `sentence-transformers` (`all-MiniLM-L6-v2`) generating 384-dimensional dense vectors for node names + docstrings + signatures.
3. **Score Fusion**: Weighted combination (`0.4 * keyword_score + 0.6 * semantic_score`).
4. **Graph Neighborhood Traversal**: 1–2 hop edge expansion via `CONTAINS`, `CALLS`, and `IMPORTS` edges to retrieve parent classes, callers/callees, and imported module contexts.

### Single-File JSON Persistence over Graph Databases
For codebases in the 5k–30k line range (such as `pallets/flask`), using complex graph databases like Neo4j or ArangoDB adds heavy operational overhead without latency benefits. Storing `graph.json` with in-memory graph traversal delivers sub-millisecond graph queries while keeping the deployment footprint minimal and zero-dependency.

### Strict Citation Enforcement & Low-Confidence Safeguard
The prompt and synthesizer strictly enforce inline citations (`[file:symbol:line]`). If top retrieval scores fall below a minimum score threshold or if the query refers to unindexed out-of-scope concepts (e.g. Kafka event publishing or WebSocket frame parsing), the system returns confidence `< 0.3` and explicitly answers: *"I don't know — there is no evidence of this feature in the codebase."* This prevents hallucination.

---

## 2. What Was Deliberately Cut & Future Roadmap

### Deliberately Cut
1. **Incremental Diff Indexing**: Re-indexing computes the full graph in ~4 seconds for 82 files. Incremental re-indexing on git diffs was omitted to prioritize robust graph traversal and citation quality.
2. **Multi-Tenant Auth & Production Deployment**: Omitted per the assessment scope guidelines.
3. **Multi-Language Parsing**: Focused 100% on Python AST depth rather than shallow regex/heuristics across multiple languages.

### Next Features to Build
1. **Tree-Sitter Polyglot Integration**: Replace Python `ast` with `tree-sitter` bindings to support TypeScript, Go, and Rust.
2. **Dynamic LocalProxy Resolution via Type Inference**: Statically resolving dynamic Flask proxies (`current_app`, `g`, `request`, `session`) is limited. Integrating Pyright / Mypy type-check artifacts would increase `CALLS` edge accuracy from ~60% to 95%+.
3. **Incremental Git Hook Indexer**: Compute git diffs on `post-commit` to update only modified AST nodes in `graph.json`.

---

## 3. Known Failure Modes Observed in Evaluation

During Step 7 evaluation across 10 queries on `pallets/flask`, we observed the following specific empirical failure modes:

1. **Werkzeug / Flask LocalProxy Indirect Calls**:
   - Flask relies heavily on dynamic thread-local proxies (`current_app`, `g`, `request`, `session`). When code invokes `current_app.config.get(...)`, static AST call resolution captures `current_app.config.get` as an unresolved call because `current_app` is a proxy object instantiated at runtime via `Werkzeug.local.LocalProxy`.
2. **Decorator-Wrapped View Dispatching**:
   - Methods decorated with `@app.route` or `@setupmethod` wrap the underlying function in closure objects. Static call graph resolution identifies the decorator function call rather than the wrapped view callback inside the routing map.
3. **Module Facade Re-exports (`flask/__init__.py`)**:
   - `flask/__init__.py` re-exports public API symbols (`Blueprint`, `Flask`, `request`, `render_template`, `jsonify`). High-level queries matching `Flask` occasionally retrieve the re-export line in `__init__.py` alongside the core class definition in `src/flask/app.py`.

---

## 4. AI Assistance Statement

In accordance with assignment disclosure guidelines: **Claude (Anthropic)** assisted in writing python code, refactoring AST edge case handling, formatting markdown documentation, and designing the dark-mode glassmorphism Web UI for RepoGraph AI. All generated code and graph structures were empirically verified via automated test runs and CLI executions.
