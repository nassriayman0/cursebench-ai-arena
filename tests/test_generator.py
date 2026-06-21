"""Unit tests for the BALANCE CORE — game/generator.enforce_law.

Offline (no LLM): the validator is pure Python. Covers the invariant, phase
ceilings, exploitable-complication guarantee, vague rejection, handicap
consistency, and a fuzz sweep across all three phases (the Step 3 DoD).
"""

import random

from config import settings
from game.generator import (ComplicationDraft, TechniqueDraft, enforce_law,
                            is_lawful, law_violations, safe_fallback)
from game.state import Complication, Technique


def _draft(power, costs, vague=False, is_domain=False, is_rct=False, exploitable=False):
    comps = [ComplicationDraft(
        name=f"c{i}",
        description="sometimes weaker" if vague else "A concrete, telegraphed opening enemies can exploit",
        cost=c, exploitable=exploitable,
    ) for i, c in enumerate(costs)]
    return TechniqueDraft(name="T", power=power, complications=comps,
                          is_domain=is_domain, is_rct=is_rct, tags=["melee"])


def test_underpowered_complications_clamp_power_down():
    # power 9 with NO complications must be clamped to BASELINE (3) in phase 1.
    tech = enforce_law(_draft(9, []), phase=1, round_number=1)
    assert is_lawful(tech, 1)
    assert tech.power == settings.BASELINE_POWER  # 3


def test_lawful_high_power_kept():
    # power 9 with 6 cost in phase 2 (ceiling 9) satisfies the law and is kept.
    tech = enforce_law(_draft(9, [3, 3]), phase=2, round_number=4)
    assert tech.power == 9
    assert tech.total_complication_cost() >= settings.required_complication_cost(9)
    assert is_lawful(tech, 2)


def test_phase_ceiling_clamped():
    # phase 3 ceiling is 4; a power-8 draft must clamp to <= 4.
    tech = enforce_law(_draft(8, [5]), phase=3, round_number=8)
    assert tech.power <= settings.power_ceiling_for_phase(3)
    assert is_lawful(tech, 3)


def test_exploitable_complication_guaranteed():
    # above baseline, at least one complication must be exploitable.
    tech = enforce_law(_draft(7, [4], exploitable=False), phase=1, round_number=1)
    assert any(c.exploitable for c in tech.complications)


def test_vague_complications_rejected():
    tech = enforce_law(_draft(7, [5], vague=True), phase=2, round_number=4)
    assert all("sometimes weaker" not in c.description for c in tech.complications)


def test_handicap_consistency():
    tech = enforce_law(_draft(6, [3], is_domain=True, is_rct=True), phase=2,
                       round_number=5, handicaps=["no_domain", "no_rct"])
    assert tech.is_domain is False
    assert tech.is_rct is False


def test_law_violations_detects_broken_technique():
    broken = Technique(name="OP", power=9, complications=[], phase_origin=1)
    problems = law_violations(broken, phase=1)
    assert problems  # not lawful
    assert not is_lawful(broken, 1)


def test_safe_fallback_is_lawful_in_every_phase():
    for phase, rnd in [(1, 1), (2, 5), (3, 9)]:
        tech = safe_fallback(phase, rnd)
        assert is_lawful(tech, phase)


def test_fuzz_enforce_law_always_lawful():
    """200 adversarial drafts across all phases must each come out lawful."""
    rng = random.Random(0)
    for _ in range(200):
        power = rng.randint(1, 12)                       # includes over-ceiling
        costs = [rng.randint(1, 6) for _ in range(rng.randint(0, 4))]
        vague = rng.random() < 0.3
        phase = rng.choice([1, 2, 3])
        draft = _draft(power, costs, vague=vague,
                       is_domain=rng.random() < 0.5, exploitable=rng.random() < 0.5)
        tech = enforce_law(draft, phase, round_number=1)
        assert not law_violations(tech, phase), (power, costs, phase, tech)
