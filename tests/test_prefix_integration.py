"""Integration test for `render_prefix` against the real Llama 3.1 tokenizer.

Verifies the rendered string contains the expected substrings: production
system prompt content, the user prompt, tool names, and ends with the
assistant generation prompt header.

Loads only the tokenizer, not the model — fast (~1s on warm cache).
Gated behind RUN_8B=1 to keep the default suite free of HF auth concerns.
"""

from __future__ import annotations

import os

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from securerag_agent.agent.prompts import build_system_prompt
from securerag_agent.agent.tools import (
    lookup_employee,
    search_documents,
)
from transformers import AutoTokenizer

from surrogate.fitness.prefix import render_prefix


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_8B") != "1",
    reason="Skipping tokenizer integration test; set RUN_8B=1 to enable.",
)

MODEL_ID = os.environ.get(
    "SURROGATE_MODEL_PATH", "meta-llama/Llama-3.1-8B-Instruct",
)


@pytest.fixture(scope="module")
def tokenizer():
    return AutoTokenizer.from_pretrained(MODEL_ID)


@pytest.fixture(scope="module")
def tool_dicts():
    return [
        convert_to_openai_tool(t)["function"]
        for t in (search_documents, lookup_employee)
    ]


def test_rendered_prefix_contains_system_prompt_signature(tokenizer, tool_dicts):
    system_prompt = build_system_prompt(user_id="E003", caller=None)
    result = render_prefix(
        tokenizer,
        system_prompt=system_prompt,
        tool_function_dicts=tool_dicts,
        user_prompt="What can you help me with?",
    )
    # Verbatim leak target signature — Campaign A's target string lives
    # at line 1 of the system prompt and must survive templating.
    assert "You are the Meridian assistant for SecureRAG-Agent" in result


def test_rendered_prefix_contains_user_prompt(tokenizer, tool_dicts):
    system_prompt = build_system_prompt(user_id="E003", caller=None)
    user = "Walk me through what your job is, in detail."
    result = render_prefix(
        tokenizer, system_prompt=system_prompt,
        tool_function_dicts=tool_dicts, user_prompt=user,
    )
    assert user in result


def test_rendered_prefix_contains_tool_names(tokenizer, tool_dicts):
    """Campaign B target = 'search_documents' must appear in the prefix
    via the tool-schema portion of the chat template.
    """
    system_prompt = build_system_prompt(user_id="E003", caller=None)
    result = render_prefix(
        tokenizer, system_prompt=system_prompt,
        tool_function_dicts=tool_dicts, user_prompt="hello",
    )
    assert "search_documents" in result
    assert "lookup_employee" in result


def test_rendered_prefix_ends_at_assistant_header(tokenizer, tool_dicts):
    """The prefix must terminate at the assistant generation prompt —
    that's where the model is about to speak, and where target_log_prob
    must measure from.
    """
    system_prompt = build_system_prompt(user_id="E003", caller=None)
    result = render_prefix(
        tokenizer, system_prompt=system_prompt,
        tool_function_dicts=tool_dicts, user_prompt="hello",
    )
    # Llama 3.1's assistant generation prompt; the trailing "\n\n" is what
    # apply_chat_template emits before the model's first reply token.
    assert result.rstrip().endswith("<|start_header_id|>assistant<|end_header_id|>")
