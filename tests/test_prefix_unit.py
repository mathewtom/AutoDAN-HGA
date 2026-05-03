"""Unit tests for `render_prefix` using a stub tokenizer.

Verifies the helper passes the right messages, tool list, and template
flags to apply_chat_template — without depending on a real HF tokenizer
or its chat template internals.
"""

from __future__ import annotations

from surrogate.fitness.prefix import render_prefix


class StubTokenizer:
    """Records the apply_chat_template call so the test can inspect it."""

    def __init__(self) -> None:
        self.last_call: dict | None = None

    def apply_chat_template(self, messages, tools=None,
                            add_generation_prompt=False, tokenize=True):
        self.last_call = {
            "messages": messages,
            "tools": tools,
            "add_generation_prompt": add_generation_prompt,
            "tokenize": tokenize,
        }
        return f"<RENDERED:{len(messages)}msgs:{len(tools or [])}tools>"


def test_render_prefix_passes_system_and_user_messages():
    tok = StubTokenizer()
    result = render_prefix(
        tok,
        system_prompt="SYS",
        tool_function_dicts=[],
        user_prompt="USER",
    )
    assert result == "<RENDERED:2msgs:0tools>"
    assert tok.last_call["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
    ]


def test_render_prefix_forwards_tools():
    tok = StubTokenizer()
    fake_tools = [
        {"name": "search_documents", "parameters": {}},
        {"name": "lookup_employee", "parameters": {}},
    ]
    render_prefix(
        tok, system_prompt="SYS",
        tool_function_dicts=fake_tools, user_prompt="USER",
    )
    assert tok.last_call["tools"] == fake_tools


def test_render_prefix_uses_add_generation_prompt_and_string_output():
    """The model must score from exactly the assistant-header position
    (add_generation_prompt=True), and the result must be a string so it
    composes with target_log_prob's string interface (tokenize=False).
    """
    tok = StubTokenizer()
    render_prefix(tok, system_prompt="SYS",
                  tool_function_dicts=[], user_prompt="USER")
    assert tok.last_call["add_generation_prompt"] is True
    assert tok.last_call["tokenize"] is False
