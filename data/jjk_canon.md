# JJK Canon — Generator Reference (loaded into the technique-generator prompt)

Keep it terse: lists parse better than prose for small models.

## TECHNIQUE BANK (Phase 1 / rounds 1–3 — these are REAL Jujutsu Kaisen techniques)
In rounds 1–3 you MUST pick ONE technique from this list and use its REAL name (you may
add a short flavor subtitle, but keep the canonical name and its mechanic + complication).
Format: NAME | theme | power | mechanic | built-in complication | tags

- Limitless: Infinity | space | 9 | attacks never arrive; Blue pulls, Red repels, Hollow Purple erases | colossal CE, brain strain, needs RCT upkeep; beaten by space-targeting/nullify | [ranged, defense, sure-hit]
- Ten Shadows Technique | summoning | 7 | shadow shikigami (Divine Dogs, Nue, Max Elephant); Mahoraga adapts | a destroyed shikigami is gone for good; summons cost CE; Mahoraga can turn on the user | [summon, adaptive, melee]
- Malevolent Shrine: Dismantle & Cleave | cutting | 8 | invisible slashes; Cleave auto-cuts the weak; barrierless open-air domain | smaller sure-hit radius; the flame "Furnace" needs the cooking steps first | [melee, ranged, aoe, sure-hit]
- Straw Doll Technique: Resonance | voodoo | 6 | link a piece of the target, then hammer a nail to strike the SOUL at any range | needs a physical fragment (hair/blood) first; CE-heavy | [ranged, soul]
- Cursed Speech | command | 6 | spoken commands the target must obey ("Don't move", "Blast away") | strong commands tear the user's own throat (self-damage); must be heard | [control, self-damage, ranged]
- Ratio Technique | precision | 6 | mark a 7:3 point and strike it as a guaranteed critical | melee range only; CE per strike; struggles at range | [melee, crit]
- Idle Transfiguration | soul | 8 | reshape a touched target's soul (and your own body) | requires touch; only SOUL attacks harm the user back | [melee, soul, heal-self]
- Boogie Woogie | swap | 5 | clap to swap the positions of any two cursed-energy things | needs a clap (telegraph); pure utility, no direct damage | [utility, mobility]
- Blood Manipulation: Piercing Blood | blood | 6 | convert CE to blood; Convergence then fire blood at sonic speed | Convergence charge-up leaves you open; anemia/water weakness | [ranged, buff, melee]
- Construction | creation | 7 | materialize persistent matter from cursed energy | extremely CE-inefficient (very few uses) | [utility, ranged, summon]
- Star Rage: Bonbaie | mass | 7 | add imaginary mass to hits and to the Garuda shikigami | does NOT raise your own durability; telegraphed | [melee, ranged-finisher]
- Projection Sorcery | frames | 7 | 24 frames/sec; a mistimed touch freezes the target 1 second | you must also obey the 24-fps rule or freeze yourself; readable | [melee, control, self-risk]
- Cursed Spirit Manipulation: Maximum Uzumaki | curses | 7 | command absorbed curses; condense them into one swirling blast | absorbing curses costs CE + mental burden; Uzumaki is slow to charge | [summon, aoe]
- Disaster Flames (Jogo) | fire | 8 | volcanoes, magma, Ember Insects, Maximum Meteor | big moves need charge; weak to being out-classed in his own domain | [ranged, aoe, fire]
- Disaster Plants (Hanami) | nature | 7 | wooden constructs, draining seeds, bark armor | weak to FIRE; the seed-drain is slow | [melee, ranged, summon]
- Disaster Tides (Dagon) | water | 7 | endless cursed water + fish shikigami swarm | targets with no cursed energy can't be hit; best inside his domain | [ranged, summon, aoe]
- Mythical Beast Amber (Kashimo) | lightning | 9 | become living electricity; sure-hit lightning discharge, x-ray, sonic | ONE-TIME use — the body crumbles after | [ranged, sure-hit, melee]
- Idle Death Gamble: Jackpot (Hakari) | luck | 8 | a jackpot grants ~4 min of infinite CE + reflexive auto-heal | jackpot odds 1/239; near-useless until it hits | [heal-self, domain, buff]
- Jacob's Ladder / Technique Extinguishment (Angel) | holy | 8 | nullify ANY cursed technique; drop a pillar of purifying light | mercy/hesitation; output drops if she's wounded | [ranged, nullify, anti-technique]
- Sky Manipulation: Thin Ice Breaker (Uro) | space | 7 | grab the "sky" as a surface; fly, deflect, shatter it behind a target | her domain is hard to manifest; the frames are readable | [ranged, defense, melee]
- Copy (Yuta) | mimic | 8 | copy another sorcerer's innate technique after sampling them | needs a body part; only while Rika is manifested (5-min) or in his domain | [adaptive, copy]
- Comedian (Takaba) | reality | 9 | reality bends to whatever he finds genuinely funny — heal, nullify, conjure | only works if he TRULY finds it funny; he doesn't understand his own power | [reality, nullify, heal-self]
- Black Bird Manipulation: Bird Strike (Mei Mei) | crows | 6 | control crows + shared vision; a binding-vow kamikaze one-hit-kill | Bird Strike costs a crow's life (vow); interceptable before contact | [ranged, recon, summon]
- Granite Blast / Cursed Energy Discharge (Ryu) | output | 8 | raw concentrated energy beams — single, rapid, or homing | pure output, no finesse; no defense boost; telegraphed | [ranged, finisher]
- Boogie Woogie, Love Rendezvous (Kirara) | stars | 5 | mark targets as constellation stars to force their movement order | utility only; no direct damage | [control, utility]
- Contractual Re-Creation (Reggie) | contracts | 6 | burn a written receipt to materialize what it describes | needs the contract prepared first; weak body | [summon, ranged, utility]

