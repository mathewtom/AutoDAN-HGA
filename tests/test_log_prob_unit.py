"""Unit tests for `target_log_prob` using stub model + tokenizer.

Verifies the slicing, gather, and summation logic without loading the
real 8B. Real-model behavior (e.g. "Paris" scores higher than "banana"
after a France-themed prefix) is covered separately by the integration
test, which requires the surrogate to be loaded.
"""

from __future__ import annotations

import math

import torch

from surrogate.fitness.log_prob import target_log_prob


VOCAB_SIZE = 5
WIN_LOGP = math.log(0.9)
LOSE_LOGP = math.log(0.025)  # 0.1 spread across the 4 non-winner tokens


class _StubTokenizerOutput:
    """Mimics the object returned by HF tokenizers: .input_ids + .to()."""

    def __init__(self, ids: list[int]):
        self.input_ids = torch.tensor([ids], dtype=torch.long)

    def to(self, _device):
        return self


class StubTokenizer:
    """Each digit-character is one token ID. '012' -> [0, 1, 2]."""

    def __call__(self, text: str, add_special_tokens: bool = False,
                 return_tensors: str = "pt"):
        ids = [int(c) for c in text]
        return _StubTokenizerOutput(ids)


class StubModelOutput:
    def __init__(self, logits: torch.Tensor):
        self.logits = logits


class PositionalStubModel:
    """At input position k, the predicted "winner" token is (k mod V).

    Logits are constructed so log_softmax over the vocab returns:
      winner: log(0.9)        ~ -0.105
      others: log(0.025)      ~ -3.689   (each)
    Logits are independent of the input token values — only position
    matters. This makes the slicing/off-by-one logic the only thing
    under test.
    """

    def __init__(self) -> None:
        self.device = torch.device("cpu")

    def __call__(self, input_ids: torch.Tensor) -> StubModelOutput:
        batch, seq_len = input_ids.shape
        logits = torch.full(
            (batch, seq_len, VOCAB_SIZE),
            fill_value=LOSE_LOGP,
        )
        for k in range(seq_len):
            winner = k % VOCAB_SIZE
            logits[:, k, winner] = WIN_LOGP
        return StubModelOutput(logits)


def test_single_token_target_hits_winner_at_predicting_position():
    """Prefix length 2 (positions 0,1). Predicting position is N-1 = 1.
    Winner at position 1 is token 1. Target = '1' should yield log(0.9).
    """
    model = PositionalStubModel()
    tok = StubTokenizer()
    result = target_log_prob(model, tok, prefix_text="01", target_text="1")
    assert math.isclose(result, WIN_LOGP, abs_tol=1e-5)


def test_single_token_target_misses_winner():
    """Same prefix; target = '2' is NOT the winner at position 1.
    Expected log-prob is log(0.025), not log(0.9).
    """
    model = PositionalStubModel()
    tok = StubTokenizer()
    result = target_log_prob(model, tok, prefix_text="01", target_text="2")
    assert math.isclose(result, LOSE_LOGP, abs_tol=1e-5)


def test_multi_token_target_sums_per_token_logprobs():
    """Prefix length 3, target length 2. Predicting positions are
    N-1=2 and N-1+1=3. Winners are tokens 2 and 3. Target '23' hits
    both, so log-prob = 2 * log(0.9).
    """
    model = PositionalStubModel()
    tok = StubTokenizer()
    result = target_log_prob(model, tok, prefix_text="012", target_text="23")
    assert math.isclose(result, 2 * WIN_LOGP, abs_tol=1e-5)


def test_off_by_one_would_flip_winner_to_loser():
    """Regression guard: prefix='01', target='2'. With CORRECT slicing
    (position N-1=1), the winner is token 1 — target token 2 is a loser
    -> result = log(0.025). With an off-by-one (slicing position N=2),
    the winner WOULD be token 2 — target token 2 would match -> log(0.9).

    Asserting log(0.025) catches any future drift toward the wrong slice.
    """
    model = PositionalStubModel()
    tok = StubTokenizer()
    result = target_log_prob(model, tok, prefix_text="01", target_text="2")
    assert math.isclose(result, LOSE_LOGP, abs_tol=1e-5)
    assert not math.isclose(result, WIN_LOGP, abs_tol=1e-2)


def test_mixed_winner_and_loser_in_multi_token_target():
    """Prefix length 3, target length 2. Predicting positions are 2 and 3.
    Target '24' -> position 2 winner is token 2 (HIT), position 3 winner
    is token 3 (target says 4, MISS). Expected log-prob = log(0.9) + log(0.025).
    """
    model = PositionalStubModel()
    tok = StubTokenizer()
    result = target_log_prob(model, tok, prefix_text="012", target_text="24")
    expected = WIN_LOGP + LOSE_LOGP
    assert math.isclose(result, expected, abs_tol=1e-5)
