"""Compute the log-probability of a target string given a prefix.

Single primitive used by SystemPromptLeakFitness (Tier 2). For an
autoregressive LM, the probability of a target sequence given a prefix
factorizes as the product of per-token conditionals:

    P(t_1 ... t_M | prefix) = prod_{i=1..M} P(t_i | prefix, t_1 ... t_{i-1})

We compute the log of that — a sum of M per-token log-probabilities —
in a single forward pass.
"""

from __future__ import annotations

import torch


def target_log_prob(
    model,
    tokenizer,
    prefix_text: str,
    target_text: str,
) -> float:
    """Sum of log-probabilities the model assigns to `target_text` immediately
    following `prefix_text`, in nats.

    The caller is responsible for any chat templating in `prefix_text` —
    this helper is a pure log-prob primitive, not a chat wrapper.

    Note on tokenization: BPE tokenizers split text differently depending on
    whether a leading space is present. If `target_text` is meant to start
    the assistant's reply directly after a chat-template header, no leading
    space is needed. If it's meant to continue mid-sentence, the caller
    should include the leading space in `target_text`.
    """
    device = model.device

    prefix_ids = tokenizer(
        prefix_text, add_special_tokens=False, return_tensors="pt",
    ).input_ids.to(device)
    target_ids = tokenizer(
        target_text, add_special_tokens=False, return_tensors="pt",
    ).input_ids.to(device)

    full_ids = torch.cat([prefix_ids, target_ids], dim=1)

    with torch.inference_mode():
        logits = model(full_ids).logits

    N = prefix_ids.shape[1]
    M = target_ids.shape[1]
    target_logits = logits[0, N - 1 : N - 1 + M, :]

    log_probs = torch.log_softmax(target_logits.float(), dim=-1)
    token_log_probs = log_probs.gather(
        dim=1, index=target_ids[0].unsqueeze(-1),
    ).squeeze(-1)

    return token_log_probs.sum().item()
