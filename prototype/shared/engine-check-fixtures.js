// GENERATED FILE -- do not edit by hand.
// Produced by skill/scripts/build_engine_check_fixtures.py from the real
// engines. Read-only demo data for prototype/shared/engine-check-view.js; not a
// rules authority. Regenerate and commit after any engine or envelope change.
window.RC_ENGINE_CHECK_FIXTURES = Object.freeze({
  "schema_version": "engine-check-view-fixtures.v1",
  "generated_by": "skill/scripts/build_engine_check_fixtures.py",
  "note": "Read-only demo data produced by the real engines. Not a rules authority; every check carries official_status unofficial and state_effect none.",
  "fixtures": [
    {
      "fixture_id": "supported",
      "note": "Timing kernel accepted the action inside its bounded coverage. Source case RK-001: Turn player may play a default-timing Unit in Neutral Open during Main",
      "check": {
        "schema_version": "engine-check.v1",
        "check_id": "engine-check:01b5a45cf62d01537220b620",
        "check_kind": "timing",
        "outcome": "supported",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-07-16",
          "faq_as_of": "2026-08-14"
        },
        "component": {
          "name": "rules_core",
          "version": "riftbound-rules-core-state.v1"
        },
        "coverage": {
          "id": "timing_permission_v1",
          "complete_game": false,
          "complete_legality": false,
          "supported_scope": [
            "four_state_timing",
            "priority_focus",
            "hot_fepr",
            "combat_showdown_close"
          ],
          "unsupported_scope": [
            "arbitrary_card_effects",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:bd1727a8ecd98b4480ac6d24bc112bebea10696ca0a406cf4b36fa4e7278acee"
        },
        "result_hash": "sha256:e2700998cabe97bca0029e0dd24c610eaecaa95e3e117818f429fa7a99ecce94",
        "reason": {
          "code": "ok",
          "message": "By default, the Turn Player with Priority may play cards or activate abilities during the Main Phase in Neutral Open."
        },
        "rule_locators": [
          "Core 310.1.a",
          "Core 312.2.a",
          "Core 316"
        ],
        "trace_summary": {
          "event_count": 0,
          "outcomes": [],
          "raw_result_included": false
        },
        "assumptions": [
          "Fixture state is treated as already confirmed."
        ],
        "missing_information": [],
        "state_label": "neutral_open"
      }
    },
    {
      "fixture_id": "illegal",
      "note": "A supported timing rule rejects the attempted action. This is a bounded rejection, not a card-legality ruling. Source case RK-002: Off-turn player cannot act without Priority in Neutral Open",
      "check": {
        "schema_version": "engine-check.v1",
        "check_id": "engine-check:3cb85af560084583d28eaaea",
        "check_kind": "timing",
        "outcome": "illegal",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-07-16",
          "faq_as_of": "2026-08-14"
        },
        "component": {
          "name": "rules_core",
          "version": "riftbound-rules-core-state.v1"
        },
        "coverage": {
          "id": "timing_permission_v1",
          "complete_game": false,
          "complete_legality": false,
          "supported_scope": [
            "four_state_timing",
            "priority_focus",
            "hot_fepr",
            "combat_showdown_close"
          ],
          "unsupported_scope": [
            "arbitrary_card_effects",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:bd1727a8ecd98b4480ac6d24bc112bebea10696ca0a406cf4b36fa4e7278acee"
        },
        "result_hash": "sha256:3018185ea7d062bdd79a9ddc98a9661018ee2c127e9d8823b4481c2c8513505f",
        "reason": {
          "code": "priority_required",
          "message": "The proposed actor does not currently have Priority."
        },
        "rule_locators": [
          "Core 312"
        ],
        "trace_summary": {
          "event_count": 0,
          "outcomes": [],
          "raw_result_included": false
        },
        "assumptions": [
          "Fixture state is treated as already confirmed."
        ],
        "missing_information": [],
        "state_label": "neutral_open"
      }
    },
    {
      "fixture_id": "unsupported",
      "note": "The effect IR has no model for this operation and fails closed rather than guessing one.",
      "check": {
        "schema_version": "engine-check.v1",
        "check_id": "engine-check:cdfcf554535f429e03751921",
        "check_kind": "effect",
        "outcome": "unsupported",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-07-16",
          "faq_as_of": "2026-08-14"
        },
        "component": {
          "name": "effect_ir",
          "version": "riftbound-effect-program.v1"
        },
        "coverage": {
          "id": "effect_program_v1",
          "complete_game": false,
          "complete_legality": false,
          "supported_scope": [
            "typed_atomic_effects",
            "bounded_replacement",
            "bounded_cleanup",
            "typed_selectors",
            "object_identity",
            "engine_decisions",
            "battlefield_targets",
            "criteria_expansion",
            "bonus_damage",
            "instruction_conditions",
            "move_triggers",
            "private_discard",
            "granted_replacements",
            "combat_relative_might",
            "keyword_modifiers",
            "active_combat_criteria",
            "mutual_current_might_damage"
          ],
          "unsupported_scope": [
            "arbitrary_card_text",
            "combat",
            "scoring",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:2d7823e643e488eeec490355b85f6622c9d5bff549a445818d820d8c942041bf"
        },
        "result_hash": "sha256:2f44621caa53d66637536e81fbcb0df4c144e0bd4ca3dea8253df08ad0584abf",
        "reason": {
          "code": "unsupported effect op 'counter'",
          "message": "unsupported effect op 'counter'"
        },
        "rule_locators": [],
        "trace_summary": {
          "event_count": 0,
          "outcomes": [],
          "raw_result_included": false
        },
        "assumptions": [],
        "missing_information": [
          "Typed program for the Counter operation."
        ]
      }
    },
    {
      "fixture_id": "decision_required",
      "note": "A controller must order simultaneous replacement events before cleanup can continue. The viewer presents the options; it never picks one.",
      "check": {
        "schema_version": "engine-check.v1",
        "check_id": "engine-check:4d1caea705f348228eeaa3c2",
        "check_kind": "cleanup",
        "outcome": "decision_required",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-07-16",
          "faq_as_of": "2026-08-14"
        },
        "component": {
          "name": "lethal_cleanup",
          "version": "riftbound-lethal-cleanup-result.v1"
        },
        "coverage": {
          "id": "lethal_cleanup_v1",
          "complete_game": false,
          "complete_legality": false,
          "supported_scope": [
            "lethal_damage",
            "self_death_triggers",
            "bounded_simultaneous_prevention"
          ],
          "unsupported_scope": [
            "full_cleanup",
            "multi_descriptor_replacement",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:d96f3ba632243e6a046f244e7dced62c0c16ed71b13876e5f3ca9e13043880cf"
        },
        "result_hash": "sha256:4e0fc1a5febca8c7e34ee37391e75ce462489075d25c0e31f7ff561c4932ba25",
        "reason": {
          "code": "replacement controller must order every qualifying simultaneous event",
          "message": "replacement controller must order every qualifying simultaneous event"
        },
        "rule_locators": [],
        "trace_summary": {
          "event_count": 0,
          "outcomes": [],
          "raw_result_included": false
        },
        "assumptions": [],
        "missing_information": [
          "Controller ordering for the simultaneous replacement batch."
        ],
        "decision_required": {
          "kind": "replacement_order",
          "controller": "p2",
          "replacement_ids": [
            "guard-all"
          ],
          "event_ids": [
            "u2",
            "u3"
          ],
          "decision_ids": [],
          "decision_schema": "riftbound-cleanup-decisions.v1"
        }
      }
    },
    {
      "fixture_id": "invalid_input",
      "note": "State or program is malformed. Repair the input; do not read this as a game ruling.",
      "check": {
        "schema_version": "engine-check.v1",
        "check_id": "engine-check:1379a5f1d0e232e9f7f0ffa2",
        "check_kind": "effect",
        "outcome": "invalid_input",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-07-16",
          "faq_as_of": "2026-08-14"
        },
        "component": {
          "name": "effect_ir",
          "version": "riftbound-effect-program.v1"
        },
        "coverage": {
          "id": "effect_program_v1",
          "complete_game": false,
          "complete_legality": false,
          "supported_scope": [
            "typed_atomic_effects",
            "bounded_replacement",
            "bounded_cleanup",
            "typed_selectors",
            "object_identity",
            "engine_decisions",
            "battlefield_targets",
            "criteria_expansion",
            "bonus_damage",
            "instruction_conditions",
            "move_triggers",
            "private_discard",
            "granted_replacements",
            "combat_relative_might",
            "keyword_modifiers",
            "active_combat_criteria",
            "mutual_current_might_damage"
          ],
          "unsupported_scope": [
            "arbitrary_card_text",
            "combat",
            "scoring",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:9bbaa4efa37d691ee7332ba37f0fdf369437e555067e70e1277b740189c8ae54"
        },
        "result_hash": "sha256:68110627fff2fb165a4d73b347d71e245b776001ebd74717a4d72d049d0519e7",
        "reason": {
          "code": "ok",
          "message": "schema_version must be riftbound-effect-state.v1; ruleset must match the R2 v1 baseline; players must be an object with at least two entries; objects must be an object; battlefields must be an object; replacement_effects must be an array"
        },
        "rule_locators": [],
        "trace_summary": {
          "event_count": 0,
          "outcomes": [],
          "raw_result_included": false
        },
        "assumptions": [],
        "missing_information": [
          "A well-formed riftbound-effect-state.v1 document."
        ]
      }
    }
  ]
});
