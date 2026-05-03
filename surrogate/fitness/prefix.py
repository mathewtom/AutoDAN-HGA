"""Build the production-parity chat-templated prefix for fitness scoring.

Used by SystemPromptLeakFitness's Tier 2: the rendered string is the
exact context the surrogate would see immediately before generating
its reply (system prompt + tool schemas + user prompt + assistant
generation prompt). It's handed to `target_log_prob` as the `prefix_text`,
so the log-prob of the leak target is computed under production-equivalent
conditioning.
"""

from __future__ import annotations

from typing import Any


def render_prefix(
    tokenizer: Any,
    system_prompt: str,
    tool_function_dicts: list[dict],
    user_prompt: str,
) -> str:
    """Apply Llama 3.1's chat template, ending at the assistant generation
    prompt — i.e., the exact position where the model is about to speak.

    Parameters
    ----------
    tokenizer
        Any tokenizer with `apply_chat_template`. In production this is
        `Llama3ChatAdapter.surrogate.tokenizer`.
    system_prompt
        The fully-rendered system prompt string (caller block already
        substituted by `build_system_prompt(user_id, caller)`).
    tool_function_dicts
        Tool schemas in the OpenAI-function-call dict shape that
        `apply_chat_template(tools=...)` consumes. The
        `Llama3ChatAdapter.bind_tools` path produces these via
        `convert_to_openai_tool` and stores `t["function"]` per tool.
    user_prompt
        The user's message for this fitness evaluation — what HGA
        is currently scoring.

    Returns
    -------
    str
        Tokenizer-rendered chat template. Suitable for direct use as
        the `prefix_text` argument to `target_log_prob`.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tools=tool_function_dicts,
        add_generation_prompt=True,
        tokenize=False,
    )
