# Engine capability manifest

`manifest.json` is **generated**, not written. It is what
`skill/scripts/capability_manifest.py build` derives from the engine's own
declarations — `effect_ir.SUPPORTED_OPS` and `OP_RULES`, `rules_core.RULES`,
and `engine_check.KIND_CONFIG` — plus a hash of the engine source files.

It answers two questions ADR-0002 says every executable artifact must answer
and `engine-check.v1` previously could not:

| Field | Question | Same across builds? |
| --- | --- | --- |
| `capability_set_id` | Which operations, procedures, clauses and exclusions does this engine support? | Yes, if the capabilities are identical |
| `implementation.value` | Which exact source produced it? | No — any engine edit changes it |

An `engine-check.v1` may carry both under an optional `capability` block. Old
checks without it remain valid; the field is optional precisely so that adding
it is not a new schema major.

`skill/scripts/check_capability_manifest.py` fails CI when this file no longer
matches the engine. Re-run the build and commit the diff; do not edit it by
hand. It claims no complete game and no complete legality, and cannot — those
two fields are constants in the schema.