Canon domains (use these names for domain_expansion in phase 1): Unlimited Void (Gojo — info-overload freeze),
Malevolent Shrine (Sukuna — barrierless auto-cut), Self-Embodiment of Perfection (Mahito — guaranteed soul-touch),
Chimera Shadow Garden (Megumi — unlimited summons), Coffin of the Iron Mountain (Jogo — volcano),
Horizon of the Captivating Skandha (Dagon — endless shikigami), Time Cell Moon Palace (Naoya — 24-fps freeze).

## GENERATION RULES BY PHASE
- **Phase 1 (rounds 1–3) — REAL CANON ONLY.** You MUST choose ONE technique from the Technique Bank above and keep its REAL name. Re-flavor its description to fit the fighter, but do NOT invent a new technique. Power 4–7. Keep the built-in complication.
- **Phase 2 (rounds 4–6) — Imaginary but lawful.** Invent freely (luck, memory theft, rule-rewrite, probability, gravity, time-slice). Power 5–9. High power demands harsh, concrete, exploitable complications summing to `power - 3`. ≥1 complication must be a baitable/dodgeable opening. Handicaps unlock (round 5+).
- **Phase 3 (rounds 7–10) — Bizarre / rare / weak.** Power 1–4. Strange and narrow (affects only X; works only while doing Y; turns A into B under condition C). Forces clever use of weak tools; reward combos.

## COMPLICATION LIBRARY (cost in parentheses — pick concrete, exploitable ones)
- Activation tell / visible charge-up (2) — enemy can interrupt or dodge.
- Requires physical contact (2).
- Requires a spoken phrase / gesture / clap (1) — interruptible.
- Single-use per round (3).
- Long cooldown after use (2).
- Self-damage on use (2).
- Heavy CE cost, can't act next tick (3).
- Narrow target set (only X kind of target/material/direction) (2).
- Must reveal the technique's rule to the enemy to activate it (2).
- Only works under a condition (low HP / in a domain / while moving / while singing) (2).
- Backfires if it misses (3).
- Can be fully negated by a named common counter (Simple Domain / Amplification / ranged soul-hit) (2).
- Locks out another of the user's abilities while active (2).

## VALIDATOR LAW (Python enforces — the generator should satisfy it up front)
1. `sum(complication.cost) >= max(0, power - 3)`.
2. complications must be concrete & triggered (no "sometimes weaker").
3. ≥1 complication is opponent-exploitable (baitable / dodgeable / a named counter).
4. `power <= phase ceiling` (phase1=7, phase2=9, phase3=4).
5. `is_domain` / `is_rct` flags consistent with the fighter's handicaps.

## MECHANIC RULES (the engine enforces these; the generator should respect them)
- R1 Sure-hit (successful Domain) bypasses normal mitigation/reinforcement.
- R2 Two-domain clash: higher net power wins; loser exposed to the winner's sure-hit. Close gap = slower.
- R3 THREE-OR-MORE domains in one tick = TOTAL COLLAPSE, no winner, all break (canon).
- R4 Domain Amplification negates one technique on contact, but you cannot use your own technique while amplifying (unless it is imbued in an already-open domain).
- R5 Simple Domain neutralizes a sure-hit but only delays a far stronger domain.
- R6 RCT/RCE heals CE→HP; blocked by `no_rct`; CANNOT heal `soul`-tagged damage without the `soul_sight` trait.
- R7 Black Flash is not at-will: a random proc on a CE-melee hit; ×2.5 and a round-long flow buff.
- R8 Binding Vow: accept a restriction (handicap / revealing a technique) for a validated future power bump.
- R9 Heavenly Restriction: a frail/no-CE body trades CE for physical stats; immune to domains; use sparingly.
- R10 Reinforcement (spend CE to cut incoming non-sure-hit damage) is always available to everyone.
