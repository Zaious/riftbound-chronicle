(() => {
  "use strict";

  // Shared read-only renderer for `engine-check.v1`.
  //
  // Read `skill/references/shared/engine-check.md` before changing anything here:
  // this component presents a bounded consistency check, never an authority. It
  // has three hard rules, and each one has a test in check_engine_check_view.py:
  //
  //   1. It never chooses. A `decision_required` check is rendered as neutral
  //      options with no default, no ordering hint, and no control that could be
  //      mistaken for making the choice.
  //   2. It never widens a claim. Coverage is printed as the check states it,
  //      including complete_game/complete_legality being false, and the
  //      authority triple is always visible.
  //   3. It never mutates. No state is written, nothing is posted, and the
  //      consumer keeps its own authority contract (P2-A still needs a human
  //      confirmation and a fresh snapshot afterwards).
  //
  // The renderer returns a DOM node rather than an HTML string so callers cannot
  // accidentally interpolate untrusted engine text into innerHTML.

  const OUTCOME_COPY = {
    supported: {
      en: "Supported",
      zh: "已支援",
      meaning_en: "The bounded component completed this check. Cite it only inside the coverage below.",
      meaning_zh: "有界元件完成了這項檢查。引用時不得超出下方的涵蓋範圍。",
    },
    illegal: {
      en: "Illegal",
      zh: "不合法",
      meaning_en: "A supported timing or procedure rejects this action. This is a bounded rejection, not a ruling about the card.",
      meaning_zh: "某條已支援的時機或程序否決了這個動作。這是有界的否決，不是對這張卡的裁定。",
    },
    unsupported: {
      en: "Unsupported",
      zh: "未支援",
      meaning_en: "The component lacks the semantics for this. Fall back to sourced prose and lower engine confidence.",
      meaning_zh: "元件缺少這部分的語義。請改用有出處的文字說明，並降低引擎信心。",
    },
    decision_required: {
      en: "Decision required",
      zh: "需要決定",
      meaning_en: "A controller or human choice is needed before this can be retried. The options are shown; nothing is chosen here.",
      meaning_zh: "需要控制者或玩家先做出選擇才能重試。以下只列出選項，這裡不會替你選。",
    },
    invalid_input: {
      en: "Invalid input",
      zh: "輸入無效",
      meaning_en: "The state, program, or decision artifact is malformed. Repair the input; this is not a game ruling.",
      meaning_zh: "狀態、程式或決定物件的格式有誤。請修正輸入；這不是遊戲裁定。",
    },
  };

  const pick = (zhValue, enValue) =>
    globalThis.RC_I18N ? RC_I18N.pick(zhValue, enValue) : enValue;

  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };

  const listOf = (values, className) => {
    const list = el("ul", className);
    for (const value of values) list.append(el("li", null, value));
    return list;
  };

  function section(titleZh, titleEn, body) {
    const wrap = el("section", "ecv-section");
    wrap.append(el("h4", null, pick(titleZh, titleEn)));
    wrap.append(body);
    return wrap;
  }

  function coverageBlock(coverage) {
    const wrap = el("div", "ecv-coverage");
    wrap.append(el("code", "ecv-coverage-id", coverage?.id ?? "unknown"));

    // Stated as claims the check itself makes, never softened by the viewer.
    const limits = el("ul", "ecv-limits");
    limits.append(el("li", null, pick(
      `完整遊戲涵蓋：${coverage?.complete_game ? "是" : "否"}`,
      `Complete game: ${coverage?.complete_game ? "yes" : "no"}`)));
    limits.append(el("li", null, pick(
      `完整合法性：${coverage?.complete_legality ? "是" : "否"}`,
      `Complete legality: ${coverage?.complete_legality ? "yes" : "no"}`)));
    wrap.append(limits);

    for (const [key, zh, en] of [
      ["supported_scope", "已支援範圍", "Supported scope"],
      ["unsupported_scope", "未支援範圍", "Unsupported scope"],
    ]) {
      const values = Array.isArray(coverage?.[key]) ? coverage[key] : [];
      if (!values.length) continue;
      const group = el("div", `ecv-scope ecv-scope-${key.split("_")[0]}`);
      group.append(el("span", "ecv-scope-label", pick(zh, en)));
      group.append(listOf(values, "ecv-scope-list"));
      wrap.append(group);
    }
    return wrap;
  }

  function decisionBlock(decision) {
    // Neutral by construction: a definition list of what must be decided and by
    // whom, with no button, no preselection, and no recommended option.
    const wrap = el("div", "ecv-decision");
    wrap.append(el("p", "ecv-decision-lead", pick(
      "以下是引擎回報需要有人決定的內容。這個檢視器不會替任何人做決定，也不會排序建議。",
      "The engine reports that someone must decide the following. This viewer does not decide, and does not rank the options.")));

    const dl = el("dl", "ecv-decision-fields");
    const rows = [
      [pick("決定種類", "Decision kind"), decision?.kind],
      [pick("由誰決定", "Decided by"), decision?.controller],
      [pick("決定結構", "Decision schema"), decision?.decision_schema],
    ];
    for (const [term, value] of rows) {
      if (!value) continue;
      dl.append(el("dt", null, term));
      dl.append(el("dd", null, value));
    }
    wrap.append(dl);

    for (const [key, zh, en] of [
      ["replacement_ids", "相關取代效果", "Replacement effects involved"],
      ["event_ids", "待排序事件", "Events awaiting an order"],
      ["options", "可選項", "Options"],
    ]) {
      const values = Array.isArray(decision?.[key]) ? decision[key] : [];
      if (!values.length) continue;
      wrap.append(section(zh, en, listOf(values.map(v => (typeof v === "string" ? v : JSON.stringify(v))), "ecv-decision-list")));
    }
    return wrap;
  }

  /**
   * Render one engine-check.v1 object.
   * @param {object} check parsed engine-check.v1
   * @returns {HTMLElement} detached node; the caller decides where it goes
   */
  function render(check) {
    const root = el("article", "ecv");

    if (!check || typeof check !== "object" || check.schema_version !== "engine-check.v1") {
      root.classList.add("ecv-outcome-invalid_input");
      root.append(el("p", "ecv-error", pick(
        "這不是一份 engine-check.v1 檢查結果，無法呈現。",
        "This is not an engine-check.v1 result and cannot be rendered.")));
      return root;
    }

    const outcome = String(check.outcome || "");
    const copy = OUTCOME_COPY[outcome];
    root.classList.add(`ecv-outcome-${outcome || "unknown"}`);
    root.dataset.outcome = outcome;
    root.dataset.checkKind = String(check.check_kind || "");

    const header = el("header", "ecv-head");
    header.append(el("span", "ecv-badge", copy ? pick(copy.zh, copy.en) : outcome));
    header.append(el("span", "ecv-kind", String(check.check_kind || "")));
    header.append(el("span", "ecv-component",
      `${check.component?.name ?? "engine"} ${check.component?.version ?? ""}`.trim()));
    root.append(header);

    if (copy) root.append(el("p", "ecv-meaning", pick(copy.meaning_zh, copy.meaning_en)));

    // The authority triple is not optional chrome; it is the reason a consumer
    // may show this at all.
    const authority = el("p", "ecv-authority");
    authority.append(el("span", "ecv-tag", `official_status: ${check.authority?.official_status ?? "unofficial"}`));
    authority.append(el("span", "ecv-tag", `role: ${check.authority?.role ?? "consistency_check"}`));
    authority.append(el("span", "ecv-tag", `state_effect: ${check.authority?.state_effect ?? "none"}`));
    root.append(authority);

    if (check.reason?.message) {
      root.append(section("引擎說明", "Engine reason", el("p", "ecv-reason", check.reason.message)));
    }

    root.append(section("涵蓋範圍", "Coverage", coverageBlock(check.coverage)));

    if (outcome === "decision_required" && check.decision_required) {
      root.append(section("需要的決定", "Required decision", decisionBlock(check.decision_required)));
    }

    const locators = Array.isArray(check.rule_locators) ? check.rule_locators : [];
    if (locators.length) {
      root.append(section("官方條號", "Official rule locators", listOf(locators, "ecv-locators")));
    }

    const assumptions = Array.isArray(check.assumptions) ? check.assumptions : [];
    if (assumptions.length) {
      root.append(section("假設", "Assumptions", listOf(assumptions, "ecv-assumptions")));
    }

    const missing = Array.isArray(check.missing_information) ? check.missing_information : [];
    if (missing.length) {
      root.append(section("缺少的資訊", "Missing information", listOf(missing, "ecv-missing")));
    }

    const trace = check.trace_summary || {};
    const footer = el("footer", "ecv-foot");
    footer.append(el("span", null, pick(`事件數 ${trace.event_count ?? 0}`, `${trace.event_count ?? 0} trace events`)));
    if (trace.stage) footer.append(el("span", null, `stage: ${trace.stage}`));
    if (trace.procedure) footer.append(el("span", null, `procedure: ${trace.procedure}`));
    footer.append(el("span", "ecv-hash", `result ${String(check.result_hash || "").slice(0, 12)}`));
    root.append(footer);

    return root;
  }

  /** Replace a container's contents with one rendered check. */
  function mount(container, check) {
    if (!container) return null;
    container.replaceChildren(render(check));
    return container.firstElementChild;
  }

  window.RC_ENGINE_CHECK_VIEW = Object.freeze({
    render,
    mount,
    outcomes: Object.freeze(Object.keys(OUTCOME_COPY)),
  });
})();
