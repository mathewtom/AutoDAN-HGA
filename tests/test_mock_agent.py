"""Composition smoke tests for build_mock_agent and the chat adapter's
Llama 3.1 tool-call parser.

Verifies the mock agent composes without hitting the 8B model, the
70B Ollama, or a populated ChromaDB — i.e. runs in CI. Real
end-to-end behavior is covered by the parity test in
scripts/parity_test.py, which requires a live SecureRAG-Agent service
and is tagged `slow`.
"""

from __future__ import annotations

from typing import Any, Iterable

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from surrogate.chat_adapter import _parse_llama3_output
from surrogate.mock_agent import build_mock_agent


class StubChatModel(BaseChatModel):
    """LLM stub for LangGraph: returns queued AIMessages in order.

    Bind_tools is a no-op since the stub replays pre-built responses
    that can already include tool_calls if a test needs the graph to
    enter the tool node.
    """

    responses: list[AIMessage] = []
    index: int = 0

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools: Iterable[Any], **_: Any) -> "StubChatModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.index >= len(self.responses):
            msg = AIMessage(content="DONE")
        else:
            msg = self.responses[self.index]
            self.index += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


class FakeRetriever:
    """Stand-in for MeridianRetriever used when a real ChromaDB is
    unavailable. Only the .search method is exercised."""

    def search(self, *, query: str, user_id: str, k: int = 5) -> list[dict[str, Any]]:
        return []


def test_build_mock_agent_composes_without_tool_call(tmp_path):
    stub = StubChatModel(responses=[AIMessage(content="hello, E003")])
    agent = build_mock_agent(
        llm=stub, retriever=FakeRetriever(), logs_dir=tmp_path,
    )

    initial = {
        "request_id": "unit_test",
        "user_id": "E003",
        "messages": [HumanMessage(content="hi")],
        "step_count": 0,
        "max_steps": 5,
        "tool_call_log": [],
        "security_verdicts": [],
        "retrieved_doc_ids": [],
        "final_answer": None,
        "termination_reason": None,
    }
    final = agent.invoke(initial)

    # Expect the stub's single content-only AIMessage to end the graph
    # without visiting the tools node.
    assert final["tool_call_log"] == []
    assert isinstance(final["messages"][-1], AIMessage)
    assert "E003" in final["messages"][-1].content


def test_build_mock_agent_routes_tool_call_through_auth_node(tmp_path):
    # First assistant turn requests lookup_employee; second ends.
    tool_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "lookup_employee",
            "args": {"employee_id": "E003"},
            "id": "call_1",
        }],
    )
    final_turn = AIMessage(content="ok, looked up")
    stub = StubChatModel(responses=[tool_call, final_turn])

    agent = build_mock_agent(
        llm=stub, retriever=FakeRetriever(), logs_dir=tmp_path,
    )
    initial = {
        "request_id": "unit_test_tool",
        "user_id": "E003",
        "messages": [HumanMessage(content="look up E003")],
        "step_count": 0,
        "max_steps": 5,
        "tool_call_log": [],
        "security_verdicts": [],
        "retrieved_doc_ids": [],
        "final_answer": None,
        "termination_reason": None,
    }
    final = agent.invoke(initial)

    # One tool call should have been dispatched by the real
    # AuthenticatedToolNode. If this asserts, the make_lookup_employee
    # wiring has changed upstream and mock_agent.py needs to follow.
    assert len(final["tool_call_log"]) == 1
    assert final["tool_call_log"][0]["tool_name"] == "lookup_employee"


@pytest.mark.parametrize("stop_token", ["<|eom_id|>", "<|eot_id|>"])
def test_parse_tool_call_handles_both_terminators(stop_token):
    """Llama 3.1 uses <|eom_id|> to terminate a tool-call turn (so the
    agent loop knows to run the tool and come back) and <|eot_id|> for
    plain-text turns. A tokenizer that ships with `Llama-3.1-8B-Instruct`
    emits <|eom_id|> for tool calls, so the parser MUST strip it before
    json.loads — or every adversarial prompt's tool-call emission will
    be mis-parsed as free-form content and the agent will never dispatch.
    Regression for the parity-gate failure on 2026-04-20."""
    payload = '{"name": "lookup_employee", "parameters": {"employee_id": "E003"}}'
    raw = f"<|python_tag|>{payload}{stop_token}"

    msg = _parse_llama3_output(raw)
    assert msg.tool_calls, f"no tool_calls parsed from {stop_token} output"
    assert msg.tool_calls[0]["name"] == "lookup_employee"
    assert msg.tool_calls[0]["args"] == {"employee_id": "E003"}
