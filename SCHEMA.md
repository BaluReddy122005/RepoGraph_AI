# RepoGraph AI — Knowledge Graph Schema

This document describes every node type, edge type, attribute, exclusion rule, and route/config representation in the knowledge graph persisted as `graph.json`.

---

## Target Repository Scope

- **Repository**: `pallets/flask` (commit `36e4a824f340fdee7ed50937ba8e7f6bc7d17f81`)
- **Scope Metrics**: **82 parsed files** | **18,236 lines of code**
- **Graph Size**: **998 Nodes** | **2,360 Edges**

---

## Explicit Ingestion & Exclusion Rules

During repository ingestion (`parser.py` & `graph_builder.py`), files are scanned according to explicit rules:

### Included Files
- All Python source files (`*.py`) in the repository core (`src/flask/`), test suite (`tests/`), and example applications (`examples/`).

### Excluded Files & Directories
- `docs/` — Excluded because Sphinx documentation configuration and doc build scripts are not part of the application source code.
- `ext/` or vendored third-party dependencies — Excluded to prevent indexing non-first-party library code.
- `__pycache__/` & hidden directories (`.*`) — Excluded to ignore temporary byte-compiled artifacts and `.git` internal metadata.

---

## Route Definitions & Config Representation in Graph

### Route Representation
- **Attributes on Function / Method Nodes**:
  - `is_route` (`boolean`): `true` if the function or method is decorated with a web framework route decorator (e.g. `@app.route`, `@bp.route`, `@bp.get`, `@bp.post`, `@app.errorhandler`, `@app.before_request`, `@app.after_request`).
  - `route_decorators` (`string[]`): List of matching route decorator expression strings attached to the function (e.g. `["bp.get"]`, `["app.route", "app.route"]`).
- **Graph Coverage**: 41 function nodes across `pallets/flask` are explicitly flagged with `is_route=true` and populated `route_decorators`.

### Config Constants & Config Handlers Representation
- **Attributes on File Nodes**:
  - `config_constants` (`object[]`): List of `{name, value, line}` objects representing module-level literal constant assignments parsed from AST `Assign` and `AnnAssign` nodes.
- **Attributes on Function Nodes**:
  - `is_config` (`boolean`): `true` if the function or containing class handles configuration loading (e.g. `Config.from_object`, `Config.from_pyfile`, `Config.from_mapping`, `make_config`).
- **Graph Coverage**: 45 function nodes flagged with `is_config=true` and 3 File nodes with populated `config_constants`.

---

## Node Types & Attributes

### File

Represents a Python source file in the repository.

