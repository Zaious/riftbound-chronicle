#!/usr/bin/env python3
"""
Property-style determinism and atomicity checks for the typed effect IR.

check_effect_ir.py asserts what specific programs do. This asserts what every
supported program must do regardless of what it does, over many generated
programs -- the class of failure that hand-written cases systematically miss,
because the case author picks the inputs and unconsciously picks the ones that
work.

Five properties, each of which would be a correctness bug if violated:

  P1 Purity      -- applying a program never mutates the caller's state. A
                    consumer holding the confirmed snapshot must still hold it.
  P2 Determinism -- the same (state, program) always produces a byte-identical
                    result, including every hash and the whole trace. Engine
                    evidence that is not reproducible is not evidence.
  P3 Atomicity   -- a program that does not commit leaves no next_state and no
                    partial application. All effects or none; a half-applied
                    program is a state nobody can audit.
  P4 Coherence   -- a committed result's next_state is valid, and its declared
                    next_state_hash really is that state's hash.
  P5 Portability -- hashes do not depend on interpreter run state. Verified in
                    subprocesses under different PYTHONHASHSEED values, because
                    a dict-ordering dependency reproduces perfectly within one
                    process and breaks across machines.

Generation is seeded and fixed, so a failure names a seed that reproduces it.
"""

from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state, program  # noqa: E402
from effect_ir import (  # noqa: E402
    CORE_RULESET,
    FAQ_AS_OF,
    PROGRAM_VERSION,
    apply_program,
    hash_value,
    validate_state,
)

SEEDS = (11, 137, 2029, 31337)
PROGRAMS_PER_SEED = 60
BOARD_OBJECTS = ("u1", "u2")
PLAYERS = ("p1", "p2")


def random_effect(rng: random.Random, index: int) -> dict:
    """One effect from the supported vocabulary, valid or plausibly invalid.

    Deliberately includes references to absent objects and oversized counts: a
    program that cannot complete is exactly the case where atomicity matters,
    so the generator must be able to produce one.
    """
    op = rng.choice([
        "draw", "recycle_one", "move_board_object", "modify_might", "deal_damage",
        "heal_damage", "ready", "exhaust", "add_resource", "kill", "play_token",
    ])
    effect: dict = {"effect_id": f"e{index}", "op": op}
    ghost = rng.random() < 0.15  # sometimes name an object that is not there
    obj = "ghost-object" if ghost else rng.choice(BOARD_OBJECTS)
    if op == "draw":
        effect.update({"player": rng.choice(PLAYERS), "count": rng.choice([1, 1, 2, 5])})
    elif op == "recycle_one":
        effect.update({"object_id": "ghost-card" if ghost else rng.choice(["c3", "c1"])})
    elif op == "move_board_object":
        destination = rng.choice([
            {"kind": "battlefield", "battlefield": "bf1"},
            {"kind": "base", "player": rng.choice(PLAYERS)},
        ])
        effect.update({"object_id": obj, "destination": destination})
    elif op == "modify_might":
        effect.update({"object_id": obj, "amount": rng.choice([-2, -1, 1, 2, 3]),
                       "duration": rng.choice(["this_turn", "unlimited"]), "source": "property-suite"})
    elif op in ("deal_damage", "heal_damage"):
        effect.update({"object_id": obj, "amount": rng.choice([1, 2, 3, 6])})
    elif op in ("ready", "exhaust", "kill"):
        effect.update({"object_id": obj})
    elif op == "add_resource":
        if rng.random() < 0.5:
            effect.update({"player": rng.choice(PLAYERS), "resource": "energy", "amount": rng.choice([1, 2])})
        else:
            effect.update({"player": rng.choice(PLAYERS), "resource": "power",
                           "domain": rng.choice(["fury", "calm", "mind"]), "amount": 1})
    elif op == "play_token":
        controller = rng.choice(PLAYERS)
        effect.update({
            "object_id": f"token-{index}", "owner": controller, "controller": controller,
            "token_kind": "unit", "base_might": rng.choice([1, 2, 3]),
            "destination": {"kind": "base", "player": controller},
        })
    return effect


