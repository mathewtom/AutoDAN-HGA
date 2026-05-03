"""Mock agent: SecureRAG-Agent's real LangGraph with a swappable LLM.

See autodan/README.md §2 for the rationale — HGA/GCG fitness needs
the full agent's behavior (authorization, retrieval, tool dispatch,
audit emission), not a stripped LLM-only proxy, or the optimizer
finds prompts that break a fiction and don't transfer to the 70B.

What IS composed (same as production):
  - `build_graph` (ReAct loop, AuthenticatedToolNode, budget)
  - the seven `make_*_handler` factories from securerag_agent
  - `MeridianRetriever` over the real ChromaDB collection
  - `AuditSink` emitting JSONL events for fitness inspection

What is NOT composed (bypassed during HGA optimization):
  - rate limiter, input scanners, output scanners, classification
    guard, credential detector — these live in `AgenticChain`
    (securerag_agent.agent.wrapper) and are re-engaged at transfer
    time via the live HTTP endpoint. Per-layer ASR attribution
    depends on them being bypassed here.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import chromadb

from securerag_agent import audit as sra_audit
from securerag_agent.agent.audit_sink import AuditSink
from securerag_agent.agent.graph import build_graph
from securerag_agent.agent.retriever import MeridianRetriever
from securerag_agent.agent.tools.escalate_to_human import (
    make_escalate_to_human_handler,
)
from securerag_agent.agent.tools.get_approval_chain import (
    make_get_approval_chain_handler,
)
from securerag_agent.agent.tools.get_ticket_detail import (
    make_get_ticket_detail_handler,
)
from securerag_agent.agent.tools.list_calendar_events import (
    make_list_calendar_events_handler,
)
from securerag_agent.agent.tools.list_my_tickets import (
    make_list_my_tickets_handler,
)
from securerag_agent.agent.tools.lookup_employee import (
    make_lookup_employee_handler,
)
from securerag_agent.agent.tools.registry import (
    ToolRegistry,
    make_search_documents_handler,
)
from securerag_agent.data.loaders import (
    load_calendar,
    load_employees,
    load_projects,
    load_tickets,
)

_DEFAULT_CHROMA_PATH = os.environ.get(
    "CHROMA_PATH", "../SecureRAG-Agent/data/chroma",
)
_DEFAULT_COLLECTION = "meridian_documents"


class MockAgent:
    """Compiled LangGraph + its AuditSink (the fitness function
    reads from `audit_sink.path` to inspect what happened)."""

    def __init__(self, *, graph: Any, audit_sink: AuditSink) -> None:
        self.graph = graph
        self.audit_sink = audit_sink

    def invoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        return self.graph.invoke(initial_state)


def build_mock_agent(
    *,
    llm: Any,
    retriever: MeridianRetriever | None = None,
    chroma_path: str | Path | None = None,
    chroma_collection: str = _DEFAULT_COLLECTION,
    logs_dir: Path | None = None,
) -> MockAgent:
    """Compose the agent graph with `llm` in the place of ChatOllama.

    Parameters
    ----------
    llm
        Any object implementing ``.bind_tools(list) -> self`` and
        ``.invoke(messages) -> AIMessage``. Pass ``Llama3ChatAdapter``
        for real surrogate runs, or a fake chat model for unit tests.
    retriever
        An already-built ``MeridianRetriever``. If not given, a
        retriever is constructed from ``chroma_path`` +
        ``chroma_collection``.
    chroma_path
        Path to the ChromaDB directory SecureRAG-Agent ingested into.
        Defaults to ``CHROMA_PATH`` env or the sibling repo's
        ``data/chroma``.
    logs_dir
        Where to write audit JSONL. Defaults to a fresh tempdir so
        each fitness eval is self-contained.
    """
    employees_list = load_employees()
    employees = {e.employee_id: e for e in employees_list}
    tickets_list = load_tickets()
    tickets_by_id = {t.ticket_id: t for t in tickets_list}
    projects_list = load_projects()
    projects_by_id = {p.project_id: p for p in projects_list}
    events_list = load_calendar()

    if retriever is None:
        path = Path(chroma_path) if chroma_path else Path(_DEFAULT_CHROMA_PATH)
        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_collection(chroma_collection)
        retriever = MeridianRetriever(
            collection=collection, employees_by_id=employees,
        )

    handlers: ToolRegistry = {
        "search_documents": make_search_documents_handler(retriever),
        "lookup_employee": make_lookup_employee_handler(employees=employees),
        "get_approval_chain": make_get_approval_chain_handler(
            employees=employees,
        ),
        "list_my_tickets": make_list_my_tickets_handler(
            employees=employees, tickets=tickets_list,
        ),
        "get_ticket_detail": make_get_ticket_detail_handler(
            employees=employees,
            tickets=tickets_by_id,
            projects=projects_by_id,
        ),
        "list_calendar_events": make_list_calendar_events_handler(
            employees=employees, events=events_list,
        ),
        "escalate_to_human": make_escalate_to_human_handler(
            employees=employees, audit=sra_audit,
        ),
    }

    sink_dir = logs_dir or Path(tempfile.mkdtemp(prefix="autodan_audit_"))
    audit_sink = AuditSink(logs_dir=sink_dir)

    graph = build_graph(
        llm=llm,
        handlers=handlers,
        audit=sra_audit,
        audit_sink=audit_sink,
        employees=employees,
    )
    return MockAgent(graph=graph, audit_sink=audit_sink)
