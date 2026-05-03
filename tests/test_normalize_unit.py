"""Unit tests for `log_prob_to_leak_score`.

Pure math primitive — no model, no tokenizer. Verifies the sigmoid
shape and the meaning of the shift/scale knobs.
"""

from __future__ import annotations

import math

import pytest

from surrogate.fitness.normalize import log_prob_to_leak_score


def test_default_midpoint_is_at_log_prob_minus_two():
    """With default shift=-2.0, scale=2.0: log_prob=-2 -> leak_score=0.5."""
    assert math.isclose(log_prob_to_leak_score(-2.0), 0.5, abs_tol=1e-9)


def test_log_prob_zero_is_above_midpoint():
    """log_prob=0 is the strongest possible leak signal (P(target)=1).
    Default knobs put it well above 0.5.
    """
    score = log_prob_to_leak_score(0.0)
    assert 0.7 < score < 0.8


def test_very_negative_log_prob_is_near_zero():
    score = log_prob_to_leak_score(-20.0)
    assert score < 0.01


def test_very_positive_log_prob_is_near_one():
    """Mathematically log_prob can't be positive (probability > 1 is
    impossible), but the function should saturate cleanly if fed one."""
    score = log_prob_to_leak_score(20.0)
    assert score > 0.99


def test_strictly_monotonic_in_log_prob():
    """Higher log_prob (less surprising target) must always yield
    higher leak_score — never flat, never inverted."""
    samples = [-30, -10, -5, -2, -1, 0, 1, 5]
    scores = [log_prob_to_leak_score(lp) for lp in samples]
    for prev, curr in zip(scores, scores[1:]):
        assert curr > prev


def test_output_always_in_unit_interval():
    """Even adversarial inputs must produce a valid bounded score."""
    for lp in (-1e6, -100.0, -2.0, 0.0, 100.0, 1e6):
        score = log_prob_to_leak_score(lp)
        assert 0.0 <= score <= 1.0


def test_custom_shift_moves_the_midpoint():
    """If midpoint is shifted to -5, then log_prob=-5 yields 0.5."""
    assert math.isclose(
        log_prob_to_leak_score(-5.0, shift=-5.0, scale=2.0), 0.5, abs_tol=1e-9,
    )


def test_smaller_scale_makes_the_curve_sharper():
    """Smaller scale -> steeper transition. With scale=0.5, log_prob=-1
    (one nat above midpoint at -2) should yield a much higher score
    than with scale=2.0 at the same point.
    """
    sharp = log_prob_to_leak_score(-1.0, shift=-2.0, scale=0.5)
    gentle = log_prob_to_leak_score(-1.0, shift=-2.0, scale=2.0)
    assert sharp > gentle
