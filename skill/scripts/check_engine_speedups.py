#!/usr/bin/env python3
"""The two engine speed-ups of 2026-11-03 give the answers the engine gave without them.

  K1-K6  state_copy.deepcopy is copy.deepcopy on the engine's value types: equal copies, the same sharing (one copy per
         original container), cycles, a tuple of atoms returned as is, a tuple holding a container copied, a dict
         subclass and an object of another type handed to copy.deepcopy with the same memo
  V1-V5  validate_state's content cache: a valid and an invalid state answer as validate_state_uncached does, every
         time; a state mutated after it was validated is validated again (the cache is keyed by content, not by the
         object); two states JSON encodes alike ({1: x} and {"1": x}) are told apart; the caller may change the list
         it gets back without changing the cache; an unpicklable state is validated uncached
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import effect_ir as IR  # noqa: E402
import state_copy  # noqa: E402
from check_effect_ir import base_state  # noqa: E402

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}{(': ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILS.append(name)


def shape(value, seen=None):
    """The value's structure with sharing made explicit: the n-th distinct container, and where it recurs."""
    seen = {} if seen is None else seen
    if isinstance(value, (dict, list, tuple)):
        if id(value) in seen:
            return ("ref", seen[id(value)])
        seen[id(value)] = len(seen)
        if isinstance(value, dict):
            return (type(value).__name__, tuple((k, shape(v, seen)) for k, v in value.items()))
        return (type(value).__name__, tuple(shape(v, seen) for v in value))
    return ("atom", type(value).__name__, value)


class Marker:
    def __init__(self, n):
        self.n = n

    def __eq__(self, other):
        return isinstance(other, Marker) and other.n == self.n


class Sub(dict):
    pass


def main() -> int:
    shared = [1, 2]
    atoms = (1, "a", None, 2.5, True)
    value = {"a": shared, "b": {"again": shared, "t": atoms, "tc": (shared, 3)}, "c": [shared, {"x": shared}]}
    for name, v in (("K1 equal, with the same sharing", value), ("K1 the engine's base state", base_state())):
        a, b = state_copy.deepcopy(v), copy.deepcopy(v)
        check(name, a == b and shape(a) == shape(b) and a is not v)
    cyc = [1]
    cyc.append(cyc)
    d = {"self": None}
    d["self"] = d
    for name, v in (("K2 a list cycle", cyc), ("K2 a dict cycle", d)):
        a = state_copy.deepcopy(v)
        check(name, shape(a) == shape(copy.deepcopy(v)) and a is not v)
    check("K3 a tuple of atoms is returned as is", state_copy.deepcopy(atoms) is atoms and copy.deepcopy(atoms) is atoms)
    t = (shared, 3)
    a = state_copy.deepcopy(t)
    check("K4 a tuple holding a container is copied", a is not t and a[0] is not shared and a == t)
    s = Sub(k=[1])
    a = state_copy.deepcopy(s)
    check("K5 a dict subclass is copied by copy.deepcopy", type(a) is Sub and a == s and a["k"] is not s["k"])
    m = Marker(7)
    mixed = {"m": m, "again": m, "l": [m]}
    a = state_copy.deepcopy(mixed)
    check("K6 another type, through copy.deepcopy, keeps its sharing",
          a == mixed and a["m"] is a["again"] is a["l"][0] and a["m"] is not m)

    IR._VALIDATED.clear()
    good = base_state()
    bad = base_state()
    bad["schema_version"] = "nope"
    for name, st in (("V1 a valid state", good), ("V1 an invalid state", bad)):
        first, second, plain = IR.validate_state(st), IR.validate_state(st), IR.validate_state_uncached(st)
        check(name, first == second == plain, f"{first} / {second} / {plain}")
    st = base_state()
    before = IR.validate_state(st)
    st["players"] = {}
    after = IR.validate_state(st)
    check("V2 a state mutated after validation is validated again",
          before == [] and after == IR.validate_state_uncached(st) and after != [], f"{before} -> {after}")
    a1, a2 = base_state(), base_state()
    a1["players"]["p1"]["resources"]["power"] = {1: 1}
    a2["players"]["p1"]["resources"]["power"] = {"1": 1}
    check("V3 the JSON twins encode alike", IR.hash_value(a1) == IR.hash_value(a2))
    r2 = IR.validate_state(a2)
    r1 = IR.validate_state(a1)
    check("V3 but have different content keys", IR._content_key(a1) != IR._content_key(a2))
    check("V3 and each gets its own answer", r1 == IR.validate_state_uncached(a1) and r2 == IR.validate_state_uncached(a2),
          f"{r1} / {r2}")
    got = IR.validate_state(bad)
    got.append("caller's own")
    check("V4 the caller's list is its own", IR.validate_state(bad) == IR.validate_state_uncached(bad))
    odd = base_state()
    odd["objects"]["u1"]["note"] = lambda: None
    check("V5 an unpicklable state is validated uncached",
          IR._content_key(odd) is None and IR.validate_state(odd) == IR.validate_state_uncached(odd))
    print(f"check_engine_speedups: {'FAILED ' + ', '.join(FAILS) if FAILS else 'all passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
