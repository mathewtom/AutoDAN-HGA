"""Integration test for `target_log_prob` against the real Llama 3.1 8B.

Verifies the directional property a stub model can't:
  for a prefix that primes a target, the model assigns higher log-prob
  to the expected continuation than to a clearly-wrong one.

Slow: loads ~16 GB of weights (~30 s on first run, faster after warm
HF cache). Gated behind RUN_8B=1 so the default suite stays fast and
free of model-loading side effects.

Run explicitly:
    RUN_8B=1 uv run pytest tests/test_log_prob_integration.py -v
"""

from __future__ import annotations

import os

import pytest

from surrogate.fitness.log_prob import target_log_prob
from surrogate.load_8b import load_surrogate


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_8B") != "1",
    reason="Skipping 8B integration test; set RUN_8B=1 to enable.",
)


@pytest.fixture(scope="module")
def surrogate():
    """Load the 8B once per test module — sharing across tests in this file."""
    return load_surrogate()


def test_paris_scores_higher_than_banana_after_france_prefix(surrogate):
    """Directional sanity: a plausible completion outscores a nonsense one."""
    prefix = "The capital of France is"

    likely = target_log_prob(
        surrogate.model, surrogate.tokenizer, prefix, " Paris",
    )
    unlikely = target_log_prob(
        surrogate.model, surrogate.tokenizer, prefix, " banana",
    )

    assert likely < 0, "log-prob must be negative"
    assert unlikely < 0, "log-prob must be negative"
    assert likely > unlikely, (
        f"Expected ' Paris' ({likely:.3f}) > ' banana' ({unlikely:.3f}) "
        f"given prefix '{prefix}'"
    )
    # Looser-but-meaningful gap: at least 2 nats of separation, so we're
    # measuring real preference, not noise.
    assert likely - unlikely > 2.0, (
        f"Gap too small: ' Paris'={likely:.3f}, ' banana'={unlikely:.3f}"
    )


def test_log_prob_decreases_as_target_gets_longer(surrogate):
    """Each additional token only multiplies probabilities (never increases),
    so log-prob of a longer target must be ≤ log-prob of any prefix of it.
    """
    prefix = "The capital of France is"

    short = target_log_prob(
        surrogate.model, surrogate.tokenizer, prefix, " Paris",
    )
    longer = target_log_prob(
        surrogate.model, surrogate.tokenizer, prefix, " Paris, France",
    )

    assert longer <= short, (
        f"Longer target should not score higher: short={short:.3f}, "
        f"longer={longer:.3f}"
    )
