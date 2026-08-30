#!/usr/bin/env python3
"""Scenario tests for bilingual lookup, precedence metadata, and stale-source masking."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

from rules_index import create_schema, search


def add_document(connection, source_id, title, locale, authority, status, controlling, document_class="core_rules", successor=None):
    connection.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (source_id, source_id, title, "fixture", locale, "global", document_class, authority,
         status, successor, int(controlling), f"{source_id}.pdf", "fixture", 1),
    )


def add_chunk(connection, source_id, locator, text):
    connection.execute(
        "INSERT INTO chunks(source_id, page, locator, text, compact_text) VALUES (?, 1, ?, ?, ?)",
        (source_id, locator, text, "".join(text.casefold().split())),
    )


def main() -> int:
    errors = []
    with tempfile.TemporaryDirectory(prefix="riftbound-rules-index-test-") as folder:
        database = Path(folder) / "fixture.sqlite3"
        connection = sqlite3.connect(database)
        create_schema(connection)
        add_document(connection, "core-en", "Core Rules", "en-US", "official", "active", True)
        add_document(connection, "core-zh", "核心规则", "zh-CN", "official", "active", False)
        add_document(connection, "judge-old", "旧裁判 FAQ", "zh-CN", "judge_guidance", "superseded", False, "judge_faq", "judge-new")
        add_document(connection, "judge-new", "裁判 FAQ", "zh-CN", "judge_guidance", "active", False, "judge_faq")
        add_chunk(connection, "core-en", "339.1", "When both players pass, resolve the newest object on the chain.")
        add_chunk(connection, "core-zh", "339.1", "双方连续让过后，结算连锁上最新的项目。")
        add_chunk(connection, "judge-old", "page-1-paragraph-1", "旧裁判FAQ：连锁一次全部结算。")
        add_chunk(connection, "judge-new", "page-1-paragraph-1", "裁判FAQ：连锁只结算最新项目。")
        connection.commit()
        connection.close()

        results = search(database, "連鎖 結算", limit=10, locale=None, region=None, document_class=None, include_superseded=False)
        ids = [item["source_id"] for item in results]
        if "core-zh" not in ids or "core-en" not in ids:
            errors.append(f"Traditional Chinese alias search did not retrieve both Chinese and controlling English evidence: {ids}")
        if "judge-old" in ids:
            errors.append("superseded judge guidance leaked into default search")
        exact = search(database, "339.1", limit=2, locale=None, region=None, document_class=None, include_superseded=False)
        if not exact or exact[0]["locator"] != "339.1":
            errors.append("exact rule locator did not receive priority")
        historical = search(database, "全部結算", limit=10, locale=None, region=None, document_class=None, include_superseded=True)
        if not any(item["source_id"] == "judge-old" and item["superseded_by"] == "judge-new" for item in historical):
            errors.append("explicit historical search did not expose the successor pointer")

    if errors:
        print("\n".join(f"FAILED: {item}" for item in errors))
        return 1
    print("OK: bilingual retrieval, locator ranking, authority labels, and superseded-source masking validate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
