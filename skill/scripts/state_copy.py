#!/usr/bin/env python3
"""copy.deepcopy for the engine's states, without the generic dispatch (2026-11-03).

A corpus game spent half its time in copy.deepcopy (game 100, 675 steps: 545 of 1,084 s under the profiler), nearly all
of it the dispatch, the reduce protocol and the keep-alive list that deepcopy runs for every value. The engine's states
are trees of dict, list, tuple and atoms, but not always trees: 2,005 of 117,374 copies in the first 250 steps held a
container reachable twice. So this copy keeps deepcopy's semantics exactly for those types - one copy per original
container (the memo), a tuple whose items copy to themselves is returned as is, atoms are returned as they are - and
hands any other type, a dict or list subclass included, to copy.deepcopy with the same memo. No keep-alive list: every
original this module memoizes is reachable from the value being copied for the whole copy, so no id can be reused;
copy.deepcopy keeps its own temporaries alive in the same memo.

    deepcopy(value, memo=None) -> the copy
"""
from __future__ import annotations

import copy as _copy
from typing import Any

_ATOMS = frozenset({str, int, float, bool, type(None), bytes, complex})


def deepcopy(value: Any, memo: dict[int, Any] | None = None) -> Any:
    cls = type(value)
    if cls in _ATOMS:
        return value
    if memo is None:
        memo = {}
    found = memo.get(id(value), memo)
    if found is not memo:
        return found
    if cls is dict:
        out: Any = {}
        memo[id(value)] = out
        for key, item in value.items():
            out[deepcopy(key, memo)] = deepcopy(item, memo)
        return out
    if cls is list:
        out = []
        memo[id(value)] = out
        append = out.append
        for item in value:
            append(deepcopy(item, memo))
        return out
    if cls is tuple:
        items = [deepcopy(item, memo) for item in value]
        # a tuple met again while its items were copied (a cycle through a list or dict) was copied there
        found = memo.get(id(value), memo)
        if found is not memo:
            return found
        out = value if all(a is b for a, b in zip(value, items)) else tuple(items)
        if out is not value:
            memo[id(value)] = out
        return out
    return _copy.deepcopy(value, memo)

