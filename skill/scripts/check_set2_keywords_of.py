#!/usr/bin/env python3
"""
Regression gate (2026-10-29, set 2): "give another friendly unit my keywords and +[M] equal to my Might this turn." (Kato
the Arm) - grant_keywords_of, and a this-turn give of the source's own Might.

  K1 copied     the source has [Deflect] and [Assault 2]: the target has both this turn (Assault at 2), and its Might is
                its own plus the source's (5 + 3)
  K2 gone       the source left the board (a new object) before it resolves: no keyword is given (the instruction is
                ignored, Core 359.3.e.12); the give of its Might is ignored too
  K3 outside    a source with a keyword the engine cannot grant ([Deathknell]): refused by name, nothing dropped
  K4 none       a source with no keyword: nothing is granted (a no_op)
  V             a program that names the source itself (keywords_from), or another duration, is refused

    python skill/scripts/check_set2_keywords_of.py
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from check_effect_ir import base_state  # noqa: E402
from effect_ir import (PROGRAM_VERSION, apply_program, characteristics, effective_might, object_identity,  # noqa: E402
                       validate_program)
from rules_core import CORE_RULESET, FAQ_AS_OF  # noqa: E402

errors: list[str] = []


def fail(label, why) -> None:
    errors.append(f"{label}: {why}")


def unit(owner, might, **extra):
    return {"owner": owner, "controller": owner, "kind": "unit", "base_might": might, "might_modifiers": [], "damage": 0,
            "exhausted": False, **extra}


def board(**source):
    state = base_state()
    state["objects"]["kato"] = unit("p1", 3, **source)
    state["objects"]["pal"] = unit("p1", 5)
    state["players"]["p1"]["zones"]["base"] += ["kato", "pal"]
    return state


def program(state, effects):
    return {"schema_version": PROGRAM_VERSION, "ruleset": {"core": CORE_RULESET, "faq_as_of": FAQ_AS_OF},
            "program_id": "kato", "controller": "p1", "source_object": "kato",
            "source_identity": object_identity(state, "kato") or "kato@0", "effects": effects}


def target(state):
    return {"object_id": "pal", "chosen_zone_class": "board", "kind": "unit", "controller_relation": "friendly",
            "bound_identity": object_identity(state, "pal")}


def kato(state):
    return [{"op": "grant_keywords_of", "effect_id": "kw", "target": target(state), "duration": "this_turn", "source": "kato"},
            {"op": "modify_might", "effect_id": "mm", "target": target(state), "duration": "this_turn", "source": "kato",
             "amount_ref": {"kind": "program_source_current_might"}}]


def main() -> int:
    state = board(keywords=["deflect", "assault"], assault_value=2)
    done = apply_program(state, program(state, kato(state)))
    if not done.get("committed"):
        fail("K1", f"refused: {done.get('errors') or done.get('reason')}")
    else:
        kws = characteristics(done["next_state"], "pal")["keywords"]
        if kws.get("assault") != 2 or "deflect" not in kws or effective_might(done["next_state"], "pal") != 8:
            fail("K1", f"the target has {kws}, Might {effective_might(done['next_state'], 'pal')} - not Deflect, Assault 2, 8")
    gone = board(keywords=["deflect"])
    program_gone = program(gone, kato(gone))
    gone["players"]["p1"]["zones"]["base"].remove("kato")
    gone["players"]["p1"]["zones"]["trash"].append("kato")
    gone["objects"]["kato"]["identity"] = "kato@9"
    done = apply_program(gone, program_gone)
    if not done.get("committed") or "deflect" in characteristics(done["next_state"], "pal")["keywords"] \
            or effective_might(done["next_state"], "pal") != 5:
        fail("K2", f"a source gone: {done.get('reason') or done.get('errors') or characteristics(done['next_state'], 'pal')['keywords']}")
    odd = board(keywords=["deathknell"])
    done = apply_program(odd, program(odd, kato(odd)[:1]))
    if done.get("committed") or not done.get("unsupported"):
        fail("K3", f"a source with Deathknell: {done.get('committed')} {done.get('reason')}")
    bare = board()
    done = apply_program(bare, program(bare, kato(bare)[:1]))
    events = [t for t in (done.get("trace") or []) if t.get("effect_id") == "kw"]
    if not done.get("committed") or not events or events[0].get("outcome") != "no_op":
        fail("K4", f"a source with no keyword: {done.get('committed')} {[e.get('outcome') for e in events]}")
    for label, bad in (("keywords_from named", {**kato(state)[0], "keywords_from": "pal"}),
                       ("permanent", {**kato(state)[0], "duration": "permanent"})):
        if not any("grant_keywords_of" in p for p in validate_program(program(state, [bad]))):
            fail("V", f"{label} validated")
    if errors:
        print("FAILED: set 2 grant_keywords_of")
        for e in errors:
            print("  - " + e)
        return 1
    print("OK: 'my keywords' are the source's as it executes, values kept, granted this turn (479.3); a source gone gives "
          "none, one the engine cannot grant is refused by name; '+[M] equal to my Might' gives the source's Might")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
