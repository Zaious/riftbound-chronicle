// GENERATED FILE -- do not edit by hand.
// Produced by skill/scripts/build_behavior_coverage_fixtures.py from the real
// deck-behavior-coverage.v1 projection, using demonstration manifests that are
// NOT an R3 card behavior pack. Read-only display data for the Deck Coach
// prototype. Regenerate and commit after any projection change.
window.RC_BEHAVIOR_COVERAGE_FIXTURES = Object.freeze({
  "schema_version": "behavior-coverage-view-fixtures.v1",
  "generated_by": "skill/scripts/build_behavior_coverage_fixtures.py",
  "note": "Read-only demonstration data from the real deck-behavior-coverage.v1 projection. The manifests behind it are demonstrations, not an R3 card behavior pack, and this is not evidence about any deck's strategy.",
  "fixtures": [
    {
      "fixture_id": "unavailable",
      "note": "The ordinary case today: no R3 pack is bundled, so no card in this deck has an executable behavior claim.",
      "deck_id": "rengar-ottawa-2026-08-08",
      "coverage": {
        "schema_version": "deck-behavior-coverage.v1",
        "scope": "main_deck_current_text_clauses",
        "status": "unavailable",
        "manifest_id": null,
        "cards": [],
        "copy_weighted": {
          "total": 40,
          "full": 0,
          "partial": 0,
          "unsupported": 0,
          "stale": 0,
          "uncovered": 40
        },
        "strategy_evidence": "not_established_by_engine_coverage",
        "warnings": [
          "No R3 card behavior manifest was supplied."
        ]
      }
    },
    {
      "fixture_id": "available",
      "note": "A demonstration manifest covers three cards of this list. The remaining copies stay uncovered, which is the number that matters.",
      "deck_id": "rengar-ottawa-2026-08-08",
      "coverage": {
        "schema_version": "deck-behavior-coverage.v1",
        "scope": "main_deck_current_text_clauses",
        "status": "available",
        "manifest_id": "demonstration-manifest",
        "cards": [
          {
            "canonical_name": "Inferna",
            "count": 3,
            "status": "full",
            "covered_clause_ids": [
              "clause-a"
            ],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Irresistible Faefolk",
            "count": 3,
            "status": "partial",
            "covered_clause_ids": [
              "clause-b"
            ],
            "unsupported_mechanics": [
              "conditional_choice"
            ]
          },
          {
            "canonical_name": "Pit Rookie",
            "count": 3,
            "status": "unsupported",
            "covered_clause_ids": [
              "clause-c"
            ],
            "unsupported_mechanics": [
              "attachment"
            ]
          },
          {
            "canonical_name": "Grim Apothecary",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Pyke - Dockside Butcher",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "First Mate",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Kinkou Initiate",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Pakaa Cub",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Nidalee - Cat Form",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Kai'Sa, Survivor",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Noxus Hopeful",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Darius - Trifarian",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Rengar - Trophy Hunter",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Ferrous Forerunner",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Sabotage",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Punch First",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Thrill of the Hunt",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Rampage",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          }
        ],
        "copy_weighted": {
          "total": 40,
          "full": 3,
          "partial": 3,
          "unsupported": 3,
          "stale": 0,
          "uncovered": 31
        },
        "strategy_evidence": "not_established_by_engine_coverage",
        "warnings": [
          "Some resolved Main Deck cards have no behavior manifest entry."
        ]
      }
    },
    {
      "fixture_id": "stale_manifest",
      "note": "The manifest exists but is not active, so nothing in it may be consumed as a current executable claim.",
      "deck_id": "rengar-ottawa-2026-08-08",
      "coverage": {
        "schema_version": "deck-behavior-coverage.v1",
        "scope": "main_deck_current_text_clauses",
        "status": "stale",
        "manifest_id": "demonstration-manifest",
        "cards": [],
        "copy_weighted": {
          "total": 40,
          "full": 0,
          "partial": 0,
          "unsupported": 0,
          "stale": 0,
          "uncovered": 40
        },
        "strategy_evidence": "not_established_by_engine_coverage",
        "warnings": [
          "Behavior manifest status is 'draft', not active."
        ]
      }
    },
    {
      "fixture_id": "incompatible",
      "note": "The manifest was built for a different environment. Coverage from it says nothing about this deck here.",
      "deck_id": "rengar-ottawa-2026-08-08",
      "coverage": {
        "schema_version": "deck-behavior-coverage.v1",
        "scope": "main_deck_current_text_clauses",
        "status": "incompatible",
        "manifest_id": "demonstration-manifest",
        "cards": [],
        "copy_weighted": {
          "total": 40,
          "full": 0,
          "partial": 0,
          "unsupported": 0,
          "stale": 0,
          "uncovered": 40
        },
        "strategy_evidence": "not_established_by_engine_coverage",
        "warnings": [
          "Behavior manifest does not match this ruleset/environment/format/region."
        ]
      }
    },
    {
      "fixture_id": "available_stale_entry",
      "note": "The manifest is active, but one card's text has changed since it was verified, so those copies count as stale rather than covered.",
      "deck_id": "rengar-ottawa-2026-08-08",
      "coverage": {
        "schema_version": "deck-behavior-coverage.v1",
        "scope": "main_deck_current_text_clauses",
        "status": "available",
        "manifest_id": "demonstration-manifest",
        "cards": [
          {
            "canonical_name": "Inferna",
            "count": 3,
            "status": "stale",
            "covered_clause_ids": [],
            "unsupported_mechanics": [
              "current_card_text_changed"
            ]
          },
          {
            "canonical_name": "Irresistible Faefolk",
            "count": 3,
            "status": "partial",
            "covered_clause_ids": [
              "clause-b"
            ],
            "unsupported_mechanics": [
              "conditional_choice"
            ]
          },
          {
            "canonical_name": "Pit Rookie",
            "count": 3,
            "status": "unsupported",
            "covered_clause_ids": [
              "clause-c"
            ],
            "unsupported_mechanics": [
              "attachment"
            ]
          },
          {
            "canonical_name": "Grim Apothecary",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Pyke - Dockside Butcher",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "First Mate",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Kinkou Initiate",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Pakaa Cub",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Nidalee - Cat Form",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Kai'Sa, Survivor",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Noxus Hopeful",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Darius - Trifarian",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Rengar - Trophy Hunter",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Ferrous Forerunner",
            "count": 1,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Sabotage",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Punch First",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Thrill of the Hunt",
            "count": 3,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          },
          {
            "canonical_name": "Rampage",
            "count": 2,
            "status": "uncovered",
            "covered_clause_ids": [],
            "unsupported_mechanics": []
          }
        ],
        "copy_weighted": {
          "total": 40,
          "full": 0,
          "partial": 3,
          "unsupported": 3,
          "stale": 3,
          "uncovered": 31
        },
        "strategy_evidence": "not_established_by_engine_coverage",
        "warnings": [
          "Some resolved Main Deck cards have no behavior manifest entry.",
          "Some behavior entries do not match current card text or are stale."
        ]
      }
    }
  ]
});
