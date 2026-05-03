"""Phase 1 hard gate: does the 8B mock agent trace match the 70B live
agent trace on benign queries?

HGA will optimize adversarial prompts against the mock. If the 8B's
tool-call sequences diverge substantially from the 70B's, those
attacks won't transfer. Per the README §7 exit criterion: >20%
divergence = STOP and either rework the mock agent or document the
transfer-degradation risk.

This script:
  1. Loads a benign query set (queries/benign.txt, one per line).
  2. POSTs each to the live SecureRAG-Agent at SECURERAG_AGENT_URL.
  3. Runs each through the 8B mock agent.
  4. Extracts the tool-call shape (ordered list of tool names) from
     both, ignoring args (args will vary with LLM stochasticity).
  5. Reports per-query agreement and overall divergence rate.

Requires:
  - SecureRAG-Agent running at SECURERAG_AGENT_URL (default
    http://127.0.0.1:8000). Ollama up with llama3.3:70b.
  - Llama 3.1 8B weights downloaded and SURROGATE_MODEL_PATH set.
  - ChromaDB populated (run `uv run python -m scripts.ingest_meridian`
    in SecureRAG-Agent first).

Memory note: 70B Ollama + 8B HF + ChromaDB together exceed laptop
headroom. Run this ONLY during dedicated parity runs; not during
HGA optimization (which uses the 8B alone).

Exit code 0 on pass (<=20% divergence), 1 on fail.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from langchain_core.messages import HumanMessage

# autodan/ sibling of scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from surrogate.chat_adapter import Llama3ChatAdapter
from surrogate.load_8b import load_surrogate
from surrogate.mock_agent import build_mock_agent

DEFAULT_AGENT_URL = os.environ.get("SECURERAG_AGENT_URL", "http://127.0.0.1:8000")
DEFAULT_DIVERGENCE_THRESHOLD = 0.20
DEFAULT_DEMO_USER = os.environ.get("SECURERAG_DEMO_USER", "E003")


@dataclass
class ParityResult:
    query: str
    mock_trace: list[str]
    live_trace: list[str]
    agrees: bool


def live_tool_trace(base_url: str, query: str) -> list[str]:
    """Run the query against live /agent/query; reconstruct tool
    sequence from the audit log file for this request_id."""
    resp = requests.post(
        f"{base_url}/agent/query", json={"query": query}, timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    req_id = data["request_id"]
    return _tool_names_from_audit_log(req_id)


def _tool_names_from_audit_log(
    request_id: str, logs_dir: Path | None = None,
) -> list[str]:
    """Extract tool_call events for a given request_id from today's
    audit JSONL, in the order they appear. Cross-day requests are out
    of scope here (tests complete in a single day)."""
    import datetime as _dt

    logs_dir = logs_dir or Path(
        os.environ.get("AUDIT_LOG_DIR", "../SecureRAG-Agent/logs"),
    )
    today = _dt.date.today().isoformat()
    log_path = logs_dir / f"audit-{today}.jsonl"
    if not log_path.exists():
        return []

    names: list[str] = []
    with log_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "tool_call":
                continue
            if event.get("request_id") != request_id:
                continue
            if event.get("status") != "success":
                continue
            tn = event.get("tool_name")
            if isinstance(tn, str):
                names.append(tn)
    return names


def mock_tool_trace(agent: Any, query: str) -> list[str]:
    request_id = f"parity_{uuid.uuid4().hex[:8]}"
    initial = {
        "request_id": request_id,
        "user_id": DEFAULT_DEMO_USER,
        "messages": [HumanMessage(content=query)],
        "step_count": 0,
        "max_steps": 20,
        "tool_call_log": [],
        "security_verdicts": [],
        "retrieved_doc_ids": [],
        "final_answer": None,
        "termination_reason": None,
    }
    final = agent.invoke(initial)
    return [
        rec["tool_name"]
        for rec in final.get("tool_call_log", [])
        if rec.get("status") == "success" or str(rec.get("status")).endswith("SUCCESS")
    ]


def compare(mock: list[str], live: list[str]) -> bool:
    """Traces agree if the ordered tool-name sequences match.

    Intentionally strict — if the 8B skips a tool the 70B makes or
    calls one the 70B doesn't, that's a transfer-degradation signal.
    """
    return mock == live


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path(__file__).resolve().parent / "queries" / "benign.txt",
        help="Path to benign query set (one query per line).",
    )
    parser.add_argument(
        "--base-url", default=DEFAULT_AGENT_URL,
        help="SecureRAG-Agent URL for live traces.",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_DIVERGENCE_THRESHOLD,
        help="Max acceptable divergence rate (0.20 per README §7).",
    )
    parser.add_argument(
        "--report", type=Path, default=None,
        help="Write per-query results as JSONL to this path.",
    )
    args = parser.parse_args()

    queries = [
        line.strip() for line in args.queries.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    print(f"Loaded {len(queries)} benign queries from {args.queries}")

    print("Loading Llama 3.1 8B on MPS...")
    surrogate = load_surrogate()
    llm = Llama3ChatAdapter(surrogate=surrogate)
    agent = build_mock_agent(llm=llm)

    results: list[ParityResult] = []
    for q in queries:
        try:
            live = live_tool_trace(args.base_url, q)
        except Exception as e:
            print(f"  LIVE FAIL: {q[:60]}... -> {e}")
            continue
        try:
            mock = mock_tool_trace(agent, q)
        except Exception as e:
            print(f"  MOCK FAIL: {q[:60]}... -> {e}")
            continue

        agrees = compare(mock, live)
        results.append(ParityResult(q, mock, live, agrees))
        mark = "OK " if agrees else "DIV"
        print(f"  {mark} mock={mock} live={live}  q={q[:50]!r}")

    if not results:
        print("No completed comparisons — aborting.")
        return 1

    divergence = sum(1 for r in results if not r.agrees) / len(results)
    print()
    print(f"Divergence rate: {divergence:.1%} ({sum(1 for r in results if not r.agrees)}/{len(results)})")
    print(f"Threshold:       {args.threshold:.1%}")

    if args.report is not None:
        with args.report.open("w") as f:
            for r in results:
                f.write(json.dumps({
                    "query": r.query,
                    "mock": r.mock_trace,
                    "live": r.live_trace,
                    "agrees": r.agrees,
                }) + "\n")
        print(f"Report written: {args.report}")

    return 0 if divergence <= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
