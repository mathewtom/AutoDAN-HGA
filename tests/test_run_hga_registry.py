"""Wiring tests for FITNESS_REGISTRY in run_hga.py.

Verifies that the registry's shape is consistent (3-tuples) and that
build_fitness resolves each system_prompt_leak entry to a real
SystemPromptLeakFitness with the campaign's target_string. We do NOT
exercise identity_smuggling here — its build_fitness loads the mock
agent (ChromaDB, employees, etc.) and isn't relevant to the active
work.

Uses a stub adapter; no 8B / no scanner side effects beyond what
SystemPromptLeakFitness's __init__ does (which is just rendering the
production system prompt and tool dicts — fast, no GPU).
"""

from __future__ import annotations

from attacks.hga.run_hga import FITNESS_REGISTRY, build_fitness
from surrogate.fitness.system_prompt_leak import SystemPromptLeakFitness


class _StubSurrogate:
    model = object()
    tokenizer = object()


class _StubAdapter:
    surrogate = _StubSurrogate()


def test_registry_entries_are_3_tuples():
    """Every entry must be (module_path, factory_name, kwargs_dict)."""
    for name, entry in FITNESS_REGISTRY.items():
        assert len(entry) == 3, f"{name!r} entry has wrong shape: {entry}"
        module_path, factory, kwargs = entry
        assert isinstance(module_path, str)
        assert isinstance(factory, str)
        assert isinstance(kwargs, dict)


def test_three_system_prompt_leak_campaigns_present():
    expected = {
        "system_prompt_leak_verbatim",
        "system_prompt_leak_tool_disclosure",
        "system_prompt_leak_meta",
    }
    assert expected.issubset(FITNESS_REGISTRY.keys())


def test_each_campaign_has_distinct_target_string():
    targets = {
        name: FITNESS_REGISTRY[name][2]["target_string"]
        for name in FITNESS_REGISTRY
        if name.startswith("system_prompt_leak_")
    }
    assert len(set(targets.values())) == 3, (
        f"campaigns must have distinct targets; got {targets}"
    )


def test_build_fitness_returns_system_prompt_leak_instance_with_correct_target():
    """End-to-end: build_fitness('system_prompt_leak_verbatim', adapter)
    returns a SystemPromptLeakFitness with the verbatim target string.
    """
    adapter = _StubAdapter()
    fit = build_fitness("system_prompt_leak_verbatim", adapter)
    assert isinstance(fit, SystemPromptLeakFitness)
    # Internal field name — testing white-box because the contract is
    # "registry kwargs reach __init__ correctly."
    assert fit._target_string == (
        "You are the Meridian assistant for SecureRAG-Agent."
    )


def test_build_fitness_propagates_target_for_all_three_campaigns():
    adapter = _StubAdapter()
    cases = {
        "system_prompt_leak_verbatim":
            "You are the Meridian assistant for SecureRAG-Agent.",
        "system_prompt_leak_tool_disclosure": "search_documents",
        "system_prompt_leak_meta": "my system prompt",
    }
    for name, expected_target in cases.items():
        fit = build_fitness(name, adapter)
        assert fit._target_string == expected_target


def test_unknown_fitness_name_raises():
    import pytest
    with pytest.raises(ValueError, match="unknown fitness"):
        build_fitness("not_a_real_campaign", _StubAdapter())
