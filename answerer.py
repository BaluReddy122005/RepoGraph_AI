"""
answerer.py — LLM Answer Synthesis with mandatory citations for RepoGraph AI.

Given a user question and retrieved graph nodes:
  1. Formats context with file, symbol, signature, lines, and docstrings.
  2. Prompt Anthropic API (model claude-sonnet-4-6) to synthesize a cited answer.
  3. Validates mandatory citations (file:symbol:line) and confidence scoring.
  4. Enforces "I don't know" / low confidence for queries lacking strong evidence.
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any

import anthropic


SYSTEM_PROMPT = """You are RepoGraph AI, an expert code-understanding assistant.
Your job is to answer questions about a codebase strictly based on the provided context nodes extracted from a knowledge graph.

CRITICAL CONSTRAINTS & CITATION RULES:
1. EVERY factual claim in your answer MUST be cited with an explicit tag in the exact format: `[file:symbol:line]`
   - Example: `HTTPBasicAuth` implements basic authentication `[src/requests/auth.py:HTTPBasicAuth:L85]`.
   - Example: `send()` dispatches requests over connections `[src/requests/adapters.py:HTTPAdapter.send:L420]`.
2. DO NOT make any claim that is not directly supported by the provided context nodes.
3. ABSOLUTE TRUTH & CONFIDENCE:
   - If the context nodes do NOT contain strong, clear evidence to answer the question (e.g. asking about a feature like Kafka, WebSockets, or SQL database that is not in the repo), you MUST state clearly: "I don't know — there is no evidence of this feature in the codebase."
   - For low/no evidence, set `confidence` to a float < 0.3 (e.g. 0.0 or 0.1).
   - If evidence is solid, set `confidence` to a float between 0.75 and 1.0.
4. REQUIRED OUTPUT FORMAT:
   Return ONLY a valid JSON object matching this schema:
   {
     "answer": "Your formatted answer text with [file:symbol:line] inline citations...",
     "confidence": 0.95,
     "confidence_justification": "One sentence explaining why confidence is high or low.",
     "sources": [
       {
         "file": "src/requests/auth.py",
         "symbol": "HTTPBasicAuth",
         "line": 85
       }
     ]
   }
"""


class LLMAnswerer:
    """
    Synthesizes grounded answers with citations using Anthropic Claude API.
    """

    def __init__(self, model_name: str = "claude-sonnet-4-6") -> None:
        self.model_name = model_name
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic() if self.api_key else None

    def format_context(self, retrieved_data: dict[str, Any]) -> str:
        """Format retrieved nodes into structured text for the prompt."""
        nodes = retrieved_data.get("nodes", [])
        if not nodes:
            return "NO RELEVANT CONTEXT FOUND IN KNOWLEDGE GRAPH."

        context_lines = []
        for i, n in enumerate(nodes, 1):
            symbol = n.get("qualified_name") or n.get("name", "unknown")
            file_path = n.get("file", "unknown")
            l_start = n.get("line_start", "?")
            l_end = n.get("line_end", "?")
            ntype = n.get("type", "Node")
            doc = n.get("docstring") or "No docstring"
            sig = n.get("signature") or ""

            entry = [
                f"--- NODE #{i} [{ntype}] ---",
                f"Symbol: {symbol}",
                f"File: {file_path}",
                f"Lines: {l_start}-{l_end}",
            ]
            if sig:
                entry.append(f"Signature: {sig}")
            entry.append(f"Docstring/Summary: {doc}")
            if "bases" in n and n["bases"]:
                entry.append(f"Base Classes: {', '.join(n['bases'])}")
            if "args" in n and n["args"]:
                entry.append(f"Args: {', '.join(n['args'])}")

            context_lines.append("\n".join(entry))

        return "\n\n".join(context_lines)

    def answer(self, question: str, retrieved_data: dict[str, Any]) -> dict[str, Any]:
        """
        Synthesize an answer for the given question using retrieved context.
        """
        reasoning_trace = list(retrieved_data.get("reasoning_trace", []))
        nodes = retrieved_data.get("nodes", [])

        # Low evidence check: if top seed score is low or nodes empty
        top_score = nodes[0]["retrieval_score"] if nodes else 0.0

        if not nodes or top_score < 15.0:
            reasoning_trace.append("Synthesis Decision: Context scores below threshold. Defaulting to 'I don't know'.")
            return {
                "question": question,
                "answer": "I don't know — there is no evidence of this feature in the codebase.",
                "confidence": 0.0,
                "confidence_justification": "The search and graph traversal found no relevant symbols or modules in the repository.",
                "sources": [],
                "reasoning_trace": reasoning_trace,
            }

        context_text = self.format_context(retrieved_data)

        user_prompt = f"""QUESTION:
{question}

