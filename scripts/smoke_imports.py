"""Phase 0 smoke test: verify every symbol the mock agent needs is
importable from a public (non-underscore) path in the installed
securerag_agent package.

Run: `uv run python scripts/smoke_imports.py`
Exits 0 on success, non-zero on any import failure.
"""

from __future__ import annotations

import sys
import traceback

EXPECTED = [
    ("securerag_agent.agent.tools.registry", "ToolRegistry"),
    ("securerag_agent.agent.tools.registry", "ToolHandler"),
    ("securerag_agent.agent.tools.registry", "make_search_documents_handler"),
    ("securerag_agent.agent.tools.lookup_employee", "make_lookup_employee_handler"),
    ("securerag_agent.agent.tools.get_approval_chain", "make_get_approval_chain_handler"),
    ("securerag_agent.agent.tools.list_my_tickets", "make_list_my_tickets_handler"),
    ("securerag_agent.agent.tools.get_ticket_detail", "make_get_ticket_detail_handler"),
    ("securerag_agent.agent.tools.list_calendar_events", "make_list_calendar_events_handler"),
    ("securerag_agent.agent.tools.escalate_to_human", "make_escalate_to_human_handler"),
    ("securerag_agent.agent.graph", "AuthenticatedToolNode"),
    ("securerag_agent.agent.graph", "build_graph"),
    ("securerag_agent.agent.audit_sink", "AuditSink"),
    ("securerag_agent.agent.retriever", "MeridianRetriever"),
    ("securerag_agent.agent.state", "AgentState"),
    ("securerag_agent.agent.state", "ToolStatus"),
    ("securerag_agent.data.loaders", "load_employees"),
    ("securerag_agent.data.loaders", "load_projects"),
    ("securerag_agent.data.loaders", "load_tickets"),
    ("securerag_agent.data.loaders", "load_calendar"),
]


def main() -> int:
    failures: list[tuple[str, str, str]] = []
    for module, symbol in EXPECTED:
        try:
            mod = __import__(module, fromlist=[symbol])
            getattr(mod, symbol)
            print(f"  OK  {module}:{symbol}")
        except Exception:
            failures.append((module, symbol, traceback.format_exc()))
            print(f"  FAIL {module}:{symbol}")

    if failures:
        print(f"\n{len(failures)} import(s) failed:")
        for module, symbol, tb in failures:
            print(f"\n--- {module}:{symbol} ---\n{tb}")
        return 1
    print(f"\nAll {len(EXPECTED)} imports OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
