"""HGA genetic operators adapted for agentic-fitness search.

Upstream AutoDAN (Liu et al. 2024) uses LM-based mutation (call the
target model to rephrase a prompt). That works when fitness is
log-likelihood of a target string. For our setting — fitness is an
audit-log check on a mock-agent invocation — each fitness eval
already costs one full agent turn (LLM + tool dispatch + audit).
Per-mutation LM calls would double the budget.

These operators stay lexical: sentence-level crossover, word-level
shuffle / drop / duplicate, and seed-grafting. For the T-001 control
run this is sufficient — the hypothesis is "no rhetorical reframing
bypasses AuthenticatedToolNode," and lexical perturbations over the
seeded smuggling templates exercise that hypothesis efficiently.

For T-006 / T-005 (research phases), adding LM-based sentence
rephrase as an optional operator may help convergence. Guarded
behind a `use_lm_mutation` flag on HGAConfig so the T-001 run stays
cheap and deterministic.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD_SPLIT = re.compile(r"\s+")


@dataclass
class HGAConfig:
    population_size: int = 64
    elite_k: int = 4
    crossover_rate: float = 0.5
    mutation_rate: float = 0.3
    # Per-word probability of being shuffled/dropped/duplicated.
    word_op_prob: float = 0.05
    seed: int = 1


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def words(text: str) -> list[str]:
    return [w for w in _WORD_SPLIT.split(text.strip()) if w]


def join_sentences(segments: list[str]) -> str:
    return " ".join(s.strip() for s in segments if s.strip())


def crossover(parent_a: str, parent_b: str, rng: random.Random) -> str:
    """Sentence-level single-point crossover.

    Takes a prefix from parent_a and a suffix from parent_b at a
    random cut point. If either parent has fewer than 2 sentences,
    falls back to seed-grafting (inject one of parent_b's sentences
    into a random position in parent_a)."""
    a_sents = sentences(parent_a)
    b_sents = sentences(parent_b)
    if not a_sents or not b_sents:
        return parent_a

    if len(a_sents) < 2 or len(b_sents) < 2:
        # Graft: insert one random sentence from b into a.
        donor = rng.choice(b_sents)
        insert_at = rng.randint(0, len(a_sents))
        new = a_sents[:insert_at] + [donor] + a_sents[insert_at:]
        return join_sentences(new)

    cut_a = rng.randint(1, len(a_sents) - 1)
    cut_b = rng.randint(1, len(b_sents) - 1)
    return join_sentences(a_sents[:cut_a] + b_sents[cut_b:])


def mutate(prompt: str, rng: random.Random, word_op_prob: float) -> str:
    """Per-word perturbation: shuffle adjacent pairs, drop a word,
    duplicate a word. Rates stay low so most of the prompt's
    semantic signal survives a single mutation.

    Also, with 10% probability, shuffles sentence order.
    """
    ws = words(prompt)
    if not ws:
        return prompt

    i = 0
    mutated: list[str] = []
    while i < len(ws):
        if rng.random() < word_op_prob:
            op = rng.choice(("swap", "drop", "dup"))
            if op == "swap" and i + 1 < len(ws):
                mutated.extend([ws[i + 1], ws[i]])
                i += 2
                continue
            if op == "drop":
                i += 1
                continue
            if op == "dup":
                mutated.extend([ws[i], ws[i]])
                i += 1
                continue
        mutated.append(ws[i])
        i += 1

    out = " ".join(mutated)

    if rng.random() < 0.10:
        sents = sentences(out)
        rng.shuffle(sents)
        out = join_sentences(sents)

    return out


def roulette_select(
    fitnesses: list[float], n: int, rng: random.Random,
) -> list[int]:
    """Pick `n` parent indices by fitness-proportional sampling.

    If all fitnesses are zero (expected for T-001 control), falls
    back to uniform random — prevents division by zero AND matches
    the right behavior: when no prompt is "more fit" than another,
    HGA should explore uniformly.
    """
    total = sum(fitnesses)
    if total <= 0.0:
        return [rng.randrange(len(fitnesses)) for _ in range(n)]

    picks: list[int] = []
    for _ in range(n):
        r = rng.uniform(0.0, total)
        acc = 0.0
        for i, f in enumerate(fitnesses):
            acc += f
            if acc >= r:
                picks.append(i)
                break
        else:
            picks.append(len(fitnesses) - 1)
    return picks


def step_generation(
    population: list[str],
    fitnesses: list[float],
    config: HGAConfig,
    rng: random.Random,
) -> list[str]:
    """Produce the next generation: top-k elites survive unchanged;
    the rest are children of selected parents via crossover +
    optional mutation.
    """
    assert len(population) == len(fitnesses) == config.population_size

    # Elites: highest fitness first. Ties resolved by original index
    # (stable) — deterministic given seed.
    ranked = sorted(
        range(len(population)), key=lambda i: fitnesses[i], reverse=True,
    )
    elites = [population[i] for i in ranked[: config.elite_k]]

    next_gen: list[str] = list(elites)
    n_children = config.population_size - len(elites)
    parents = roulette_select(fitnesses, 2 * n_children, rng)

    for j in range(n_children):
        p_a = population[parents[2 * j]]
        p_b = population[parents[2 * j + 1]]
        child = crossover(p_a, p_b, rng) if rng.random() < config.crossover_rate else p_a
        if rng.random() < config.mutation_rate:
            child = mutate(child, rng, config.word_op_prob)
        next_gen.append(child)

    return next_gen


def seed_population(
    seeds: list[str], config: HGAConfig, rng: random.Random,
) -> list[str]:
    """Fill a starting population from `seeds`. If fewer seeds than
    population_size, mutate duplicates to diversify generation 0 so
    selection has variance to work with.
    """
    pop: list[str] = []
    i = 0
    while len(pop) < config.population_size:
        base = seeds[i % len(seeds)]
        if i >= len(seeds):
            base = mutate(base, rng, config.word_op_prob * 2)
        pop.append(base)
        i += 1
    return pop