def random_program(rng: random.Random, label: str) -> dict:
    effects = [random_effect(rng, index) for index in range(rng.randint(1, 4))]
    return {
        "schema_version": PROGRAM_VERSION,
        "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
        "program_id": label,
        "controller": rng.choice(PLAYERS),
        "effects": effects,
    }


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def check_properties() -> list[str]:
    failures: list[str] = []
    committed_count = 0
    rejected_count = 0

    for seed in SEEDS:
        rng = random.Random(seed)
        for index in range(PROGRAMS_PER_SEED):
            label = f"prop-{seed}-{index}"
            state = base_state()
            candidate = random_program(rng, label)
            guard_hash = hash_value(state)
            guard_copy = copy.deepcopy(state)

            first = apply_program(state, candidate)

            # P1: the caller's state is untouched, whatever the outcome.
            if hash_value(state) != guard_hash or state != guard_copy:
                failures.append(f"{label}: apply_program mutated the caller's state")
                state = guard_copy

            # P2: byte-identical on a repeat run, from an equal but distinct state.
            second = apply_program(copy.deepcopy(guard_copy), copy.deepcopy(candidate))
            if canonical(first) != canonical(second):
                failures.append(f"{label}: result is not deterministic across identical inputs")

            if first.get("input_state_hash") != guard_hash:
                failures.append(f"{label}: input_state_hash does not describe the state that was passed in")

            if first.get("committed") is True:
                committed_count += 1
                # P4: a committed result is internally coherent.
                next_state = first.get("next_state")
                if not isinstance(next_state, dict):
                    failures.append(f"{label}: committed result carries no next_state")
                else:
                    if state_errors := validate_state(next_state):
                        failures.append(f"{label}: committed next_state is invalid: {state_errors}")
                    if first.get("next_state_hash") != hash_value(next_state):
                        failures.append(f"{label}: next_state_hash does not match its own next_state")
            else:
                rejected_count += 1
                # P3: nothing partially applied, and no state handed back that a
                # consumer could mistake for the result.
                if "next_state" in first:
                    failures.append(f"{label}: uncommitted result still returned a next_state ({first.get('reason') or first.get('errors')})")

            # P3, the sharper form: a program that commits, with one failing
            # effect appended, must abandon the whole program -- the prefix that
            # would have succeeded must not survive.
            if first.get("committed") is True:
                poisoned = copy.deepcopy(candidate)
                poisoned["program_id"] = f"{label}-poisoned"
                poisoned["effects"].append({"effect_id": "unsupported-tail", "op": "counter", "chain_item_id": "x"})
                spoiled = apply_program(copy.deepcopy(guard_copy), poisoned)
                if spoiled.get("committed") is True:
                    failures.append(f"{label}: appending an unsupported effect still committed the program")
                elif "next_state" in spoiled:
                    failures.append(f"{label}: an abandoned program returned a partially applied next_state")

    if not committed_count:
        failures.append("no generated program committed; the suite is exercising nothing")
    if not rejected_count:
        failures.append("no generated program was rejected; the atomicity properties never ran")

    return failures


HASH_PROBE = (
    "import sys, json; sys.path.insert(0, {script_dir!r});"
    "from check_effect_ir import base_state;"
    "from effect_ir import hash_value, apply_program;"
    "state = base_state();"
    "program = {{'schema_version': 'riftbound-effect-program.v1',"
    " 'ruleset': {{'core': {core!r}, 'faq_as_of': {faq!r}}},"
    " 'program_id': 'hash-probe', 'controller': 'p1',"
    " 'effects': [{{'op': 'deal_damage', 'object_id': 'u1', 'amount': 2}},"
    " {{'op': 'draw', 'player': 'p1', 'count': 1}}]}};"
    "result = apply_program(state, program);"
    "print(json.dumps([hash_value(state), result['next_state_hash'], result['input_state_hash']]))"
)


def check_hash_portability() -> list[str]:
    """P5: hashes must not vary with interpreter run state.

    A hash that depends on dict iteration order is stable inside one process and
    differs across machines, which would silently break check_id determinism and
    every cached engine result.
    """
    failures: list[str] = []
    source = HASH_PROBE.format(script_dir=str(SCRIPT_DIR), core=CORE_RULESET, faq=FAQ_AS_OF)
    observed = []
    for hash_seed in ("0", "1", "12345"):
        environment = {**os.environ, "PYTHONHASHSEED": hash_seed}
        run = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True,
                             env=environment, cwd=str(SCRIPT_DIR.parent.parent), check=False)
        if run.returncode != 0:
            failures.append(f"hash portability probe failed under PYTHONHASHSEED={hash_seed}: {run.stderr.strip()}")
            return failures
        observed.append(json.loads(run.stdout))
    if any(entry != observed[0] for entry in observed[1:]):
        failures.append(f"hashes vary with PYTHONHASHSEED: {observed}")
    return failures


def main() -> int:
    failures = check_properties() + check_hash_portability()
    total = len(SEEDS) * PROGRAMS_PER_SEED
    print(f"[info] effect IR properties: {total} generated programs over {len(SEEDS)} fixed seeds; "
          "purity, determinism, atomic rollback, committed-state coherence, and cross-process hash stability.")
    if failures:
        print("\n[errors]")
        for failure in dict.fromkeys(failures):
            print(f"  - {failure}")
        print(f"\nFAILED: {len(failures)} effect-IR property violation(s).")
        return 1
    print("\nOK: supported effect programs are pure, deterministic, atomic, and hash-stable across processes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
