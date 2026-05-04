"""Fitness protocol for HGA campaigns.

Fitness functions map an adversarial prompt to a real-valued score.
Scores are absolute (threshold on the defense condition itself), not
relative to any baseline — see README §"What this measures" for why.
"""

from __future__ import annotations

from typing import Protocol


class Fitness(Protocol):
    """Adversarial prompt -> real-valued score. Higher = more
    successful attack. 0.0 means the defense held (or the prompt
    never exercised the attack surface)."""

    def __call__(self, prompt: str) -> float: ...