| Attribute         | Type       | Description                                    | Example                            |
|------------------|------------|------------------------------------------------|------------------------------------|
| `id`             | `string`   | Unique identifier: `file:<path>`               | `"file:src/flask/app.py"`          |
| `type`           | `string`   | Always `"File"`                                | `"File"`                           |
| `name`           | `string`   | Base filename                                  | `"app.py"`                         |
| `file`           | `string`   | Relative path from repo root                   | `"src/flask/app.py"`               |
| `line_start`     | `integer`  | Always `1`                                     | `1`                                |
| `line_end`       | `integer?` | `null` (file-level node)                       | `null`                             |
| `docstring`      | `string?`  | `null` (files don't have docstrings in nodes)  | `null`                             |
| `signature`      | `string?`  | `null` (not applicable)                        | `null`                             |
| `config_constants`| `object[]`| List of `{name, value, line}` constants        | `[{"name": "TEST_KEY", ...}]`     |

### Class

Represents a Python class definition.

| Attribute    | Type       | Description                                    | Example                               |
|-------------|------------|------------------------------------------------|---------------------------------------|
| `id`        | `string`   | Unique identifier: `class:<path>:<name>`       | `"class:src/flask/app.py:Flask"`      |
| `type`      | `string`   | Always `"Class"`                               | `"Class"`                              |
| `name`      | `string`   | Class name                                     | `"Flask"`                             |
| `file`      | `string`   | File containing the class                      | `"src/flask/app.py"`                  |
| `line_start`| `integer`  | First line of class definition                 | `108`                                 |
| `line_end`  | `integer`  | Last line of class definition                  | `1890`                                |
| `docstring` | `string?`  | Class docstring, if present                    | `"The flask object implements..."`    |
| `signature` | `string?`  | `null` (not applicable to classes)             | `null`                                 |
| `bases`     | `string[]` | Base class names                               | `["App"]`                             |
| `decorators`| `string[]` | Decorator names                                | `[]`                                   |

### Function

Represents a function or method definition.

| Attribute         | Type       | Description                                    | Example                                        |
|------------------|------------|------------------------------------------------|------------------------------------------------|
| `id`             | `string`   | Unique ID: `func:<path>:<class>.<name>`        | `"func:src/flask/app.py:Flask.route"`          |
| `type`           | `string`   | Always `"Function"`                            | `"Function"`                                    |
| `name`           | `string`   | Function/method name                           | `"route"`                                      |
| `qualified_name` | `string`   | `ClassName.method` or just `func_name`         | `"Flask.route"`                                |
| `file`           | `string`   | File containing the function                   | `"src/flask/app.py"`                        |
| `line_start`     | `integer`  | First line of function definition              | `1280`                                         |
| `line_end`       | `integer`  | Last line of function definition               | `1310`                                         |
| `docstring`      | `string?`  | Function docstring, if present                 | `"A decorator that is used to register..."`     |
| `signature`      | `string`   | Human-readable signature                       | `"route(self, rule, **options)"`               |
| `class_parent`   | `string?`  | Name of containing class (null if top-level)   | `"Flask"`                                      |
| `is_async`       | `boolean`  | Whether it's an `async def`                    | `false`                                         |
| `decorators`     | `string[]` | Decorator names                                | `["setupmethod"]`                              |
| `args`           | `string[]` | Argument names (with `*`/`**` prefixes)        | `["self", "rule", "**options"]`                |
| `is_route`       | `boolean`  | `true` if node has route decorator             | `true`                                         |
| `route_decorators`| `string[]`| Matching route decorator expressions           | `["bp.get"]`                                   |
| `is_config`      | `boolean`  | `true` if node handles config loading          | `false`                                        |

---

## Edge Types

### CONTAINS

Structural containment relationship.

| Attribute | Type     | Description                                    |
|-----------|----------|------------------------------------------------|
| `source`  | `string` | Parent node ID                                 |
| `target`  | `string` | Child node ID                                  |
| `type`    | `string` | Always `"CONTAINS"`                            |

Valid source→target combinations:
- **File → Class**: File contains a class definition
- **File → Function**: File contains a top-level function
- **Class → Function**: Class contains a method

### CALLS

Function-to-function call relationship (best-effort static resolution).

| Attribute        | Type     | Description                                    |
|-----------------|----------|------------------------------------------------|
| `source`        | `string` | Caller function ID                             |
| `target`        | `string` | Callee function ID                             |
| `type`          | `string` | Always `"CALLS"`                               |
| `call_expression`| `string`| Original call expression from AST              |

### IMPORTS

File-to-file import dependency.

| Attribute | Type     | Description                                    |
|-----------|----------|------------------------------------------------|
| `source`  | `string` | Importing file ID                              |
| `target`  | `string` | Imported file ID                               |
| `type`    | `string` | Always `"IMPORTS"`                             |
| `module`  | `string` | Original import module string                  |

---

## Unresolved Calls

Calls that could not be statically resolved to a known function in the repo (e.g. calls to third-party packages like Werkzeug, Click, Jinja2, or dynamic method dispatch).

| Attribute        | Type     | Description                                    |
|-----------------|----------|------------------------------------------------|
| `caller`        | `string` | ID of the function that makes the call         |
| `call_expression`| `string`| The call expression that could not be resolved |
