"""Round-trip test for state + persistence (Step 2 DoD)."""

from game.state import Complication, Fighter, GameState, Technique
from util.persistence import load_match, save_match


def make_state() -> GameState:
    seats = [("Anthropic", "claude-sonnet-4-6"), ("Qwen", "qwen2.5:7b"),
             ("Google", "gemma2:9b"), ("Meta", "llama3.1:8b")]
    fighters = {}
    for i, (company, model) in enumerate(seats):
        name = f"Fighter {i}"
        f = Fighter(company=company, model_id=model, character_name=name)
        f.techniques.append(Technique(
            name="Seed Technique", power=6, phase_origin=1,
            complications=[Complication(name="tell", description="visible wind-up",
                                        cost=2, exploitable=True)],
        ))
        fighters[name] = f
    return GameState(fighters=fighters, rng_seed=123, match_options={"match_id": "rt"})


def test_save_load_roundtrip(tmp_path):
    state = make_state()
    state.rng.random()  # advance RNG so its state is non-trivial
    path = save_match(state, saves_dir=str(tmp_path))

    loaded = load_match(path)
    assert loaded.model_dump() == state.model_dump()
    assert loaded.rng_seed == 123
    assert set(loaded.fighters) == set(state.fighters)
    assert loaded.fighters["Fighter 0"].techniques[0].name == "Seed Technique"
