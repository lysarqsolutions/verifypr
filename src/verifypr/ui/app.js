// VerifyPR local page. No frameworks, no build step, no data from the repository is ever
// inserted as HTML (only textContent). The session token lives in memory only.
"use strict";

(() => {
  const S = window.VPR_STRINGS;
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.hash.slice(1));
  const TOKEN = params.get("token") || "";
  history.replaceState(null, "", location.pathname); // keep the token out of history/screens

  let state = null;
  let last = null;
  let filter = "all";
  let stageTimer = null;

  // ---- helpers ------------------------------------------------------------------------
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === false || v === null || v === undefined) continue;
      if (k === "text") el.textContent = v;
      else if (k === "class") el.className = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined) el.append(c);
    return el;
  }

  async function api(path, { method = "GET", body } = {}) {
    const res = await fetch(path, {
      method,
      headers: { "X-VerifyPR-Token": TOKEN, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const type = res.headers.get("content-type") || "";
    const data = type.includes("json") ? await res.json() : await res.text();
    if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
    return data;
  }

  async function copy(text, msgEl, msg) {
    try {
      await navigator.clipboard.writeText(text);
      msgEl.textContent = msg;
    } catch {
      msgEl.textContent = text; // fall back: show it so it can be selected and copied
    }
  }

  function say(el, text) { el.textContent = text || ""; }

  // ---- static text --------------------------------------------------------------------
  function fillStrings() {
    const set = (id, text) => { const el = $(id); if (el) el.textContent = text; };
    set("compare-label", S.comparing);
    set("top-title", S.topIssues); set("maybe-title", S.worthALook); set("checks-title", S.pleaseCheck);
    set("agent-btn", S.agentBtn); set("agent-btn-2", S.agentBtn); set("all-btn", S.allChanges);
    set("stricter-btn", S.stricter); set("again-btn", S.checkAgain);
    set("stricter-title", S.stricterTitle); set("describe-label", S.describeLabel);
    set("describe-check", S.describeCheck); set("suggest-btn", S.suggest); set("scope-title", S.scopeTitle);
    set("scope-allowed-label", S.scopeAllowed); set("scope-forbidden-label", S.scopeForbidden);
    set("scope-save", S.scopeSave); set("details-title", S.detailsTitle); set("numbers-title", S.numbers);
    set("pr-summary-btn", S.prSummary); set("share-label", S.share); set("advanced-label", S.advanced);
    set("patch-btn", S.patch); set("patch-help", S.patchHelp);
    set("consent-title", S.consentTitle); set("consent-yes", S.consentYes); set("consent-no", S.consentNo);
    set("open-settings", S.settings); set("settings-title", S.settings); set("close-settings", S.close);
    set("ai-title", S.aiTitle); set("ai-offline", S.aiOffline); set("provider-label", S.provider);
    set("key-label", S.keyLabel); set("key-show", S.show); set("key-where", S.whereKey);
    set("remember-label", S.remember); set("key-save", S.keySave); set("key-test", S.keyTest);
    set("key-remove", S.keyRemove); set("rules-title", S.rulesTitle); set("rules-export", S.exportRules);
    set("saved-scope-title", S.savedScopeTitle); set("scope-clear", S.clearScope);
    set("vo-title", S.voTitle); set("vo-text", S.voText); set("vo-on", S.voOn);
    set("wizard-title", S.wizardTitle); set("wizard-text", S.wizardText);
    set("wizard-setup", S.wizardSetup); set("wizard-skip", S.wizardSkip);
    set("help-title", S.helpTitle); set("close-help", S.close); set("shortcuts-off", S.shortcutsOff);
    set("kept-title", S.keptTitle);
    $("help-list").replaceChildren(...S.help.map((t) => h("li", { text: t })));
    for (const b of document.querySelectorAll("[data-filter]")) b.textContent = S.filters[b.dataset.filter];
  }

  // ---- state + header -----------------------------------------------------------------
  async function loadState() {
    state = await api("/api/state");
    $("project").textContent = state.project;
    const base = $("base");
    const current = state.base || "";
    base.replaceChildren(h("option", { value: "", text: "the main branch (automatic)" }),
      ...state.branches.map((b) => h("option", { value: b, text: b, selected: b === current })));
    const badge = $("viewonly-badge");
    badge.hidden = !state.view_only;
    badge.textContent = state.offline ? S.viewOnlyOffline : S.viewOnly;
    document.body.classList.toggle("view-only", state.view_only);
    for (const el of document.querySelectorAll("[data-write]")) el.hidden = state.view_only;
    $("vo-on").hidden = state.view_only;
    const configured = state.providers.some((p) => p.source !== "none");
    $("wizard").hidden = state.wizard_done || configured || state.offline || state.view_only;
    renderSettings();
  }

  // ---- checking ------------------------------------------------------------------------
  function startStages() {
    let i = 0;
    $("status").setAttribute("aria-busy", "true");
    say($("headline"), S.stages[0]);
    stageTimer = setInterval(() => { i = (i + 1) % S.stages.length; say($("headline"), S.stages[i]); }, 1400);
  }
  function stopStages() { clearInterval(stageTimer); $("status").setAttribute("aria-busy", "false"); }

  async function runCheck() {
    startStages();
    try {
      const data = await api("/api/check", {
        method: "POST",
        body: { describe: $("describe").value.trim() || null, base: $("base").value },
      });
      stopStages();
      if (data.error) { showError(data.error + (data.hint ? ` ${data.hint}` : "")); return; }
      last = data;
      render();
      if (data.needs_consent) askConsent(data.needs_consent);
    } catch (err) { stopStages(); showError(err.message); }
  }

  function showError(msg) {
    $("status-label").className = "status fail";
    say($("status-label"), S.status.fail);
    say($("headline"), `${S.error} ${msg}`);
  }

  function askConsent(text) {
    say($("consent-text"), text);
    $("consent").showModal();
  }

  async function answerConsent(allow) {
    $("consent").close();
    await api("/api/consent", { method: "POST", body: { allow } });
    if (allow) runCheck();
  }

  // ---- rendering -----------------------------------------------------------------------
  function render() {
    const r = last.report;
    const kind = r.file_count ? r.verdict : "none";
    const label = $("status-label");
    label.className = `status ${kind}`;
    say(label, r.status_label);  // same words as the terminal and reports
    say($("headline"), r.headline);
    say($("compared"), r.file_count ? r.compared : "");
    say($("against"), r.intent ? (r.intent_inferred ? `Checked against (my best guess): ${r.intent}` : `Checked against: ${r.intent}`) : "");
    say($("progress"), r.progress ? `${S.sinceLast} ${progressText(r.progress)}` : "");
    const notes = [...last.notes];
    if (r.kept_count) notes.push(S.hiddenKept(r.kept_count));
    if (r.allowed_count) notes.push(S.hiddenAllowed(r.allowed_count));
    if (!r.ai_used && !r.offline && r.file_count) notes.push("Only basic rule-based checks ran.");
    $("notes").replaceChildren(...notes.map((n) => h("li", { text: n })));

    $("summary").hidden = !r.file_count;
    const byId = Object.fromEntries(last.findings.map((f) => [f.id, f]));
    $("top-issues").replaceChildren(...last.top_ids.map((id) => issueItem(byId[id])));
    $("top-title").hidden = !last.top_ids.length;
    $("top-issues").hidden = !last.top_ids.length;
    const maybe = last.findings.filter((f) => f.worth_a_look).slice(0, 3);
    $("maybe-wrap").hidden = !maybe.length;
    $("maybe").replaceChildren(...maybe.map((f) => h("li", {}, h("span", { text: f.title }), " — ", h("span", { class: "importance", text: f.importance }))));
    renderChecks();
    renderDetails();
  }

  function progressText(p) {
    return `Fixed ${p.fixed} of ${p.previous} · ${p.still_open} still open · ${p.new} new issue${p.new === 1 ? "" : "s"}`;
  }

  function issueItem(f) {
    return h("li", {},
      h("span", { class: "issue-title", text: f.title }), " — ",
      h("span", { class: "importance", text: f.importance }),
      h("details", {}, h("summary", { text: S.why }), h("p", { text: f.why }),
        h("p", { class: "muted", text: `${S.where} ${f.where.join(", ")}` })));
  }

  function renderChecks() {
    const items = last.check_items;
    $("checks-wrap").hidden = !items.length;
    const update = () => {
      const done = [...document.querySelectorAll("#checks input")].filter((c) => c.checked).length;
      say($("checks-progress"), S.checkedOf(done, items.length));
    };
    $("checks").replaceChildren(...items.map((text, i) => h("li", {},
      h("label", { for: `chk-${i}` }, h("input", { type: "checkbox", id: `chk-${i}`, onchange: update }), h("span", { text })))));
    update();
  }

  const FILTERS = {
    all: () => true,
    tidy: (f) => ["formatting", "formatting_mixed", "file_mode", "artifacts", "dependencies"].includes(f.category),
    tests: (f) => ["test_integrity", "guardrails"].includes(f.category),
    scope: (f) => f.classification === "unintended" || f.classification === "unclear" || f.category.startsWith("scope"),
  };

  function groupOf(f) {
    if (f.classification === "unintended" || f.category === "scope" || f.category === "scope_new_file") return "unintended";
    if (f.classification === "unclear") return "unclear";
    return "other";
  }

  function renderDetails() {
    const groups = { unintended: [], unclear: [], other: [] };
    for (const f of last.findings.filter(FILTERS[filter])) groups[groupOf(f)].push(f);
    const out = [];
    for (const [key, items] of Object.entries(groups)) {
      if (!items.length) continue;
      out.push(h("h3", { text: `${S.groups[key]} (${items.length})` }), ...items.map(card));
    }
    if (filter === "all" || filter === "scope") {
      for (const cls of ["supporting", "intended"]) {
        const items = last.changes.filter((c) => c.classification === cls);
        if (!items.length) continue;
        out.push(h("details", {}, h("summary", { text: `${S.groups[cls]} (${items.length})` }),
          h("ul", { class: "plain" }, ...items.map((c) => h("li", { text: `${c.file_path}:${c.start_line}-${c.end_line} — ${c.reason}` })))));
      }
    }
    if (!out.length) out.push(h("p", { class: "muted", text: "Nothing in this group." }));
    $("groups").replaceChildren(...out);
    const r = last.report;
    const counts = ["unintended", "unclear", "intended", "supporting"]
      .map((c) => `${last.changes.filter((x) => x.classification === c).length} ${S.groups[c].toLowerCase()}`);
    say($("numbers"), `${r.file_count} files changed · ${last.findings.length} findings` + (last.changes.length ? ` · ${counts.join(" · ")}` : "") +
      (r.ai_tokens ? ` · ${r.ai_tokens.toLocaleString()} AI tokens (${r.ai_cost})` : ""));
  }

  function codeFor(f) {
    const files = new Set(f.where.map((w) => w.split(":")[0]));
    let lines = last.changes.filter((c) => files.has(c.file_path)).flatMap((c) => c.code).slice(0, 40);
    if (!lines.length) {
      lines = f.evidence.filter((e) => e.snippet).flatMap((e) => e.snippet.split("\n").map((l) => `+${l}`)).slice(0, 20);
    }
    if (!lines.length) return null;
    return h("pre", { class: "code", tabindex: "0", "aria-label": "Code" },
      ...lines.map((l) => h("span", { class: l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "", text: `${l}\n` })));
  }

  function card(f) {
    const msg = h("p", { class: "muted", role: "status" });
    const where = f.where[0] || "";
    const actions = h("div", { class: "row" });
    if (!state.view_only) {
      actions.append(
        h("button", { type: "button", text: S.keep, onclick: async () => { await api("/api/keep", { method: "POST", body: { finding_id: f.id, title: f.title } }); say(msg, S.kept); loadState(); } }),
        h("button", { type: "button", text: S.allowHere, onclick: async () => {
          const res = await api("/api/allow", { method: "POST", body: { finding_id: f.id } });
          say(msg, S.allowed(res.pattern)); loadState();
        } }));
      if (f.classification === "unintended" || f.classification === "unclear" || f.category.startsWith("scope")) {
        actions.append(h("button", { type: "button", text: S.addScope, onclick: async () => {
          const res = await api("/api/scope/add", { method: "POST", body: { finding_id: f.id } });
          say(msg, S.scopeAdded(res.pattern)); loadState();
        } }));
      }
    }
    actions.append(h("button", { type: "button", text: S.copyUndo, onclick: () => copy(S.undoSteps(where, state.view_only), msg, S.undoCopied) }));
    if (f.editor) actions.append(h("a", { href: f.editor, text: S.openEditor }));
    return h("article", { class: "change" },
      h("p", { class: "issue-title", text: f.title }),
      h("p", { class: "meta", text: `${f.importance} · ${f.where.join(", ")}` }),
      h("details", {}, h("summary", { text: S.why }), h("p", { text: f.why })),
      codeFor(f), actions, msg);
  }

  // ---- footer actions ------------------------------------------------------------------
  async function tellAgent() {
    const msg = $("copied");
    if (!last || !last.agent_prompt) { say(msg, S.nothingToFix); return; }
    await copy(last.agent_prompt, msg, S.agentCopied);
  }

  async function download(path, name) {
    const res = await fetch(path, { headers: { "X-VerifyPR-Token": TOKEN } });
    if (!res.ok) { say($("copied"), `${S.error} ${(await res.json()).error}`); return; }
    const url = URL.createObjectURL(await res.blob());
    const a = h("a", { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  // ---- stricter: describe + suggest scope ---------------------------------------------
  async function suggest() {
    const text = $("describe").value.trim();
    if (!text) { $("describe").focus(); return; }
    say($("scope-msg"), "…");
    const res = await api("/api/scope/suggest", { method: "POST", body: { description: text } });
    if (res.needs_consent) { say($("scope-msg"), ""); askConsentThen(res.needs_consent, suggest); return; }
    if (res.error) { say($("scope-msg"), res.error); return; }
    $("scope-editor").hidden = false;
    $("scope-allowed").value = res.scope.allowed.paths.join(", ");
    $("scope-forbidden").value = res.scope.forbidden.paths.join(", ");
    $("scope-editor").dataset.goal = res.scope.goal;
    $("scope-editor").dataset.allowedBehaviors = JSON.stringify(res.scope.allowed.behaviors);
    $("scope-editor").dataset.forbiddenBehaviors = JSON.stringify(res.scope.forbidden.behaviors);
    say($("scope-msg"), "");
  }

  function askConsentThen(text, then) {
    say($("consent-text"), text);
    const dialog = $("consent");
    dialog.dataset.then = "suggest";
    dialog.showModal();
    pendingThen = then;
  }
  let pendingThen = null;
  let shortcutsOn = true;

  async function saveScope() {
    const list = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);
    const ed = $("scope-editor");
    await api("/api/scope", { method: "POST", body: {
      goal: ed.dataset.goal || $("describe").value.trim(),
      allowed_paths: list($("scope-allowed").value), forbidden_paths: list($("scope-forbidden").value),
      allowed_behaviors: JSON.parse(ed.dataset.allowedBehaviors || "[]"),
      forbidden_behaviors: JSON.parse(ed.dataset.forbiddenBehaviors || "[]"),
    } });
    say($("scope-msg"), S.scopeSaved);
    await loadState();
    runCheck();
  }

  // ---- settings ------------------------------------------------------------------------
  const KEY_PAGES = {
    anthropic: "https://console.anthropic.com/", openai: "https://platform.openai.com/api-keys",
    openrouter: "https://openrouter.ai/keys", azure: "https://portal.azure.com/",
  };

  function renderSettings() {
    $("ai-offline").hidden = !state.offline;
    $("ai-form").hidden = state.offline;
    $("remember-wrap").hidden = state.view_only;
    $("key-remove").hidden = state.view_only;
    const select = $("provider");
    const chosen = select.value || "anthropic";
    select.replaceChildren(...state.providers.map((p) => h("option", { value: p.provider, text: S.providerNames[p.provider] || p.provider, selected: p.provider === chosen })));
    $("provider-status").replaceChildren(...state.providers.map((p) => {
      let how = S.noKey;
      if (p.source === "no_key_needed") how = S.noKeyNeeded;
      else if (p.source === "environment") how = `${p.masked} (${S.fromEnv(p.env_var)})`;
      else if (p.source === "login") how = S.signedIn(p.signed_in);
      else if (p.masked) how = `${p.masked} (${p.source})`;
      return h("li", { text: `${S.providerNames[p.provider] || p.provider}: ${how}` });
    }));
    updateKeyLink();
    $("rules").replaceChildren(...(state.allow_rules.length ? state.allow_rules.map((r) => h("li", {},
      h("span", { text: `${r.kind} in ${r.paths.join(", ")} ` }),
      state.view_only ? null : h("button", { type: "button", class: "ghost", text: S.remove, onclick: async () => { await api(`/api/allow-rules/${r.index}`, { method: "DELETE" }); await loadState(); } })))
      : [h("li", { class: "muted", text: S.noRules })]));
    $("kept").replaceChildren(...(state.kept.length ? state.kept.map((k) => h("li", {},
      h("span", { text: `${k.title} ` }),
      state.view_only ? null : h("button", { type: "button", class: "ghost", text: S.showAgain, onclick: async () => { await api("/api/unkeep", { method: "POST", body: { finding_id: k.id } }); await loadState(); runCheck(); } })))
      : [h("li", { class: "muted", text: S.noneKept })]));
    say($("saved-scope"), state.scope ? state.scope.goal : S.noScope);
    $("scope-clear").hidden = !state.scope || state.view_only;
  }

  function updateKeyLink() {
    const p = $("provider").value;
    const link = $("key-where");
    link.hidden = !KEY_PAGES[p];
    if (KEY_PAGES[p]) link.href = KEY_PAGES[p];
    const envProvider = state.providers.find((x) => x.provider === p && x.source === "environment");
    $("api-key").disabled = Boolean(envProvider);
  }

  async function saveKey() {
    const key = $("api-key").value.trim();
    if (!key) { $("api-key").focus(); return; }
    try {
      const res = await api("/api/key", { method: "POST", body: { provider: $("provider").value, key, remember: $("remember").checked && !state.view_only } });
      $("api-key").value = "";
      say($("key-msg"), S.keySaved(res.masked, res.saved) + (res.note ? ` ${res.note}` : ""));
      await loadState();
    } catch (err) { say($("key-msg"), err.message); }
  }

  // ---- wiring --------------------------------------------------------------------------
  function toggle(sectionId, button) {
    const section = $(sectionId);
    section.hidden = !section.hidden;
    button.setAttribute("aria-expanded", String(!section.hidden));
    if (sectionId === "details") button.textContent = section.hidden ? S.allChanges : S.hideChanges;
    if (!section.hidden) section.scrollIntoView({ block: "start" });
  }

  function wire() {
    $("again-btn").onclick = runCheck;
    $("base").onchange = runCheck;
    $("all-btn").onclick = () => toggle("details", $("all-btn"));
    $("stricter-btn").onclick = () => { toggle("stricter", $("stricter-btn")); $("describe").focus(); };
    $("describe-check").onclick = runCheck;
    $("suggest-btn").onclick = () => suggest().catch((e) => say($("scope-msg"), e.message));
    $("scope-save").onclick = () => saveScope().catch((e) => say($("scope-msg"), e.message));
    $("agent-btn").onclick = tellAgent;
    $("agent-btn-2").onclick = tellAgent;
    $("pr-summary-btn").onclick = async () => copy(await api("/api/report.md"), $("copied"), S.prCopied);
    for (const b of document.querySelectorAll("[data-report]")) b.onclick = () => download(`/api/report.${b.dataset.report}`, `verifypr-report.${b.dataset.report}`);
    $("patch-btn").onclick = () => download("/api/patch", "verifypr-undo.patch");
    $("consent-yes").onclick = async () => { const then = pendingThen; pendingThen = null; await answerConsent(true); if (then) then(); };
    $("consent-no").onclick = () => { pendingThen = null; answerConsent(false); };
    $("open-settings").onclick = () => { renderSettings(); $("settings").showModal(); };
    $("close-settings").onclick = () => $("settings").close();
    $("open-help").onclick = () => $("help").showModal();
    $("close-help").onclick = () => $("help").close();
    $("shortcuts-off").onclick = () => {
      shortcutsOn = !shortcutsOn;
      $("shortcuts-off").textContent = shortcutsOn ? S.shortcutsOff : S.shortcutsOn;
      $("shortcuts-off").setAttribute("aria-pressed", String(!shortcutsOn));
    };
    $("provider").onchange = updateKeyLink;
    $("key-show").onclick = () => {
      const input = $("api-key");
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      $("key-show").textContent = showing ? S.show : S.hide;
      $("key-show").setAttribute("aria-pressed", String(!showing));
    };
    $("key-save").onclick = saveKey;
    $("key-test").onclick = async () => { say($("key-msg"), "…"); const r = await api("/api/key/test", { method: "POST", body: { provider: $("provider").value } }); say($("key-msg"), r.ok ? `✔ ${r.message}` : r.message); };
    $("key-remove").onclick = async () => { await api(`/api/key/${$("provider").value}`, { method: "DELETE" }); say($("key-msg"), S.keyRemoved); await loadState(); };
    $("rules-export").onclick = async () => copy(await api("/api/allow-rules/export"), $("key-msg"), S.rulesCopied);
    $("scope-clear").onclick = async () => { await api("/api/scope", { method: "DELETE" }); await loadState(); runCheck(); };
    $("vo-on").onclick = async () => { await api("/api/view-only", { method: "POST" }); await loadState(); render(); };
    $("wizard-setup").onclick = () => { $("settings").showModal(); };
    $("wizard-skip").onclick = async () => { await api("/api/wizard-done", { method: "POST" }); $("wizard").hidden = true; };
    for (const b of document.querySelectorAll("[data-filter]")) {
      b.onclick = () => {
        filter = b.dataset.filter;
        for (const o of document.querySelectorAll("[data-filter]")) o.setAttribute("aria-pressed", String(o === b));
        if (last) renderDetails();
      };
    }
    document.addEventListener("keydown", (e) => {
      if (!shortcutsOn || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.target.closest("input, textarea, select") || document.querySelector("dialog[open]")) return;
      if (e.key === "c") runCheck();
      else if (e.key === "a") toggle("details", $("all-btn"));
      else if (e.key === "s") { toggle("stricter", $("stricter-btn")); if (!$("stricter").hidden) $("describe").focus(); }
      else if (e.key === "?") $("help").showModal();
    });
  }

  async function start() {
    fillStrings();
    wire();
    if (!TOKEN) { showError("Open this page from the link VerifyPR printed in your terminal."); return; }
    try { await loadState(); } catch (err) { showError(err.message); return; }
    runCheck();
  }

  document.addEventListener("DOMContentLoaded", start);
})();
