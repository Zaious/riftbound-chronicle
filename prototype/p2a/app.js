(() => {
  "use strict";

  const CONSTANTS = Object.freeze({
    schema_version: "p2a-session.v1",
    mode: "player2-agent",
    automation_level: "P2-A",
    p2s_enabled: false,
    state_authority: "user_confirmed",
    legality_authority: "user_confirmed",
  });

  let session = null;
  let toastTimer = null;

  const $ = (selector) => document.querySelector(selector);
  const elements = {
    sessionForm: $("#session-form"),
    stateForm: $("#state-form"),
    proposalForm: $("#proposal-form"),
    confirmationForm: $("#confirmation-form"),
    copyBrief: $("#copy-brief"),
    exportButton: $("#export-session"),
    resetButton: $("#reset-session"),
    ledger: $("#ledger"),
    ledgerEmpty: $("#ledger-empty"),
    proposalSelect: $("#proposal-select"),
    eventCount: $("#event-count"),
    shortId: $("#session-id-short"),
    statusBanner: $("#status-banner"),
    toast: $("#toast"),
  };

  function nowIso() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  function makeId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `p2a-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function formValues(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  function appendEvent(event) {
    session.events.push({ seq: session.events.length + 1, recorded_at: nowIso(), ...event });
    render();
  }

  function latestEvent(type) {
    return [...(session?.events || [])].reverse().find((event) => event.type === type) || null;
  }

  function latestState() {
    return latestEvent("state_confirmed");
  }

  function pendingProposals() {
    if (!session) return [];
    const confirmed = new Set(session.events.filter((event) => event.type === "action_confirmed").map((event) => event.action_id));
    const currentState = latestState();
    return session.events.filter((event) => event.type === "action_proposed" && event.state_seq === currentState?.seq && !confirmed.has(event.action_id));
  }

  function awaitingState() {
    if (!session?.events.length) return false;
    const last = session.events.at(-1);
    return last.type === "action_confirmed" && last.legal === true;
  }

  function currentStep() {
    if (!session) return "session";
    if (!latestState() || awaitingState()) return awaitingState() ? "next-state" : "state";
    if (pendingProposals().length) return "confirmation";
    return "proposal";
  }

  function setFormEnabled(form, enabled) {
    form.classList.toggle("disabled-form", !enabled);
    for (const control of form.elements) control.disabled = !enabled;
  }

  function setPanelState(id, label) {
    $(id).textContent = label;
  }

  function setStatus(step) {
    const copy = {
      session: ["Create a session to begin", "The ledger lives only in this browser tab until you export it."],
      state: ["Describe the physical table", "Only a human-confirmed snapshot becomes authoritative state."],
      proposal: ["Ask Player 2 Agent for a choice", "The recommendation stays unverified until the human checks legality."],
      confirmation: ["Human confirmation required", "Check legality, resolve with the physical cards, then record the result."],
      "next-state": ["Resolution does not update the board", "Return to Step 2 and confirm the resulting physical state."],
    };
    const [title, detail] = copy[step];
    elements.statusBanner.classList.toggle("warning", step === "confirmation" || step === "next-state");
    elements.statusBanner.querySelector("strong").textContent = title;
    elements.statusBanner.querySelector("p").textContent = detail;
    elements.statusBanner.querySelector(".status-icon").textContent = step === "confirmation" || step === "next-state" ? "!" : "→";
  }

  function renderSteps(step) {
    const order = ["session", "state", "proposal", "confirmation", "next-state"];
    const currentIndex = order.indexOf(step);
    document.querySelectorAll("#flow-steps li").forEach((item) => {
      const index = order.indexOf(item.dataset.step);
      item.classList.toggle("current", index === currentIndex);
      item.classList.toggle("done", session && index < currentIndex && !(step === "state" && index > 0));
    });
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function renderLedger() {
    const events = session?.events || [];
    elements.eventCount.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
    elements.ledgerEmpty.hidden = events.length > 0;
    elements.ledger.classList.toggle("has-events", events.length > 0);
    elements.ledger.innerHTML = events.map((event) => {
      const time = new Date(event.recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      if (event.type === "state_confirmed") {
        return `<li><div class="ledger-meta"><span>#${event.seq} state confirmed</span><time>${time}</time></div><strong>Turn ${event.turn} · ${escapeHtml(event.turn_player)} · ${escapeHtml(event.phase)}</strong><p>${escapeHtml(event.public_state)}</p><span class="ledger-tag">user confirmed</span></li>`;
      }
      if (event.type === "action_proposed") {
        return `<li class="proposal"><div class="ledger-meta"><span>#${event.seq} agent proposal</span><time>${time}</time></div><strong>${escapeHtml(event.action_id)} · ${escapeHtml(event.description)}</strong><p>${escapeHtml(event.reason)}</p><span class="ledger-tag">legality unverified</span></li>`;
      }
      const rejected = event.legal === false;
      return `<li class="${rejected ? "rejected" : ""}"><div class="ledger-meta"><span>#${event.seq} human check</span><time>${time}</time></div><strong>${escapeHtml(event.action_id)} · ${rejected ? "Rejected" : "Confirmed legal"}</strong><p>${escapeHtml(event.resolution_summary || (rejected ? "No state change" : "Awaiting a new human-confirmed state"))}</p><span class="ledger-tag">${rejected ? "no transition" : "snapshot required"}</span></li>`;
    }).join("");
  }

  function renderProposalSelect() {
    const proposals = pendingProposals();
    elements.proposalSelect.innerHTML = proposals.map((proposal) => `<option value="${escapeHtml(proposal.action_id)}">${escapeHtml(proposal.action_id)} — ${escapeHtml(proposal.description)}</option>`).join("");
  }

  function render() {
    const step = currentStep();
    const hasSession = Boolean(session);
    const hasState = Boolean(latestState());
    const canPropose = hasSession && hasState && !awaitingState();
    const canConfirm = pendingProposals().length > 0 && !awaitingState();

    setFormEnabled(elements.sessionForm, !hasSession);
    setFormEnabled(elements.stateForm, hasSession && (!hasState || awaitingState() || !canConfirm));
    setFormEnabled(elements.proposalForm, canPropose);
    setFormEnabled(elements.confirmationForm, canConfirm);
    elements.copyBrief.disabled = !canPropose;
    elements.exportButton.disabled = !hasSession;
    elements.resetButton.disabled = !hasSession;

    setPanelState("#session-panel-state", hasSession ? "Complete" : "Required");
    setPanelState("#state-panel-state", !hasSession ? "Locked" : awaitingState() ? "Required" : hasState ? "Confirmed" : "Required");
    setPanelState("#proposal-panel-state", canPropose ? "Ready" : "Locked");
    setPanelState("#confirmation-panel-state", canConfirm ? "Required" : "Locked");

    $("#session-panel").open = !hasSession;
    $("#state-panel").open = hasSession && (!hasState || awaitingState());
    $("#proposal-panel").open = step === "proposal";
    $("#confirmation-panel").open = step === "confirmation";

    elements.shortId.textContent = session ? session.session_id.slice(0, 8) : "Not started";
    renderSteps(step);
    setStatus(step);
    renderProposalSelect();
    renderLedger();
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    elements.toast.textContent = message;
    elements.toast.classList.add("show");
    toastTimer = setTimeout(() => elements.toast.classList.remove("show"), 2600);
  }

  elements.sessionForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = formValues(event.currentTarget);
    session = {
      ...CONSTANTS,
      session_id: makeId(),
      created_at: nowIso(),
      created_by: values.operator.trim(),
      format: values.format.trim(),
      ruleset_version: values.ruleset.trim(),
      decks: { player1: values.player1.trim(), player2: values.player2.trim() },
      events: [],
    };
    elements.stateForm.elements.confirmedBy.value = values.operator.trim();
    elements.confirmationForm.elements.confirmedBy.value = values.operator.trim();
    render();
    showToast("P2-A session created. No game state was inferred.");
  });

  elements.stateForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = formValues(event.currentTarget);
    appendEvent({
      type: "state_confirmed",
      authority: "user_confirmed",
      confirmed_by: values.confirmedBy.trim(),
      turn: Number(values.turn),
      turn_player: values.turnPlayer,
      phase: values.phase.trim(),
      public_state: values.publicState.trim(),
      player2_private_hand: values.player2Hand.trim(),
      notes: values.notes.trim(),
    });
    event.currentTarget.elements.publicState.value = "";
    event.currentTarget.elements.player2Hand.value = "";
    event.currentTarget.elements.notes.value = "";
    showToast("Human-confirmed state added to the ledger.");
  });

  elements.proposalForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = formValues(event.currentTarget);
    const actionId = values.actionId.trim();
    if (session.events.some((item) => item.type === "action_proposed" && item.action_id === actionId)) {
      showToast("Action ID already exists. Use a unique identifier.");
      return;
    }
    appendEvent({
      type: "action_proposed",
      action_id: actionId,
      state_seq: latestState().seq,
      objective: values.objective.trim(),
      description: values.description.trim(),
      reason: values.reason.trim(),
      alternative: values.alternative.trim(),
      assumptions: values.assumptions.split("\n").map((line) => line.trim()).filter(Boolean),
      legality_status: "unverified",
    });
    event.currentTarget.reset();
    showToast("Agent proposal recorded as unverified.");
  });

  elements.confirmationForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = formValues(event.currentTarget);
    const legal = values.legal === "true";
    appendEvent({
      type: "action_confirmed",
      action_id: values.actionId,
      legal,
      confirmed_by: values.confirmedBy.trim(),
      resolution_summary: values.resolution.trim(),
      state_transition: legal ? "pending_user_snapshot" : "none",
    });
    event.currentTarget.elements.resolution.value = "";
    showToast(legal ? "Legal action confirmed. A new state snapshot is now required." : "Proposal rejected without a state transition.");
  });

  elements.copyBrief.addEventListener("click", async () => {
    const state = latestState();
    if (!state) return;
    const brief = [
      "Use the Riftbound player2-agent P2-A mode.",
      `Format: ${session.format}`,
      `Ruleset: ${session.ruleset_version}`,
      `Player 2 deck: ${session.decks.player2}`,
      `Turn ${state.turn}; turn player: ${state.turn_player}; phase: ${state.phase}`,
      `Public state: ${state.public_state}`,
      `Player 2 private hand: ${state.player2_private_hand || "not supplied"}`,
      `Human notes: ${state.notes || "none"}`,
      "Return: objective, preferred action, why, important alternative, assumptions, and the exact line 'Legality status: unverified — human confirmation required'. Do not infer or resolve the resulting state.",
    ].join("\n");
    try {
      await navigator.clipboard.writeText(brief);
      showToast("Agent brief copied.");
    } catch {
      showToast("Clipboard permission unavailable. Copy from the browser manually.");
    }
  });

  elements.exportButton.addEventListener("click", () => {
    const blob = new Blob([`${JSON.stringify(session, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `p2a-${session.session_id.slice(0, 8)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    showToast("Session JSON exported.");
  });

  elements.resetButton.addEventListener("click", () => {
    if (!confirm("Reset this in-tab prototype session? Export first if you need the ledger.")) return;
    session = null;
    elements.sessionForm.reset();
    elements.stateForm.reset();
    elements.proposalForm.reset();
    elements.confirmationForm.reset();
    render();
    showToast("Prototype session reset.");
  });

  render();
})();
