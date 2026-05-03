"""Load Llama 3.1 8B Instruct on Apple MPS for HGA surrogate use.

HuggingFace Transformers path (not Ollama) because HGA needs raw
forward-pass access for momentum-word scoring and GCG needs gradient
access. See autodan/README.md S2 for the rationale.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

DEFAULT_MODEL_ID = os.environ.get(
    "SURROGATE_MODEL_PATH", "meta-llama/Llama-3.1-8B-Instruct",
)


@dataclass
class Surrogate:
    model: Any
    tokenizer: Any
    device: torch.device
    model_id: str


def load_surrogate(
    model_id: str = DEFAULT_MODEL_ID,
    *,
    dtype: torch.dtype = torch.bfloat16,
) -> Surrogate:
    if not torch.backends.mps.is_available():
        raise RuntimeError(
            "MPS unavailable. This lab is MacBook-bound. "
            "Verify torch.backends.mps.is_available() and your torch build."
        )
    device = torch.device("mps")

    tokenizer = AutoTokenizer.from_pretrained(model_id)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    model = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=dtype, low_cpu_mem_usage=True,
    ).to(device)
    # Inference-only: disable dropout and BatchNorm training-time stats.
    model.train(False)

    return Surrogate(
        model=model, tokenizer=tokenizer, device=device, model_id=model_id,
    )


def smoke_forward_pass(surrogate: Surrogate) -> None:
    """Single forward pass, fails loudly if the model is broken."""
    inputs = surrogate.tokenizer(
        "Hello, world.", return_tensors="pt",
    ).to(surrogate.device)
    with torch.inference_mode():
        outputs = surrogate.model(**inputs)
    logits = outputs.logits
    if logits.shape[-1] < surrogate.tokenizer.vocab_size:
        raise RuntimeError(
            f"logits dim {logits.shape[-1]} < vocab size "
            f"{surrogate.tokenizer.vocab_size}, model/tokenizer mismatch"
        )


if __name__ == "__main__":
    s = load_surrogate()
    smoke_forward_pass(s)
    print(f"OK: {s.model_id} on {s.device}")
