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
        "check_id": "engine-check:aa433b4fc25aa4c7638914cb",
        "check_kind": "timing",
        "outcome": "supported",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-10-09",
          "faq_as_of": "2026-08-14"
        },
        "rule_numbering": {
          "core": "2026-07-16",
          "applies_to": "rule_locators"
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
          "state": "sha256:456ccf898b6a7c131ff667410300c70fe68767e56cb30a1142a2215d71d040bb"
        },
        "result_hash": "sha256:8a2467e50e675eb3d0c979ddd260ddf05547c5a09e6a5f5aaf1ddd30bd758dd5",
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
        "check_id": "engine-check:6e8a00538f2b3fb456f3beec",
        "check_kind": "timing",
        "outcome": "illegal",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-10-09",
          "faq_as_of": "2026-08-14"
        },
        "rule_numbering": {
          "core": "2026-07-16",
          "applies_to": "rule_locators"
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
          "state": "sha256:456ccf898b6a7c131ff667410300c70fe68767e56cb30a1142a2215d71d040bb"
        },
        "result_hash": "sha256:59771e18747c29a2023f06849656eb0e93afde0a55488bad558b77534c608168",
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
        "check_id": "engine-check:a8e38e132a4ff5995a4fa3da",
        "check_kind": "effect",
        "outcome": "unsupported",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-10-09",
          "faq_as_of": "2026-08-14"
        },
        "rule_numbering": {
          "core": "2026-07-16",
          "applies_to": "rule_locators"
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
            "leave_board_triggers",
            "battlefield_restrictions",
            "copied_abilities",
            "private_discard",
            "granted_replacements",
            "combat_relative_might",
            "keyword_modifiers",
            "active_combat_criteria",
            "mutual_current_might_damage",
            "burn_out_draw",
            "randomization_receipt",
            "choice_grammar",
            "modal_abilities",
            "card_ordering",
            "look_reveal_put_back",
            "predict",
            "multi_recycle",
            "restricted_resource_grant",
            "repeat_execution",
            "banish",
            "counter",
            "burn",
            "attachments",
            "top_most_might_bonus",
            "derived_detach_destination",
            "legend_objects",
            "legend_zone_passives",
            "continuous_effects",
            "layer_engine",
            "canonical_migration",
            "typed_conditions",
            "keyword_catalog",
            "empower_state",
            "buff_counters",
            "xp",
            "effect_text_append",
            "copy_modelled_traits"
          ],
          "unsupported_scope": [
            "arbitrary_card_text",
            "combat",
            "scoring",
            "burn_out_non_draw",
            "burn_out_in_replacement",
            "distinct_per_turn_choice",
            "each_player_choice",
            "multi_opponent_choice",
            "revealed_knowledge_persistence",
            "cannot_be_countered",
            "burn_triggers",
            "nested_attachments",
            "gear_recall_cleanup",
            "copy_unmodelled_traits",
            "champion_legend_movement",
            "token_not_in_catalogue",
            "layer_dependency_unresolved",
            "condition_needs_hidden_information",
            "keyword_not_implemented",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:1528cbc1ccf7a310f7595fd81769d02844fa59c5a60ecc4ed13eb132f8d3deba"
        },
        "result_hash": "sha256:e95978e93b47b7d3121a062d9dc617c27557a8165f52fe1f15bfc5651a3edc4f",
        "reason": {
          "code": "unsupported effect op 'double'",
          "message": "unsupported effect op 'double'"
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
        "check_id": "engine-check:2af31653f3e7d7427afe401d",
        "check_kind": "cleanup",
        "outcome": "decision_required",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-10-09",
          "faq_as_of": "2026-08-14"
        },
        "rule_numbering": {
          "core": "2026-07-16",
          "applies_to": "rule_locators"
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
          "state": "sha256:7823f721d5727e19636d8c962972ce7b8527debf76840452705ffccde05b99ab"
        },
        "result_hash": "sha256:bcbd5e0080e35dbf50fc0d35ee8c436a788974c7bdd7699f43b14faf2340a05f",
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
        "check_id": "engine-check:613b5faca6182e0b885f8b92",
        "check_kind": "effect",
        "outcome": "invalid_input",
        "authority": {
          "official_status": "unofficial",
          "role": "consistency_check",
          "state_effect": "none"
        },
        "ruleset": {
          "core": "2026-10-09",
          "faq_as_of": "2026-08-14"
        },
        "rule_numbering": {
          "core": "2026-07-16",
          "applies_to": "rule_locators"
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
            "leave_board_triggers",
            "battlefield_restrictions",
            "copied_abilities",
            "private_discard",
            "granted_replacements",
            "combat_relative_might",
            "keyword_modifiers",
            "active_combat_criteria",
            "mutual_current_might_damage",
            "burn_out_draw",
            "randomization_receipt",
            "choice_grammar",
            "modal_abilities",
            "card_ordering",
            "look_reveal_put_back",
            "predict",
            "multi_recycle",
            "restricted_resource_grant",
            "repeat_execution",
            "banish",
            "counter",
            "burn",
            "attachments",
            "top_most_might_bonus",
            "derived_detach_destination",
            "legend_objects",
            "legend_zone_passives",
            "continuous_effects",
            "layer_engine",
            "canonical_migration",
            "typed_conditions",
            "keyword_catalog",
            "empower_state",
            "buff_counters",
            "xp",
            "effect_text_append",
            "copy_modelled_traits"
          ],
          "unsupported_scope": [
            "arbitrary_card_text",
            "combat",
            "scoring",
            "burn_out_non_draw",
            "burn_out_in_replacement",
            "distinct_per_turn_choice",
            "each_player_choice",
            "multi_opponent_choice",
            "revealed_knowledge_persistence",
            "cannot_be_countered",
            "burn_triggers",
            "nested_attachments",
            "gear_recall_cleanup",
            "copy_unmodelled_traits",
            "champion_legend_movement",
            "token_not_in_catalogue",
            "layer_dependency_unresolved",
            "condition_needs_hidden_information",
            "keyword_not_implemented",
            "complete_game",
            "complete_legality"
          ]
        },
        "input_hashes": {
          "state": "sha256:9bbaa4efa37d691ee7332ba37f0fdf369437e555067e70e1277b740189c8ae54"
        },
        "result_hash": "sha256:79f8edf5c581bbaedb3b728fd74a868b380b502971367aaf699045a213c91764",
        "reason": {
          "code": "ok",
          "message": "schema_version must be riftbound-effect-state.v1; ruleset must be {'core': '2026-10-09', 'faq_as_of': '2026-08-14'}: the Core this engine executes; a state labelled with another Core is refused; players must be an object with at least two entries; objects must be an object; battlefields must be an object; replacement_effects must be an array"
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
