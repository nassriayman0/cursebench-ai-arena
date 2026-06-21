"""Tests for the v2 balance patch: Black Flash -> RCT loop (C), generator
fairness (D), and the passivity penalty (B). Offline, deterministic."""

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


def tech(power, costs=(), tags=()):
    comps = [Complication(name=f"c{i}", description="concrete drawback", cost=c)
             for i, c in enumerate(costs)]
    return Technique(name="T", power=power, complications=comps, tags=list(tags))


FULL = round(settings.CE_FACTOR_FRACTION * 100)


# --- C: Black Flash odds rise with sustained pressure, and rebuild RCT ---
def test_black_flash_odds_rise_with_consecutive_hits():
    # rng 0.20: above base chance (0.08) but below the flow-boosted chance.
    cold = mk("A")
    cold.consecutive_ce_hits = 0
    assert combat.black_flash_check(mk_state([cold], 0.20), cold, [], 1) == 1.0
    hot = mk("B")
    hot.consecutive_ce_hits = 3   # 0.08 + min(0.24, 0.18) = 0.26 > 0.20 -> procs
    assert combat.black_flash_check(mk_state([hot], 0.20), hot, [], 1) == settings.BLACK_FLASH_MULTIPLIER


def test_post_black_flash_heal_is_cheaper_and_stronger():
    base = mk("A", hp=10)
    base.rct_charge = 0
    healed_base = combat.heal_rct(base, 20)

    charged = mk("B", hp=10)
    charged.rct_charge = 1
    ce_before = charged.ce
    healed_charged = combat.heal_rct(charged, 20)

    assert healed_charged > healed_base                       # +30% HP
    assert charged.rct_charge == 0                            # one charge consumed
    expected_cost = round(20 * (1 - settings.RCT_CHARGE_CE_DISCOUNT))
    assert charged.ce == ce_before - expected_cost           # -30% CE


# --- D: generator fairness ---
def test_damage_capable_and_cursed_strike():
    util = tech(5, tags=("utility", "swap"))
    melee = tech(5, tags=("melee",))
    assert not generator.is_damage_capable(util)
    assert generator.is_damage_capable(melee)
    assert generator.is_damage_capable(generator.cursed_strike(1))


def test_balance_round_spread_caps_at_max():
    # phase 2 (round 4), ceiling 9; no complications so net_power == power.
    techs = [tech(9), tech(8), tech(3), tech(2)]
    generator.balance_round_spread(techs, round_number=4)
    nets = [generator._net_power(t) for t in techs]
    assert max(nets) - min(nets) <= settings.NET_POWER_SPREAD_MAX + 1e-6


# --- B: passivity is punished ---
def test_passive_target_takes_more_damage():
    atk, tgt = mk("A"), mk("B")
    normal = combat.resolve_attack(mk_state([atk, tgt], 0.99), atk, tgt, tech(6), FULL,
                                   sure_hit_active=False, events=[], tick=1)
    atk2, ptgt = mk("A"), mk("B")
    ptgt.status.append("passive")
    passive = combat.resolve_attack(mk_state([atk2, ptgt], 0.99), atk2, ptgt, tech(6), FULL,
                                    sure_hit_active=False, events=[], tick=1)
    assert passive > normal
