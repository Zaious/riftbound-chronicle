(() => {
  "use strict";

  const UI = {
    "zh-Hant": {
      "nav.deck": "牌組教練", "nav.rule": "規則諮詢", "nav.p2a": "二號玩家代理", "nav.ma": "賽後分析",
      "status.unofficial": "非官方", "status.preview": "開發預覽・未啟用",
      "hero.eyebrow": "一條時間線 · 兩種投影",
      "hero.title": "把一局整理成時間線，<br /><em>再分成覆盤與講評。</em>",
      "hero.body": "對局紀錄或引擎重播先整理成帶來源編號的事件序列，依選定視角遮掉看不到的資訊，接上引擎重建；覆盤只用每個決定當下已知的事件，講評不推測動機也不判失誤。兩者必須對同一份確認過的局面一致。",
      "hero.pick": "選一場",
      "tab.commentary": "講評", "tab.review": "覆盤", "tab.timeline": "時間線", "tab.boundary": "資訊邊界",
      perspective: "視角", source: "來源", engine: "引擎", events: "事件", withheld: "看不到而未使用",
      contradictions: "矛盾", decisions: "決策點", turning: "轉折點", synthetic: "合成對局，非真實比賽",
      replayed: (n) => `引擎逐步重播 ${n} 步，每一步局面雜湊都對上紀錄`,
      timing: (n) => `人工紀錄沒有完整局面；${n} 個動作做了引擎時機檢查（engine-check.v1）`,
      level: { event: "事件", sequence: "段落", turning_point: "轉折", match_summary: "全場摘要" },
      label: { confirmed: "確認", inferred: "推斷", unknown: "不明", hindsight_only: "事後才知" },
      cls: { rules_execution_error: "規則執行錯誤", missed_response_window: "錯過回應時機", strategic_misplay: "策略失誤",
        reasonable_alternative: "合理選擇", outcome_bias: "結果論", insufficient_information: "資訊不足",
        unsupported_engine_behavior: "引擎不支援" },
      chose: "實際選擇", alts: "其他合法選擇", rules: "規則面", strategy: "策略面", improve: "可回頭看", hindsight: "事後資訊",
      feedback: "回饋給", none: "無", evidence: "當下可用的事件", noAlt: "紀錄沒有列出其他選擇",
      engineList: "引擎列舉（不宣稱完整）", recordList: "紀錄", addAbilities: (n) => `另有 ${n} 個產生資源的符文動作未列出`,
      abstained: "引擎放棄列舉的動作種類",
      colId: "編號", colSrc: "來源事件", colTurn: "回合", colState: "狀態", colWho: "行動者", colWhat: "發生了什麼",
      colLabel: "可信度", colEngine: "引擎",
      withheldTitle: "此視角看不到、未使用的事件", withheldNone: "沒有：此視角能看到全部事件。",
      contraTitle: "紀錄裡的矛盾", contraNone: "沒有找到矛盾。", assumeTitle: "引擎檢查用到的假設", assumeNone: "沒有。",
      ledgerTitle: "非觀察事實（推斷、不明、事後才知）", ledgerNone: "沒有：每一則都是直接觀察到的。",
      rulesTitle: "邊界規則", lowHidden: (n) => `已隱藏 ${n} 則例行事件（抽牌、符文）`, showAll: "顯示全部", showLess: "只看重點",
      empty: "沒有示範資料。請執行 python skill/scripts/match_analyst_runner.py demo --out prototype/match-analyst/demo-data.js",
    },
    en: {
      "nav.deck": "Deck Coach", "nav.rule": "Rule Consult", "nav.p2a": "Player 2 Agent", "nav.ma": "Match Analyst",
      "status.unofficial": "Unofficial", "status.preview": "Dev preview · not routed",
      "hero.eyebrow": "ONE TIMELINE · TWO PROJECTIONS",
      "hero.title": "Turn a game into one timeline,<br /><em>then review it and narrate it.</em>",
      "hero.body": "A match log or an engine replay becomes an event sequence with source ids, filtered to what the chosen perspective could see and bound to the engine. Review grades each decision only on what was known then; Commentary guesses no motive and calls no play a mistake. Both must agree on the same confirmed state.",
      "hero.pick": "Pick a match",
      "tab.commentary": "Commentary", "tab.review": "Review", "tab.timeline": "Timeline", "tab.boundary": "Information boundary",
      perspective: "Perspective", source: "Source", engine: "Engine", events: "Events", withheld: "Unseen, not used",
      contradictions: "Contradictions", decisions: "Decisions", turning: "Turning points", synthetic: "Synthetic game, not a real match",
      replayed: (n) => `Engine replayed ${n} steps; every state hash matched the record`,
      timing: (n) => `A hand record has no full state; ${n} action(s) got an engine timing check (engine-check.v1)`,
      level: { event: "Event", sequence: "Sequence", turning_point: "Turning point", match_summary: "Match summary" },
      label: { confirmed: "Confirmed", inferred: "Inferred", unknown: "Unknown", hindsight_only: "Hindsight only" },
      cls: { rules_execution_error: "Rules execution error", missed_response_window: "Missed response window", strategic_misplay: "Strategic misplay",
        reasonable_alternative: "Reasonable alternative", outcome_bias: "Outcome bias", insufficient_information: "Insufficient information",
        unsupported_engine_behavior: "Unsupported by engine" },
      chose: "Chosen", alts: "Other legal choices", rules: "Rules", strategy: "Strategy", improve: "Worth revisiting", hindsight: "Hindsight",
      feedback: "Feedback to", none: "none", evidence: "Events available then", noAlt: "The record lists no other choice",
      engineList: "engine enumeration (not claimed complete)", recordList: "record", addAbilities: (n) => `${n} resource-tap rune action(s) not listed`,
      abstained: "Action families the engine abstained on",
      colId: "Id", colSrc: "Source", colTurn: "Turn", colState: "State", colWho: "Actor", colWhat: "What happened",
      colLabel: "Certainty", colEngine: "Engine",
      withheldTitle: "Events this perspective cannot see (not used)", withheldNone: "None: this perspective sees every event.",
      contraTitle: "Contradictions in the record", contraNone: "No contradiction found.", assumeTitle: "Assumptions the engine checks needed", assumeNone: "None.",
      ledgerTitle: "Facts that are not observations (inferred, unknown, hindsight only)", ledgerNone: "None: every fact was observed.",
      rulesTitle: "Boundary rules", lowHidden: (n) => `${n} routine event(s) hidden (draws, runes)`, showAll: "Show all", showLess: "Key events only",
      empty: "No demo data. Run python skill/scripts/match_analyst_runner.py demo --out prototype/match-analyst/demo-data.js",
    },
  };

  const DATA = window.MATCH_ANALYST_DEMO || [];
  const state = { locale: "zh-Hant", match: 0, tab: "commentary", focus: null, all: false };
  const t = (k) => UI[state.locale][k];
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const zhOrEn = (pair) => (pair ? (state.locale === "en" ? pair.en : pair.zh ?? pair["zh-Hant"]) : "");

  function applyStatic() {
    document.documentElement.lang = state.locale;
    document.documentElement.dataset.locale = state.locale;
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
    document.getElementById("language-toggle").textContent = state.locale === "en" ? "中文" : "EN";
  }

  function renderList() {
    const list = document.getElementById("match-list");
    list.innerHTML = DATA.map((m, i) => `<li><button type="button" class="${i === state.match ? "active" : ""}" data-match="${i}">${esc(m.label)}</button></li>`).join("");
  }

  function head(m) {
    const a = m.analysis;
    const rec = a.reconstruction || {};
    const engine = rec.mode === "engine_replay" ? t("replayed")(rec.steps_replayed) : t("timing")((a.engine_checks || []).length);
    const synthetic = a.source.provenance && a.source.provenance.is_real_match === false ? `<span class="chip warn">${t("synthetic")}</span>` : "";
    const stat = (k, v) => `<div class="stat"><b>${v}</b><span>${t(k)}</span></div>`;
    return `<div class="head-row"><div><h2>${esc(m.label)}</h2>
      <p class="meta">${t("perspective")}：<code>${esc(a.perspective)}</code> · ${t("source")}：${esc(a.source.log_format || a.source.kind)} ${synthetic}</p>
      <p class="meta">${t("engine")}：${esc(engine)}</p></div>
      <div class="stats">${stat("events", a.timeline.length)}${stat("withheld", a.information_boundary.withheld.length)}${stat("contradictions", a.contradictions.length)}${stat("decisions", a.decision_points.length)}${stat("turning", a.turning_points.length)}</div></div>`;
  }

  const labelChip = (l) => `<span class="chip label-${l}">${esc(t("label")[l] || l)}</span>`;
  const evLinks = (ids) => ids.map((id) => `<a href="#" class="ev-link" data-ev="${id}">${id}</a>`).join(" ");

  function commentaryView(m) {
    return `<ol class="segments">${m.commentary.segments.map((s) => `<li class="seg level-${s.level}">
      <div class="seg-meta"><span class="chip level">${esc(t("level")[s.level])}</span>${labelChip(s.label)}<span class="ids">${evLinks(s.event_ids)}</span></div>
      <p>${esc(s.text[state.locale === "en" ? "en" : "zh-Hant"])}</p>
      ${s.rules ? `<p class="rules-note">${esc(state.locale === "en" ? s.rules.en : s.rules.zh)} <small>${esc((s.rules.rule_locators || []).join(", "))}</small></p>` : ""}
    </li>`).join("")}</ol>`;
  }

  function reviewView(m) {
    const items = m.review.items;
    const counts = Object.entries(m.review.counts).filter(([, v]) => v).map(([k, v]) => `<span class="chip cls-${k}">${esc(t("cls")[k])} ${v}</span>`).join(" ");
    return `<p class="note">${esc(zhOrEn(m.review.notes))}</p><p>${counts}</p>
      <div class="review-items">${items.map((i) => {
        const alts = i.alternatives;
        const others = (alts.items || []).filter((x) => !x.chosen);
        const altList = others.length ? `<ul>${others.map((x) => `<li>${esc(state.locale === "en" ? x.text : x.text_zh)}</li>`).join("")}</ul>` : `<p class="muted">${t("noAlt")}</p>`;
        const chosen = state.locale === "en" ? i.selected_action.text : (i.selected_action.text_zh || i.selected_action.text);
        return `<article class="review-item cls-${i.classification}">
          <header><b>${esc(i.decision_id)}</b> · ${esc((i.actor || "").toUpperCase())} · <a href="#" class="ev-link" data-ev="${i.at_event}">${i.at_event}</a>
            <span class="chip cls-${i.classification}">${esc(t("cls")[i.classification])}</span><span class="chip">${esc(i.confidence)}</span></header>
          <dl>
            <dt>${t("chose")}</dt><dd>${esc(chosen || "—")}</dd>
            <dt>${t("alts")} <small>(${alts.source === "engine_enumeration" ? t("engineList") : t("recordList")})</small></dt><dd>${altList}${alts.add_abilities ? `<p class="muted">${t("addAbilities")(alts.add_abilities)}</p>` : ""}${(alts.abstained || []).length ? `<p class="muted">${t("abstained")}：${esc(alts.abstained.map((x) => x.family).join(", "))}</p>` : ""}</dd>
            <dt>${t("rules")}</dt><dd>${esc(zhOrEn(i.rules_reasoning))}</dd>
            <dt>${t("strategy")}</dt><dd>${esc(zhOrEn(i.strategy_reasoning))}</dd>
            ${i.improvement ? `<dt>${t("improve")}</dt><dd>${esc(zhOrEn(i.improvement))}</dd>` : ""}
            ${i.hindsight_guard ? `<dt>${t("hindsight")}</dt><dd>${esc(zhOrEn(i.hindsight_guard))}</dd>` : ""}
            <dt>${t("evidence")}</dt><dd class="ids">${evLinks(i.information.evidence_events)}</dd>
            <dt>${t("feedback")}</dt><dd>${esc(i.feedback_target || t("none"))}</dd>
          </dl></article>`;
      }).join("")}</div>`;
  }

  function timelineView(m) {
    const tl = m.analysis.timeline;
    const contested = new Set(m.analysis.contradictions.flatMap((c) => c.events));
    const rows = tl.filter((e) => state.all || e.salience !== "low" || e.event_id === state.focus);
    const hidden = tl.length - rows.length;
    const certainty = (e) => (contested.has(e.event_id) ? "unknown" : e.certainty);
    const engineCell = (e) => {
      const g = e.engine || {};
      if (g.mode === "replayed") return `step ${g.step}`;
      if (g.status === "checked") return `<span class="chip outcome-${g.outcome}">${esc(g.outcome)}</span>`;
      if (g.status === "not_reconstructable") return `<span class="muted">${esc((g.missing_information || []).join(", "))}</span>`;
      return "";
    };
    return `<p class="muted">${hidden ? t("lowHidden")(hidden) : ""} <button type="button" class="link-btn" id="toggle-all">${state.all ? t("showLess") : t("showAll")}</button></p>
      <table class="timeline"><thead><tr><th>${t("colId")}</th><th>${t("colSrc")}</th><th>${t("colTurn")}</th><th>${t("colState")}</th><th>${t("colWhat")}</th><th>${t("colLabel")}</th><th>${t("colEngine")}</th></tr></thead>
      <tbody>${rows.map((e) => `<tr id="row-${e.event_id}" class="${e.event_id === state.focus ? "focus" : ""} ${contested.has(e.event_id) ? "contested" : ""}">
        <td><code>${e.event_id}</code></td><td><small>${esc(e.source_event_ids.join(", "))}</small></td><td>${esc(e.turn ?? "")}</td>
        <td><small>${esc(e.state_label ?? "")}</small></td><td>${esc(e.text ? e.text[state.locale === "en" ? "en" : "zh-Hant"] : e.kind)}${e.gap ? `<br /><small class="muted">gap: ${esc(e.gap)}</small>` : ""}</td>
        <td>${labelChip(certainty(e))}</td><td>${engineCell(e)}</td></tr>`).join("")}</tbody></table>`;
  }

  function boundaryView(m) {
    const a = m.analysis;
    const list = (title, items, none) => `<h3>${title}</h3>${items.length ? `<ul>${items.join("")}</ul>` : `<p class="muted">${none}</p>`}`;
    const withheld = a.information_boundary.withheld.map((w) => `<li><code>${w.event_id}</code> ← ${esc(w.source_event_ids.join(", "))} <small>(${esc(w.reason)})</small></li>`);
    const contra = a.contradictions.map((c) => `<li><code>${c.contradiction_id}</code> ${evLinks(c.events)} · ${esc(c.field)}${c.object ? " · " + esc(c.object) : ""}</li>`);
    const assume = (a.assumptions || []).map((x) => `<li>${esc(x)}</li>`);
    const ledger = (a.ledger || []).filter((f) => f.label !== "observed").map((f) => `<li>${labelChip(f.label)} ${esc(state.locale === "en" ? f.statement : f.statement_zh || f.statement)}</li>`);
    const rules = a.information_boundary.rules.map((r) => `<li>${esc(r)}</li>`);
    return `<div class="boundary">${list(t("withheldTitle"), withheld, t("withheldNone"))}${list(t("contraTitle"), contra, t("contraNone"))}${list(t("ledgerTitle"), ledger, t("ledgerNone"))}${list(t("assumeTitle"), assume, t("assumeNone"))}${list(t("rulesTitle"), rules, "")}</div>`;
  }

  function render() {
    applyStatic();
    renderList();
    const panel = document.getElementById("panel");
    const headEl = document.getElementById("match-head");
    if (!DATA.length) { headEl.innerHTML = ""; panel.innerHTML = `<p class="muted">${t("empty")}</p>`; return; }
    const m = DATA[state.match];
    headEl.innerHTML = head(m);
    document.querySelectorAll(".ma-tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === state.tab));
    panel.innerHTML = { commentary: commentaryView, review: reviewView, timeline: timelineView, boundary: boundaryView }[state.tab](m);
    if (state.tab === "timeline" && state.focus) {
      const row = document.getElementById(`row-${state.focus}`);
      if (row) row.scrollIntoView({ block: "center" });
    }
  }

  document.addEventListener("click", (ev) => {
    const target = ev.target.closest("[data-match],[data-tab],[data-ev],#toggle-all,#language-toggle");
    if (!target) return;
    if (target.id === "language-toggle") state.locale = state.locale === "en" ? "zh-Hant" : "en";
    else if (target.id === "toggle-all") state.all = !state.all;
    else if (target.dataset.match !== undefined) { state.match = Number(target.dataset.match); state.focus = null; }
    else if (target.dataset.tab) state.tab = target.dataset.tab;
    else if (target.dataset.ev) { ev.preventDefault(); state.focus = target.dataset.ev; state.tab = "timeline"; }
    render();
  });

  render();
})();