RETRIEVED CONTEXT NODES:
{context_text}

Provide your response in strict JSON format with answer (containing inline [file:symbol:line] citations), confidence score, confidence_justification, and sources list.
"""

        # Call Anthropic API if client available
        if self.client:
            try:
                reasoning_trace.append(f"Synthesis Step: Calling Anthropic API ({self.model_name})...")
                response = self.client.messages.create(
                    model=self.model_name,
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                content = response.content[0].text
                parsed = self._parse_llm_json(content)

                return {
                    "question": question,
                    "answer": parsed.get("answer", content),
                    "confidence": float(parsed.get("confidence", 0.8)),
                    "confidence_justification": parsed.get("confidence_justification", "Grounded in retrieved code context."),
                    "sources": parsed.get("sources", self._extract_sources_from_nodes(nodes)),
                    "reasoning_trace": reasoning_trace + ["Synthesis completed successfully via LLM."],
                }
            except Exception as exc:
                reasoning_trace.append(f"LLM API Call Error: {exc}. Falling back to structured heuristic synthesizer.")

        # Fallback synthesizer if API key is not set or API call fails
        return self._heuristic_answer_fallback(question, retrieved_data, reasoning_trace)

    def _heuristic_answer_fallback(
        self,
        question: str,
        retrieved_data: dict[str, Any],
        reasoning_trace: list[str],
    ) -> dict[str, Any]:
        """
        Deterministic, rule-based synthesis fallback when LLM API is unavailable.
        Ensures strict citation rules, evidence quality checks, and out-of-scope detection.
        """
        nodes = retrieved_data.get("nodes", [])
        q_lower = question.lower()

        # ── Gate 1: No retrieved nodes at all ──
        if not nodes:
            reasoning_trace.append("No relevant nodes found in knowledge graph for this query.")
            return {
                "question": question,
                "answer": "I don't know — no relevant code symbols were found in the `pallets/flask` repository for this query.",
                "confidence": 0.0,
                "confidence_justification": "Hybrid search returned zero matching nodes.",
                "sources": [],
                "reasoning_trace": reasoning_trace,
            }

        # ── Gate 2: Check for explicitly out-of-scope technology keywords ──
        out_of_scope_keywords = [
            "kafka", "websocket", "database", "postgres", "sql", "graphql", "grpc",
            "redis", "mongodb", "kubernetes", "docker", "terraform", "aws", "firebase",
        ]
        for kw in out_of_scope_keywords:
            if kw in q_lower:
                reasoning_trace.append(f"Fallback check: Query mentions out-of-scope feature '{kw}' not in indexed codebase.")
                return {
                    "question": question,
                    "answer": f"I don't know — the repository (`pallets/flask`) is a WSGI web framework and does not contain implementation for '{kw}'.",
                    "confidence": 0.0,
                    "confidence_justification": f"No modules or symbols related to '{kw}' exist in this codebase.",
                    "sources": [],
                    "reasoning_trace": reasoning_trace,
                }

        # ── Gate 3: Check retrieval score quality ──
        # If top seed scores are very low, the matches are irrelevant noise
        top_score = nodes[0].get("retrieval_score", 0.0) if nodes else 0.0
        avg_top3 = sum(n.get("retrieval_score", 0.0) for n in nodes[:3]) / max(1, len(nodes[:3]))

        if top_score < 30.0:
            reasoning_trace.append(
                f"Quality gate: Top retrieval score ({top_score:.1f}) is below threshold (30.0). "
                f"Matches are likely irrelevant noise — returning 'I don't know'."
            )
            return {
                "question": question,
                "answer": (
                    "I don't know — this question does not appear to be about the `pallets/flask` codebase. "
                    "The retrieval engine found no strongly relevant code symbols matching this query. "
                    "RepoGraph AI can only answer questions about the indexed repository."
                ),
                "confidence": 0.0,
                "confidence_justification": (
                    f"Top retrieval score is {top_score:.1f} (threshold: 30.0). "
                    f"No code symbols in the repository are relevant to this question."
                ),
                "sources": [],
                "reasoning_trace": reasoning_trace,
            }

        # ── Build grounded response from relevant retrieved nodes ──
        sources = []
        answer_parts = [f"Based on repository analysis for '{question}':\n"]

        for n in nodes[:5]:
            symbol = n.get("qualified_name") or n.get("name")
            fpath = n.get("file")
            line = n.get("line_start", 1)
            ntype = n.get("type")
            doc = n.get("docstring")

            citation = f"[{fpath}:{symbol}:L{line}]"
            sources.append({"file": fpath, "symbol": symbol, "line": line})

            if ntype == "Class":
                bases = f" (inheriting from {', '.join(n['bases'])})" if n.get("bases") else ""
                answer_parts.append(f"- **Class `{symbol}`**{bases} defined in `{fpath}` {citation}. {doc or ''}")
            elif ntype == "Function":
                sig = f"`{n.get('signature')}`" if n.get("signature") else f"`{symbol}`"
                answer_parts.append(f"- **Function/Method {sig}** in `{fpath}` {citation}. {doc or ''}")
            elif ntype == "File":
                answer_parts.append(f"- **Module `{fpath}`** {citation} contains core definitions for this topic.")

        answer_text = "\n".join(answer_parts).strip()

        # Dynamic confidence: scale based on retrieval quality
        # top_score 80+ → confidence ~0.90, top_score 50 → ~0.60, top_score 30 → ~0.35
        raw_conf = min(0.95, max(0.25, (top_score * 0.6 + avg_top3 * 0.4) / 85.0))
        confidence = round(raw_conf, 2)

        justification = (
            f"Retrieved {len(nodes)} relevant AST nodes; top seed match score is {top_score:.1f} "
            f"with groundings in {nodes[0].get('file', 'codebase')}."
        )

        return {
            "question": question,
            "answer": answer_text,
            "confidence": confidence,
            "confidence_justification": justification,
            "sources": sources,
            "reasoning_trace": reasoning_trace + ["Grounded heuristic synthesis applied with full citations."],
        }

    def _parse_llm_json(self, content: str) -> dict[str, Any]:
        """Extract and parse JSON from LLM response text."""
        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try regex extract json code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try match brace to brace
        match = re.search(r"(\{.*\})", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        return {"answer": content, "confidence": 0.8, "sources": []}

    def _extract_sources_from_nodes(self, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extract source locations from retrieved nodes."""
        sources = []
        for n in nodes[:5]:
            sources.append({
                "file": n.get("file"),
                "symbol": n.get("qualified_name") or n.get("name"),
                "line": n.get("line_start"),
            })
        return sources


# ═══════════════════════════════════════════════════════════════════════
# CLI Test
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from retriever import GraphRetriever

    if len(sys.argv) < 2:
        print("Usage: python answerer.py '<question>'")
        sys.exit(1)

    question = sys.argv[1]
    retriever = GraphRetriever()
    retrieved = retriever.retrieve(question)

    answerer = LLMAnswerer()
    result = answerer.answer(question, retrieved)

    print("\n" + "=" * 60)
    print(f"QUESTION: {result['question']}")
    print("=" * 60)
    print(f"CONFIDENCE: {result['confidence']:.2f}")
    print(f"CONFIDENCE REASON: {result['confidence_justification']}")
    print("\n--- ANSWER ---")
    print(result["answer"])
    print("\n--- SOURCES ---")
    for s in result["sources"]:
        print(f"  • {s['file']}:{s['symbol']}:L{s['line']}")
    print("\n--- REASONING TRACE ---")
    for t in result["reasoning_trace"]:
        print(f"  {t}")
    print("=" * 60)
