"""Tests for the v5 patch + deferred v4 caps: damage caps (P0), accuracy-as-a-read
(P2), and same-tier canon assignment (P3). Offline, deterministic."""

import random

from config import settings
from game import combat, generator
from game.state import Complication, Fighter, GameState, Technique


class FixedRandom:
    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def mk(name, hp=100, ce=100, **kw):
    return Fighter(company="T", model_id="qwen2.5:7b", character_name=name,
                   hp=hp, max_hp=100, ce=ce, max_ce=100, **kw)


def mk_state(fighters, rng_value=None):
    st = GameState(fighters={f.character_name: f for f in fighters})
    if rng_value is not None:
        st._rng = FixedRandom(rng_value)  # type: ignore[assignment]
    return st


def tech(power, tags=(), accuracy=0.95, costs=()):
    comps = [Complication(name=f"c{i}", description="concrete drawback", cost=c)
             for i, c in enumerate(costs)]
    return Technique(name="T", power=power, complications=comps, tags=list(tags),
                     accuracy=accuracy)


FULL = round(settings.CE_FACTOR_FRACTION * 100)


# --- P0: damage caps ---
def test_single_hit_capped_at_fraction_of_max_hp():
    atk, tgt = mk("A"), mk("B")
    tgt.has_acted = True
    st = mk_state([atk, tgt], rng_value=0.99)
    dmg = combat.resolve_attack(st, atk, tgt, tech(10, tags=("melee",)), FULL,
                                sure_hit_active=False, events=[], tick=2)
    assert dmg <= round(settings.MAX_SINGLE_HIT_FRACTION * tgt.max_hp)


def test_first_tick_protection_floors_at_1():
    atk, tgt = mk("A"), mk("B", hp=10)
    tgt.has_acted = False     # has not acted yet this round
    st = mk_state([atk, tgt], rng_value=0.99)
    combat.resolve_attack(st, atk, tgt, tech(10, tags=("melee",)), FULL,
                          sure_hit_active=False, events=[], tick=1)
    assert tgt.hp == 1        # cannot be dropped below 1 before acting


# --- P2: accuracy is a read, not a dice roll ---
def test_telegraphed_attack_auto_misses_a_dodger():
    atk, tgt = mk("A"), mk("B")
    tgt.has_acted = True
    st = mk_state([atk, tgt], rng_value=0.5)   # eff accuracy nudge = 0
    star = tech(6, tags=("finisher",), accuracy=0.60)
    dmg = combat.resolve_attack(st, atk, tgt, star, FULL, sure_hit_active=False,
                                events=[], tick=2, target_action="dodge")
    assert dmg == 0


def test_telegraphed_attack_lands_if_target_does_not_evade():
    atk, tgt = mk("A"), mk("B")
    tgt.has_acted = True
    st = mk_state([atk, tgt], rng_value=0.5)
    star = tech(6, tags=("finisher",), accuracy=0.60)
    dmg = combat.resolve_attack(st, atk, tgt, star, FULL, sure_hit_active=False,
                                events=[], tick=2, target_action="attack")
    assert dmg > 0


def test_sure_hit_ignores_dodging():
    atk, tgt = mk("A"), mk("B")
    tgt.has_acted = True
    st = mk_state([atk, tgt], rng_value=0.5)
    shrine = tech(6, tags=("sure-hit",), accuracy=0.95)
    dmg = combat.resolve_attack(st, atk, tgt, shrine, FULL, sure_hit_active=True,
                                events=[], tick=2, target_action="dodge")
    assert dmg > 0


def test_mid_accuracy_grazes_a_dodger():
    a1, t1 = mk("A"), mk("B")
    t1.has_acted = True
    full = combat.resolve_attack(mk_state([a1, t1], 0.99), a1, t1, tech(6, tags=("melee",), accuracy=0.85),
                                 FULL, sure_hit_active=False, events=[], tick=2, target_action="attack")
    a2, t2 = mk("A"), mk("B")
    t2.has_acted = True
    grazed = combat.resolve_attack(mk_state([a2, t2], 0.5), a2, t2, tech(6, tags=("melee",), accuracy=0.85),
                                   FULL, sure_hit_active=False, events=[], tick=2, target_action="dodge")
    assert 0 < grazed < full


# --- P3: same-tier canon assignment ---
def test_assign_canon_round_same_tier_and_unique():
    fighters = [mk(f"F{i}") for i in range(4)]
    techs = generator.assign_canon_round(fighters, 1, random.Random(7))
    assert len({t.tier for t in techs}) == 1            # all one tier
    assert len({t.name for t in techs}) == 4            # all unique
    lo, hi = settings.TIER_NET_BAND[techs[0].tier]
    for t in techs:
        assert lo - 0.6 <= generator._net_power(t) <= hi + 0.6   # net_power in band
