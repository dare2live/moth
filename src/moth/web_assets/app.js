(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const state = { token: "", projects: [], payload: null, document: null, controller: null };
  const ui = {
    project: byId("project-select"), refresh: byId("refresh-button"), json: byId("json-button"),
    retry: byId("retry-button"), home: byId("home-button"), health: byId("health-badge"),
    summary: byId("status-summary"), generated: byId("generated-at"), welcome: byId("welcome-state"),
    content: byId("content-view"), error: byId("error-state"), errorMessage: byId("error-message"),
    title: byId("section-title"), kicker: byId("section-kicker"), sectionSummary: byId("section-summary"),
    metrics: byId("summary-metrics"), primary: byId("primary-content"), viewpoints: byId("viewpoint-nav"),
    layers: byId("layer-nav"), loading: byId("loading-mask"), dialog: byId("evidence-dialog"),
    evidenceTitle: byId("evidence-title"), evidenceBody: byId("evidence-body"), main: byId("main-content")
  };

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined && text !== null) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }

  function clear(element) {
    while (element.firstChild) element.removeChild(element.firstChild);
  }

  function readToken() {
    const fragment = new URLSearchParams(location.hash.slice(1));
    const fresh = fragment.get("token");
    if (fresh) {
      sessionStorage.setItem("moth.web.token", fresh);
      history.replaceState(null, "", location.pathname);
    }
    return fresh || sessionStorage.getItem("moth.web.token") || "";
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("Authorization", `Bearer ${state.token}`);
    const response = await fetch(path, { ...options, headers });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload.error?.message || `HTTP ${response.status}`;
      throw new Error(message);
    }
    return payload;
  }

  function setLoading(active) {
    ui.loading.hidden = !active;
    ui.project.disabled = active || state.projects.length === 0;
    ui.refresh.disabled = active || !ui.project.value;
    ui.json.disabled = active || !state.payload;
  }

  function showError(error) {
    ui.welcome.hidden = true;
    ui.content.hidden = true;
    ui.error.hidden = false;
    ui.errorMessage.textContent = error instanceof Error ? error.message : String(error);
    ui.health.className = "badge fail";
    ui.health.textContent = "ERROR";
    ui.summary.textContent = "服务返回了明确错误，没有生成猜测结果。";
  }

  function statusClass(value) {
    const normalized = String(value || "").toUpperCase();
    if (normalized === "PASS" || normalized === "READY") return "pass";
    if (normalized === "FAIL" || normalized === "BLOCKED") return "fail";
    return "warn";
  }

  function metric(label, value) {
    const wrap = node("div", null, "metric");
    wrap.append(node("dt", label), node("dd", value));
    return wrap;
  }

  function evidenceButton(ids, label = "查看证据") {
    const button = node("button", label, "evidence-button");
    button.type = "button";
    button.addEventListener("click", () => openEvidence(ids));
    return button;
  }

  function openEvidence(ids) {
    clear(ui.evidenceBody);
    const evidence = state.document?.evidence || {};
    const found = (ids || []).map((id) => evidence[id]).filter(Boolean);
    ui.evidenceTitle.textContent = found.length ? `证据 ${found.length} 条` : "没有可用证据";
    if (!found.length) ui.evidenceBody.append(node("p", "当前对象没有绑定可展示的证据。", "empty"));
    found.forEach((item) => {
      const row = node("article", null, "evidence-row");
      row.append(node("strong", item.kind), node("p", item.summary), node("code", item.locator));
      ui.evidenceBody.append(row);
    });
    ui.dialog.showModal();
  }

  function cardForFinding(finding) {
    const card = node("article", null, "card");
    card.dataset.severity = finding.severity;
    const meta = node("div", null, "card-meta");
    meta.append(node("span", finding.severity), node("span", finding.action_bucket), node("span", finding.confidence));
    card.append(meta, node("h3", finding.title), node("p", finding.why), node("p", `最小安全下一步：${finding.safest_step}`));
    if (finding.evidence_ids?.length) card.append(evidenceButton(finding.evidence_ids));
    return card;
  }

  function cardForEntity(entity) {
    const card = node("article", null, "card");
    const meta = node("div", null, "card-meta");
    meta.append(node("span", entity.kind), node("span", entity.status));
    card.append(meta, node("h3", entity.name), node("p", entity.summary));
    if (entity.evidence_ids?.length) card.append(evidenceButton(entity.evidence_ids));
    return card;
  }

  function section(title, items, renderer) {
    const wrap = node("section", null, "section");
    const header = node("div", null, "section-header");
    header.append(node("h2", title), node("span", `${items.length} 项`));
    wrap.append(header);
    if (!items.length) {
      wrap.append(node("p", "此视图没有可展示的已验证数据。", "empty"));
      return wrap;
    }
    const grid = node("div", null, "card-grid");
    items.forEach((item) => grid.append(renderer(item)));
    wrap.append(grid);
    return wrap;
  }

  function activateNavigation(active) {
    document.querySelectorAll(".rail button").forEach((button) => {
      button.classList.toggle("active", button.dataset.nav === active || (active === "home" && button === ui.home));
    });
  }

  function renderHome() {
    const doc = state.document;
    activateNavigation("home");
    ui.kicker.textContent = "PROJECT OVERVIEW";
    ui.title.textContent = state.payload.project.name;
    ui.sectionSummary.textContent = [state.payload.project.description, doc.status.summary].filter(Boolean).join(" ");
    clear(ui.primary);
    const priorities = (doc.home.priority_finding_ids || []).map((id) => doc.findings[id]).filter(Boolean);
    const avoids = (doc.home.avoid_action_ids || []).map((id) => doc.actions[id]).filter(Boolean);
    ui.primary.append(section("当前优先问题", priorities, cardForFinding));
    ui.primary.append(section("现在不要做", avoids, (action) => {
      const card = node("article", null, "card");
      card.append(node("div", "AVOID", "card-meta"), node("h3", action.title));
      if (action.evidence_ids?.length) card.append(evidenceButton(action.evidence_ids));
      return card;
    }));
    renderArchitecture(doc);
  }

  function renderArchitecture(doc) {
    const wrap = node("section", null, "section");
    const header = node("div", null, "section-header");
    header.append(node("h2", "架构状态"), node("span", doc.architecture.drift?.state || "UNKNOWN"));
    wrap.append(header);
    const grid = node("div", null, "architecture-grid");
    [["As-Is", doc.architecture.as_is], ["To-Be", doc.architecture.to_be]].forEach(([label, value]) => {
      const card = node("article", null, "card");
      card.append(node("div", label, "card-meta"), node("h3", value.state), node("p", `${value.entity_ids.length} 个实体，${value.relation_ids.length} 条关系。`));
      if (value.evidence_ids?.length) card.append(evidenceButton(value.evidence_ids));
      grid.append(card);
    });
    wrap.append(grid);
    ui.primary.append(wrap);
  }

  function renderLayer(layerId) {
    const doc = state.document;
    const layer = doc.layers.find((item) => item.id === layerId);
    if (!layer) return;
    activateNavigation(layerId);
    ui.kicker.textContent = "EVIDENCE LAYER";
    ui.title.textContent = layer.label;
    ui.sectionSummary.textContent = layer.summary;
    clear(ui.primary);
    const findings = layer.finding_ids.map((id) => doc.findings[id]).filter(Boolean);
    const entities = layer.entity_ids.map((id) => doc.entities[id]).filter(Boolean);
    ui.primary.append(section("发现", findings, cardForFinding), section("实体", entities, cardForEntity));
  }

  function renderViewpoint(viewpoint) {
    activateNavigation(viewpoint.id);
    ui.kicker.textContent = "VIEWPOINT";
    ui.title.textContent = viewpoint.label;
    ui.sectionSummary.textContent = "该视角组合了多个证据图层，结论仍来自同一份 visual document。";
    clear(ui.primary);
    viewpoint.layer_ids.forEach((id) => {
      const layer = state.document.layers.find((item) => item.id === id);
      if (!layer) return;
      const findings = layer.finding_ids.map((findingId) => state.document.findings[findingId]).filter(Boolean);
      ui.primary.append(section(layer.label, findings, cardForFinding));
    });
  }

  function buildNavigation(doc) {
    clear(ui.viewpoints);
    clear(ui.layers);
    ui.home.dataset.nav = "home";
    (doc.navigation.viewpoints || []).forEach((viewpoint) => {
      const button = node("button", viewpoint.label);
      button.type = "button";
      button.dataset.nav = viewpoint.id;
      button.addEventListener("click", () => renderViewpoint(viewpoint));
      ui.viewpoints.append(button);
    });
    (doc.navigation.layers || []).forEach((item) => {
      const button = node("button", item.label);
      button.type = "button";
      button.dataset.nav = item.id;
      button.addEventListener("click", () => renderLayer(item.id));
      ui.layers.append(button);
    });
  }

  function renderPayload(payload) {
    state.payload = payload;
    state.document = payload.visual_document;
    const doc = state.document;
    ui.welcome.hidden = true;
    ui.error.hidden = true;
    ui.content.hidden = false;
    ui.health.className = `badge ${statusClass(doc.status.value)}`;
    ui.health.textContent = doc.status.value;
    ui.summary.textContent = `${doc.status.label} · ${doc.status.project_health} · ${doc.status.context_readiness}`;
    ui.generated.textContent = doc.source.generated_at ? `生成于 ${new Date(doc.source.generated_at).toLocaleString()}` : "";
    clear(ui.metrics);
    ui.metrics.append(metric("实体", Object.keys(doc.entities).length), metric("发现", Object.keys(doc.findings).length), metric("图层", doc.layers.length), metric("策略", payload.execution_policy));
    buildNavigation(doc);
    renderHome();
    ui.json.disabled = false;
    ui.main.focus();
  }

  async function inspectProject() {
    if (!ui.project.value) return;
    if (state.controller) state.controller.abort();
    state.controller = new AbortController();
    setLoading(true);
    try {
      const payload = await api("/api/v1/inspections", {
        method: "POST",
        signal: state.controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: ui.project.value })
      });
      renderPayload(payload);
    } catch (error) {
      if (error.name !== "AbortError") showError(error);
    } finally {
      setLoading(false);
    }
  }

  async function initialize() {
    state.token = readToken();
    if (!state.token) {
      showError(new Error("缺少本次服务的 capability token。请使用 moth serve 输出的完整地址。"));
      return;
    }
    try {
      const registry = await api("/api/v1/projects");
      state.projects = registry.projects || [];
      clear(ui.project);
      state.projects.forEach((project) => {
        const option = node("option", project.name);
        option.value = project.id;
        ui.project.append(option);
      });
      if (!state.projects.length) throw new Error("配置中没有可选择的项目。");
      ui.project.disabled = false;
      ui.refresh.disabled = false;
      await inspectProject();
    } catch (error) {
      showError(error);
      setLoading(false);
    }
  }

  ui.project.addEventListener("change", inspectProject);
  ui.refresh.addEventListener("click", inspectProject);
  ui.retry.addEventListener("click", inspectProject);
  ui.home.addEventListener("click", renderHome);
  ui.json.addEventListener("click", () => {
    if (!state.payload) return;
    const blob = new Blob([JSON.stringify(state.payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  });
  initialize();
})();
