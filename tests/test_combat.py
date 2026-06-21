"""Unit tests for the deterministic combat engine (game/combat.py).

Offline: no LLM, all randomness either pure or via a FixedRandom stub so every
assertion is exact and seed-reproducible (the Step 4 DoD).
"""

import pytest

from config import settings
from game import combat
from game.state import Complication, Fighter, GameState, Handicap, Move, Technique


class FixedRandom:
    """Deterministic stand-in for state.rng — always returns `value`."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def mk(name, hp=100, ce=100, max_hp=100, max_ce=100, **kw):
    return Fighter(company="T", model_id="qwen2.5:7b", character_name=name,
                   hp=hp, max_hp=max_hp, ce=ce, max_ce=max_ce, **kw)


def mk_state(fighters, rng_value=None):
    state = GameState(fighters={f.character_name: f for f in fighters})
    if rng_value is not None:
        state._rng = FixedRandom(rng_value)  # type: ignore[assignment]
    return state


def tech(power, costs=(), tags=(), **kw):
    comps = [Complication(name=f"c{i}", description="concrete drawback", cost=c)
             for i, c in enumerate(costs)]
    return Technique(name="T", power=power, complications=comps, tags=list(tags), **kw)


# Spend that yields ce_factor == 1.0 (constant-relative so tuning won't break tests).
FULL = round(settings.CE_FACTOR_FRACTION * 100)


# --- §2 effective strength ---
def test_net_power_discount():
    assert combat.net_power(tech(9, costs=(3, 3))) == 6.0


def test_ce_factor_and_base_damage():
    f = mk("A")
    assert combat.ce_factor(FULL, 100) == 1.0
    assert combat.base_damage(f, tech(6), FULL) == settings.BASE_DMG * 6


# --- §3/§4 attack resolution ---
def test_basic_attack_with_mitigation():
    atk, tgt = mk("A"), mk("B")
    st = mk_state([atk, tgt], rng_value=0.99)  # no Black Flash
    dmg = combat.resolve_attack(st, atk, tgt, tech(9, costs=(3, 3)), FULL,
                                sure_hit_active=False, events=[], tick=1)
    expected = max(0, round(settings.BASE_DMG * 6 - settings.DEFENSE_FLAT))
    assert dmg == expected
    assert tgt.hp == 100 - expected
    assert atk.ce == 100 - FULL


def test_sure_hit_ignores_mitigation_and_beats_normal():
    atk, tgt = mk("A"), mk("B")
    st = mk_state([atk, tgt], rng_value=0.99)
    sure = combat.resolve_attack(st, atk, tgt, tech(5, tags=("sure-hit",)), FULL,
                                 sure_hit_active=True, events=[], tick=1)
    atk2, tgt2 = mk("A"), mk("B")
    st2 = mk_state([atk2, tgt2], rng_value=0.99)
    normal = combat.resolve_attack(st2, atk2, tgt2, tech(5, tags=("sure-hit",)), FULL,
                                   sure_hit_active=False, events=[], tick=1)
    assert sure == round(settings.BASE_DMG * 5 * settings.SURE_HIT_DOMAIN_MULT)
    assert sure > normal


def test_reinforce_reduces_damage():
    atk, tgt = mk("A"), mk("B")
    tgt.status.append("reinforced")
    tgt.reinforce_ce = 25
    st = mk_state([atk, tgt], rng_value=0.99)
    reinforced = combat.resolve_attack(st, atk, tgt, tech(8), 25,
                                       sure_hit_active=False, events=[], tick=1)
    atk2, plain = mk("A"), mk("B")
    st2 = mk_state([atk2, plain], rng_value=0.99)
    normal = combat.resolve_attack(st2, atk2, plain, tech(8), 25,
                                   sure_hit_active=False, events=[], tick=1)
    assert 0 <= reinforced < normal


# --- §7 healing & soul cap ---
def test_rct_heal_capped_by_soul_damage():
    f = mk("A", hp=50)
    f.soul_damage = 30                      # effective max 70
    healed = combat.heal_rct(f, 40)         # would heal 60
    assert f.hp == 70 and healed == 20 and f.ce == 60


def test_soul_sight_ignores_soul_cap():
    f = mk("A", hp=50)
    f.soul_damage = 30
    f.traits.append("soul_sight")
    combat.heal_rct(f, 40)
    assert f.hp == 100


# --- §6 Black Flash ---
def test_black_flash_proc_and_no_proc():
    f = mk("A")
    st = mk_state([f], rng_value=0.0)       # below base chance -> proc
    events = []
    crit = combat.black_flash_check(st, f, events, tick=1)
    assert crit == settings.BLACK_FLASH_MULTIPLIER
    assert "flow" in f.status
    assert f.rct_charge == 1                 # v2-C: Black Flash banks an RCT charge
    assert any(e.type == "BLACK FLASH" for e in events)

    g = mk("B")
    st2 = mk_state([g], rng_value=0.99)     # above any chance -> no proc
    assert combat.black_flash_check(st2, g, [], tick=1) == 1.0
    assert "flow" not in g.status and g.rct_charge == 0


# --- §8 domains ---
def test_two_domain_clash_winner_gets_sure_hit():
    a, b = mk("A"), mk("B")
    a.status.append("domain-open"); a.active_domain = tech(9)
    b.status.append("domain-open"); b.active_domain = tech(4)
    st = mk_state([a, b])
    result = combat.resolve_domains_this_tick(st, [], tick=1)
    assert result["A"] is True and result["B"] is False


def test_close_domains_cancel():
    a, b = mk("A"), mk("B")
    a.status.append("domain-open"); a.active_domain = tech(5)
    b.status.append("domain-open"); b.active_domain = tech(5)
    st = mk_state([a, b])
    result = combat.resolve_domains_this_tick(st, [], tick=1)
    assert result["A"] is False and result["B"] is False


def test_three_domain_collapse():
    a, b, c = mk("A"), mk("B"), mk("C")
    for f in (a, b, c):
        f.status.append("domain-open")
        f.active_domain = tech(7)
    st = mk_state([a, b, c])
    events = []
    result = combat.resolve_domains_this_tick(st, events, tick=1)
    assert all(v is False for v in result.values())
    assert all(f.hp == 100 - settings.DOMAIN_COLLAPSE_BACKLASH for f in (a, b, c))
    assert all("domain-open" not in f.status for f in (a, b, c))
    assert any(e.type == "DOMAIN CLASH COLLAPSE" for e in events)


# --- §10 legality ---
def test_legality_rejections_and_pass():
    atk = mk("A")
    atk.techniques.append(tech(5))
    atk.techniques[0].name = "Slash"
    tgt = mk("B")
    st = mk_state([atk, tgt])

    over = Move(actor="A", action="attack", target="B", technique_name="Slash", ce_spend=999)
    assert combat.validate_move(st, atk, over) is not None

    self_hit = Move(actor="A", action="attack", target="A", technique_name="Slash", ce_spend=10)
    assert combat.validate_move(st, atk, self_hit) is not None

    small_domain = Move(actor="A", action="domain_expansion", technique_name="Slash", ce_spend=10)
    assert combat.validate_move(st, atk, small_domain) is not None

    atk.handicaps.append(Handicap(kind="no_rct"))
    heal = Move(actor="A", action="heal_rct", ce_spend=10)
    assert combat.validate_move(st, atk, heal) is not None

    good = Move(actor="A", action="attack", target="B", technique_name="Slash", ce_spend=10)
    assert combat.validate_move(st, atk, good) is None


# --- §9 determinism ---
def test_initiative_is_seed_reproducible():
    def order_for_seed(seed):
        fs = [mk("A", ce=80), mk("B", ce=60), mk("C", ce=100), mk("D", ce=40)]
        st = GameState(fighters={f.character_name: f for f in fs}, rng_seed=seed)
        return [f.character_name for f in combat.initiative_order(st, fs)]

    assert order_for_seed(42) == order_for_seed(42)
