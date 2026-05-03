"""LangChain BaseChatModel adapter for the Llama 3.1 8B surrogate.

Implements the minimum surface LangGraph's `build_graph` exercises:
`bind_tools(tools)` and `invoke(messages) -> AIMessage`. Tool calls
are parsed from Llama 3.1's native tool-calling output format
(`<|python_tag|>{"name": ..., "parameters": ...}` or bare JSON after
an assistant turn when tools are provided).

This adapter is intentionally minimal — langchain-huggingface's
ChatHuggingFace has had spotty tool-call parsing for Llama models,
and HGA needs deterministic, inspectable behavior. Passing a
pre-loaded Surrogate keeps the heavyweight model load separate from
the per-invocation logic, making unit tests fast.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Sequence

import torch
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from surrogate.load_8b import Surrogate


_PYTHON_TAG = "<|python_tag|>"
# Llama 3.1 tool-call emission: either preceded by <|python_tag|> or a
# bare JSON object that parses to {"name": str, "parameters": dict}.
_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


class Llama3ChatAdapter(BaseChatModel):
    """Minimal BaseChatModel for Llama 3.1 8B via HF + MPS.

    Use via ``Llama3ChatAdapter(surrogate=load_surrogate())``. For
    tests use the ``StubChatModel`` in tests/conftest.py instead.
    """

    surrogate: Surrogate
    max_new_tokens: int = 512
    temperature: float = 0.0
    bound_tools: list[dict[str, Any]] = []

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "llama3-chat-adapter"

    def bind_tools(
        self, tools: Sequence[BaseTool | dict[str, Any]], **_: Any,
    ) -> "Llama3ChatAdapter":
        schemas = [
            convert_to_openai_tool(t) if not isinstance(t, dict) else t
            for t in tools
        ]
        # Pydantic model rebuild via .copy(update=...) to stay on the
        # BaseChatModel contract (which uses pydantic v1/v2 semantics).
        return self.model_copy(update={"bound_tools": schemas})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        chat = _to_chat_dicts(messages)
        template_kwargs: dict[str, Any] = {"add_generation_prompt": True}
        if self.bound_tools:
            template_kwargs["tools"] = [
                t["function"] for t in self.bound_tools
            ]

        input_ids = self.surrogate.tokenizer.apply_chat_template(
            chat, return_tensors="pt", **template_kwargs,
        ).to(self.surrogate.device)

        with torch.inference_mode():
            output_ids = self.surrogate.model.generate(
                input_ids,
                max_new_tokens=self.max_new_tokens,
                do_sample=self.temperature > 0.0,
                temperature=self.temperature if self.temperature > 0.0 else 1.0,
                pad_token_id=self.surrogate.tokenizer.pad_token_id,
            )

        generated = output_ids[0, input_ids.shape[1]:]
        text = self.surrogate.tokenizer.decode(
            generated, skip_special_tokens=False,
        )
        message = _parse_llama3_output(text)
        return ChatResult(generations=[ChatGeneration(message=message)])


def _to_chat_dicts(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, SystemMessage):
            out.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            entry: dict[str, Any] = {"role": "assistant", "content": m.content}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["args"]),
                        },
                    }
                    for tc in m.tool_calls
                ]
            out.append(entry)
        elif isinstance(m, ToolMessage):
            out.append({
                "role": "tool",
                "name": m.name or "",
                "content": m.content,
            })
        else:
            out.append({"role": "user", "content": str(m.content)})
    return out


def _parse_llama3_output(text: str) -> AIMessage:
    """Split Llama 3.1 output into content and tool_calls.

    Accepts either ``<|python_tag|>{...}`` or a leading JSON object.
    If no parseable tool call is found, returns plain content.
    """
    stripped = text
    # <|eom_id|> terminates a tool-call turn (Llama 3.1 spec); <|eot_id|>
    # terminates a plain-text turn. Strip whichever shows up first.
    for stop_token in ("<|eom_id|>", "<|eot_id|>", "<|end_of_text|>"):
        if stop_token in stripped:
            stripped = stripped.split(stop_token, 1)[0]
    stripped = stripped.strip()

    tool_json: str | None = None
    if stripped.startswith(_PYTHON_TAG):
        tool_json = stripped[len(_PYTHON_TAG):].strip()
    elif stripped.startswith("{"):
        match = _JSON_OBJ_RE.match(stripped)
        if match is not None:
            tool_json = match.group(0)

    if tool_json is not None:
        try:
            parsed = json.loads(tool_json)
        except json.JSONDecodeError:
            return AIMessage(content=stripped)
        name = parsed.get("name")
        args = parsed.get("parameters") or parsed.get("arguments") or {}
        if isinstance(name, str):
            return AIMessage(
                content="",
                tool_calls=[{
                    "name": name,
                    "args": args if isinstance(args, dict) else {},
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                }],
            )

    return AIMessage(content=stripped)
