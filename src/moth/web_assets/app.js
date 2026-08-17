(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const state = {
    token: "",
    projects: [],
    payload: null,
    document: null,
    controller: null,
    navigationMode: "map"
  };
  const ui = {
    project: byId("project-select"), refresh: byId("refresh-button"), json: byId("json-button"),
    retry: byId("retry-button"), home: byId("home-button"), health: byId("health-badge"),
    summary: byId("status-summary"), generated: byId("generated-at"), welcome: byId("welcome-state"),
    content: byId("content-view"), error: byId("error-state"), errorMessage: byId("error-message"),
    title: byId("section-title"), kicker: byId("section-kicker"), sectionSummary: byId("section-summary"),
    metrics: byId("summary-metrics"), primary: byId("primary-content"), viewpoints: byId("viewpoint-nav"),
    layers: byId("layer-nav"), loading: byId("loading-mask"), dialog: byId("evidence-dialog"),
    addProject: byId("add-project-button"), evidenceTitle: byId("evidence-title"),
    evidenceBody: byId("evidence-body"), loadingMessage: byId("loading-message"), main: byId("main-content"),
    mapMode: byId("map-mode-button"), viewMode: byId("view-mode-button")
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
    if (!response.ok) throw new Error(payload.error?.message || `HTTP ${response.status}`);
    return payload;
  }

  function setLoading(active, message = "正在检查项目…") {
    ui.loading.hidden = !active;
    ui.loadingMessage.textContent = message;
    ui.project.disabled = active || state.projects.length === 0;
    ui.refresh.disabled = active || !ui.project.value;
    ui.json.disabled = active || !state.payload;
    ui.addProject.disabled = active;
  }

  function resetRenderedState() {
    state.payload = null;
    state.document = null;
    clear(ui.primary);
    clear(ui.metrics);
    clear(ui.layers);
    clear(ui.viewpoints);
    ui.json.disabled = true;
  }

  function showError(error) {
    resetRenderedState();
    ui.welcome.hidden = true;
    ui.content.hidden = true;
    ui.error.hidden = false;
    ui.errorMessage.textContent = error instanceof Error ? error.message : String(error);
    ui.health.className = "badge fail";
    ui.health.textContent = "ERROR";
    ui.summary.textContent = "本次检查失败，旧项目结果已清除。";
    ui.generated.textContent = "";
  }

  function statusClass(value) {
    const normalized = String(value || "").toUpperCase();
    if (["PASS", "READY", "CONFORMANT", "OBSERVED", "DECLARED"].includes(normalized)) return "pass";
    if (["FAIL", "BLOCKED", "VIOLATION", "INVALID"].includes(normalized)) return "fail";
    return "warn";
  }

  function metric(label, value) {
    const wrap = node("div", null, "metric");
    wrap.append(node("dt", label), node("dd", value));
    return wrap;
  }

  function projectModel() {
    return state.payload?.inspection?.snapshot?.project_model || {};
  }

  function itemsById(ids, source) {
    return (ids || []).map((id) => source?.[id]).filter(Boolean);
  }

  function profileLabel(value) {
    return {
      configured: "已读取项目配置",
      partial: "项目配置部分可用",
      ephemeral: "通用扫描模式",
      invalid: "项目配置不可用"
    }[value] || "通用扫描模式";
  }

  function evidenceButton(ids, label = "证据") {
    const button = node("button", label, "evidence-button");
    button.type = "button";
    button.addEventListener("click", () => openEvidence(ids));
    return button;
  }

  function appendEvidenceRows(ids) {
    const evidence = state.document?.evidence || {};
    const found = itemsById(ids, evidence);
    if (!found.length) {
      ui.evidenceBody.append(node("p", "当前对象没有绑定可展示的证据。", "empty"));
      return;
    }
    found.forEach((item) => {
      const row = node("article", null, "evidence-row");
      const heading = node("div", null, "evidence-heading");
      heading.append(node("strong", item.kind), node("code", item.locator));
      row.append(heading, node("p", item.summary));
      if (item.digest) row.append(node("small", item.digest));
      ui.evidenceBody.append(row);
    });
  }

  function openEvidence(ids) {
    clear(ui.evidenceBody);
    ui.evidenceTitle.textContent = `证据 ${itemsById(ids, state.document?.evidence).length} 条`;
    appendEvidenceRows(ids);
    ui.dialog.showModal();
  }

  function openEntity(entity) {
    clear(ui.evidenceBody);
    ui.evidenceTitle.textContent = entity.name;
    const meta = node("div", null, "detail-meta");
    meta.append(node("span", entity.kind), node("span", entity.status));
    ui.evidenceBody.append(meta, node("p", entity.summary, "detail-summary"));
    const attributes = Object.entries(entity.attributes || {}).filter(([, value]) => value !== null && value !== "");
    if (attributes.length) {
      const list = node("dl", null, "attribute-list");
      attributes.forEach(([key, value]) => {
        list.append(node("dt", key), node("dd", typeof value === "object" ? JSON.stringify(value) : value));
      });
      ui.evidenceBody.append(list);
    }
    appendEvidenceRows(entity.evidence_ids);
    ui.dialog.showModal();
  }

  // 无证据时的解释区块。服务对象是 vibecoding 的学习者, 所以要回答三件事:
  // 这是什么目录 / 为什么 Moth 说不出结构 / 想看到结构该补什么。
  // 刻意**不**猜测项目内容: Moth 只报它真能观察到的东西, 猜出来的架构比空白更有害。
  function emptyProjectExplainer(model) {
    const box = node("section", null, "panel empty-explainer");
    box.append(node("h2", "Moth 目前读不出这个项目的结构"));

    const why = node("p", null, "muted");
    const detectors = ((model.coverage || {}).detectors || [])
      .filter((d) => d.state === "NOT_DETECTED").length;
    why.textContent =
      "这个目录里没有任何项目清单文件(如 pyproject.toml、package.json、requirements.txt)。" +
      "Moth 只根据仓库里真实存在的证据描述项目 —— " + detectors +
      " 个检测器都没找到可依据的清单, 所以它不去猜, 而是如实说读不出来。";
    box.append(why);

    const how = node("div", null, "explainer-how");
    how.append(node("h3", "想让它读出结构, 补一个清单就够"));
    const list = node("ul");
    [
      "Python 脚本: 加一个 requirements.txt 写明依赖, 或 pyproject.toml 写明项目名与入口",
      "前端 / Node: 加 package.json",
      "只是一堆脚本、暂时不想加清单: 那 Moth 对它就只能给出上面「需要关注」里的通用检查"
    ].forEach((line) => list.append(node("li", line)));
    how.append(list);
    box.append(how);

    const note = node("p", null, "muted");
    note.textContent =
      "注: Moth 不会根据文件名或目录结构猜测架构 —— 猜出来的架构看着完整, 但会把人带偏。";
    box.append(note);
    return box;
  }

  // 工具自检折叠条: 默认收起, 只报个数。这些是 Moth 跑得好不好, 不是项目好不好。
  function toolingSelfCheck(items) {
    const box = node("details", null, "tooling-selfcheck");
    const sum = node("summary");
    sum.textContent = `工具自检: ${items.length} 项前置未就绪(与你的项目无关, 点开查看)`;
    box.append(sum);
    items.forEach((f) => box.append(findingRow(f)));
    return box;
  }

  // 首屏一句话: 讲**项目**, 不讲工具。原文案"根据当前仓库代码、清单和项目文档即时生成"
  // 是工具在自我介绍, 对想了解项目的人零信息量。
  // 只拼已观察到的字段, **不新增任何推断** —— 每个断言都能指回 runtimes / applications /
  // modules / architecture, 说不出来的部分就不说。
  const RUNTIME_LABEL = { python: "Python", nodejs: "Node.js", swift: "Swift", java: "Java" };
  const APP_LABEL = {
    python_api: "后端 API", python_console_script: "命令行工具",
    python_web_application: "Python Web 应用", web_application: "前端应用",
    static_web_application: "静态站点"
  };

  function projectOneLiner(model) {
    const parts = [];
    const runtimes = (model.runtimes || []).map((r) => RUNTIME_LABEL[r.id] || r.id);
    if (runtimes.length) parts.push(runtimes.join(" + ") + " 项目");

    const apps = model.applications || [];
    if (apps.length) {
      const kinds = [...new Set(apps.map((a) => APP_LABEL[a.subtype] || a.subtype))];
      parts.push(`${apps.length} 个应用入口(${kinds.join("、")})`);
    }
    const mods = (model.modules || []).length;
    if (mods) parts.push(`${mods} 个模块`);

    // 架构声明状态只在**已经识别出结构**时才提。对一个连清单都没有的目录说
    // "尚未声明目标架构", 会把读者引向错误的下一步(去写架构声明), 而它真正缺的是清单。
    if (parts.length) {
      const arch = model.architecture || {};
      const drift = (arch.drift || {}).state;
      if (arch.declaration_state === "DECLARED") {
        parts.push(drift === "CONFORMANT" ? "架构声明与实际一致" : "架构声明与实际存在差异");
      } else if (arch.declaration_state === "NOT_DECLARED") {
        parts.push("尚未声明目标架构");
      }
    }
    return parts.length ? parts.join(" · ") : "";
  }

  function section(title, items, renderer, options = {}) {
    const wrap = node("section", null, `section ${options.className || ""}`.trim());
    const header = node("div", null, "section-header");
    header.append(node("h2", title), node("span", `${items.length} 项`));
    wrap.append(header);
    if (!items.length) {
      wrap.append(node("p", options.empty || "此视图没有可展示的已验证数据。", "empty"));
      return wrap;
    }
    const content = node("div", null, options.layout || "item-list");
    items.forEach((item) => content.append(renderer(item)));
    wrap.append(content);
    return wrap;
  }

  function entityRow(entity) {
    const row = node("article", null, "entity-row");
    const main = node("div", null, "entity-copy");
    const meta = node("div", null, "row-meta");
    meta.append(node("span", entity.kind), node("span", entity.status));
    main.append(meta, node("h3", entity.name), node("p", entity.summary));
    const button = node("button", "查看", "row-action");
    button.type = "button";
    button.addEventListener("click", () => openEntity(entity));
    row.append(main, button);
    return row;
  }

  function findingRow(finding) {
    const row = node("article", null, "finding-row");
    row.dataset.severity = finding.severity;
    const heading = node("div", null, "finding-heading");
    heading.append(node("h3", finding.title));
    const meta = node("div", null, "row-meta");
    meta.append(node("span", finding.severity), node("span", finding.action_bucket), node("span", finding.confidence));
    heading.append(meta);
    row.append(heading, node("p", finding.why));
    const next = node("p", null, "next-step");
    next.append(node("strong", "下一步 "), document.createTextNode(finding.safest_step));
    row.append(next);
    if (finding.avoid?.length) {
      const avoid = node("p", null, "avoid-note");
      avoid.append(node("strong", "避免 "), document.createTextNode(finding.avoid[0]));
      row.append(avoid);
    }
    if (finding.evidence_ids?.length) row.append(evidenceButton(finding.evidence_ids));
    return row;
  }

  function relationSection(title, relations, doc = state.document) {
    return section(title, relations, (relation) => {
      const row = node("article", null, "relation-row");
      const source = doc.entities[relation.source_id]?.name || relation.source_id;
      const target = doc.entities[relation.target_id]?.name || relation.target_id;
      row.append(node("strong", source), node("span", relation.label), node("strong", target));
      if (relation.evidence_ids?.length) row.append(evidenceButton(relation.evidence_ids));
      return row;
    }, { layout: "relation-list", empty: "当前没有可验证的组件关系。" });
  }

  // ── 架构图 (手写 SVG, 不引外部库) ────────────────────────────────────────
  // 为什么不引 d3/mermaid: 控制台是本地自包含的, CDN 会让它离线不可用, 打包进来又让
  // 仓库膨胀。18 个节点的分层图手写足够。
  // 为什么不用力导向: 每次刷新位置都变, 学习者会以为架构变了。分层是确定性的。
  //
  // **按连通性自适应** —— 实测两个真实项目形状完全不同:
  //   moth        18 实体 / 13 关系(calls 为主) -> 分层图有意义
  //   chunkymonkey 17 实体 / **2 条关系**, 15 个根 -> 画分层图就是一堆孤立点
  // 所以关系过少时不画连线图, 改按 kind 分组展示, 并说明为什么没有连线。
  // 节点宽度按**实际最长名**自适应, 不写死: 实测 moth 的 20 个标签里 12 个被 132px 截断
  // ("Change safety a…"), 图的可读性直接减半 —— 而"看懂组件叫什么"正是学架构的起点。
  const NODE_H = 34, GAP_X = 22, GAP_Y = 58, PAD = 16;
  const NODE_W_MIN = 132, NODE_W_MAX = 240, CHAR_PX = 7.2;
  const KIND_COLOR = {
    application: "#2f6f4f", service: "#3a5a8c", module: "#6b4f8a",
    runtime: "#8a6a2f", framework: "#8a4f4f", platform: "#4f7a8a",
    project: "#444", composition: "#666"
  };

  function assignLayers(nodeIds, relations) {
    // 最长路径分层: 无入边者为第 0 层, 其余取前驱层+1。有环时按已达层数截断。
    const incoming = new Map(nodeIds.map((id) => [id, []]));
    relations.forEach((r) => {
      if (incoming.has(r.target_id) && incoming.has(r.source_id)) {
        incoming.get(r.target_id).push(r.source_id);
      }
    });
    const layer = new Map(nodeIds.map((id) => [id, 0]));
    for (let pass = 0; pass < nodeIds.length; pass += 1) {
      let moved = false;
      nodeIds.forEach((id) => {
        incoming.get(id).forEach((src) => {
          if (layer.get(id) <= layer.get(src)) { layer.set(id, layer.get(src) + 1); moved = true; }
        });
      });
      if (!moved) break;   // 收敛即停; 上限 = 节点数, 保证有环也会终止
    }
    return layer;
  }

  function architectureDiagram(entities, relations) {
    const ids = entities.map((e) => e.id);
    const idSet = new Set(ids);
    const edges = relations.filter((r) => idSet.has(r.source_id) && idSet.has(r.target_id));

    const box = node("div", null, "arch-diagram");
    if (!ids.length) return null;
    // 判据是"关系密度"而非"边数下限": chunkymonkey 有 17 个实体却只有 2 条边,
    // `edges.length < 2` 放它过去, 结果是 15 个孤立方块排成 2342px 宽的一行 ——
    // 那不是架构图, 是一张误导人以为组件互不相关的图。
    // 要求至少有一半节点被关系连上, 才认为图能表达结构。
    const connected = new Set();
    edges.forEach((r) => { connected.add(r.source_id); connected.add(r.target_id); });
    if (edges.length < 2 || connected.size * 2 < ids.length) {
      // 没有足够关系可画 —— 说清楚为什么, 而不是给一张没有连线的图让人以为组件互不相关。
      const hint = node("p", null, "muted");
      hint.textContent =
        `已识别 ${ids.length} 个组件, 其中只有 ${connected.size} 个被关系连接` +
        `(共 ${edges.length} 条关系), 不足以画出能说明结构的图。` +
        "Moth 不会按名称猜测调用关系 —— 关系需要来自代码或声明中的证据。";
      box.append(hint);
      return box;
    }

    // 先按最长名定宽(留 16px 内边距), 夹在 [MIN, MAX] 之间; 超过 MAX 才截断。
    const longest = Math.max(...entities.map((e) => String(e.name || e.id).length));
    const NODE_W = Math.min(NODE_W_MAX, Math.max(NODE_W_MIN, Math.round(longest * CHAR_PX) + 16));
    const maxChars = Math.floor((NODE_W - 16) / CHAR_PX);

    const layer = assignLayers(ids, edges);
    const byLayer = new Map();
    ids.forEach((id) => {
      const l = layer.get(id);
      if (!byLayer.has(l)) byLayer.set(l, []);
      byLayer.get(l).push(id);
    });
    const layers = [...byLayer.keys()].sort((a, b) => a - b);
    const width = PAD * 2 + Math.max(...layers.map((l) => byLayer.get(l).length)) * (NODE_W + GAP_X);
    const height = PAD * 2 + layers.length * GAP_Y + NODE_H;

    const pos = new Map();
    layers.forEach((l, li) => {
      const row = byLayer.get(l);
      const rowW = row.length * (NODE_W + GAP_X) - GAP_X;
      row.forEach((id, i) => {
        pos.set(id, { x: (width - rowW) / 2 + i * (NODE_W + GAP_X), y: PAD + li * GAP_Y });
      });
    });

    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("class", "arch-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `架构图: ${ids.length} 个组件, ${edges.length} 条关系`);

    edges.forEach((r) => {
      const a = pos.get(r.source_id), b = pos.get(r.target_id);
      if (!a || !b) return;
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", a.x + NODE_W / 2); line.setAttribute("y1", a.y + NODE_H);
      line.setAttribute("x2", b.x + NODE_W / 2); line.setAttribute("y2", b.y);
      line.setAttribute("class", "arch-edge");
      const title = document.createElementNS(ns, "title");
      title.textContent = r.label || r.kind || "";
      line.append(title);
      svg.append(line);
    });

    entities.forEach((e) => {
      const p = pos.get(e.id);
      if (!p) return;
      const g = document.createElementNS(ns, "g");
      g.setAttribute("class", "arch-node");
      g.setAttribute("tabindex", "0");
      g.dataset.entityId = e.id;
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", p.x); rect.setAttribute("y", p.y);
      rect.setAttribute("width", NODE_W); rect.setAttribute("height", NODE_H);
      rect.setAttribute("rx", "5");
      rect.setAttribute("fill", KIND_COLOR[e.kind] || "#555");
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", p.x + NODE_W / 2); label.setAttribute("y", p.y + NODE_H / 2 + 4);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "arch-label");
      const name = String(e.name || e.id);
      label.textContent = name.length > maxChars ? name.slice(0, maxChars - 1) + "…" : name;
      const title = document.createElementNS(ns, "title");
      title.textContent = `${e.name || e.id}\n${e.kind || ""}\n${e.responsibility || ""}`;
      // 点节点 -> 复用既有的实体详情抽屉(kind / 职责 / 属性 / 证据)。
      // 这是"图上看见"到"知道在哪个文件"的桥 —— 没有它, 图停在好看但学不到。
      // 不另造面板: openEntity 已经在做同一件事, 多一个面板就是多一份会漂的实现。
      // e 就是 doc.entities 里那个对象(itemsById 直接取的引用), 不再二次查表:
      // 多一次查表就多一条"查不到就静默什么都不做"的分支。
      g.addEventListener("click", () => openEntity(e));
      g.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openEntity(e); }
      });
      g.append(rect, label, title);
      svg.append(g);
    });

    box.append(svg);
    return box;
  }

  function architectureBlock() {
    const architecture = state.document.architecture;
    const summary = architecture.summary;
    const wrap = node("section", null, "section architecture-section");
    const header = node("div", null, "section-header");
    const stateBadge = node("span", summary.state, `text-status ${statusClass(summary.state)}`);
    header.append(node("h2", "系统架构"), stateBadge);
    wrap.append(header);
    const states = node("div", null, "architecture-grid");
    [
      ["当前结构", architecture.as_is, `${architecture.as_is.entity_ids.length} 个对象，${architecture.as_is.relation_ids.length} 条关系`],
      ["目标结构", architecture.to_be, architecture.to_be.state === "DECLARED" ? `${architecture.to_be.entity_ids.length} 个对象` : "项目尚未声明 To-Be"],
      ["一致性", summary, `${summary.counts.CONFORMANT} 符合 · ${summary.counts.VIOLATION} 冲突 · ${summary.counts.UNVERIFIABLE} 未验证`]
    ].forEach(([label, value, description]) => {
      const item = node("article", null, "architecture-state");
      item.append(node("small", label), node("strong", value.state), node("p", description));
      if (value.evidence_ids?.length) item.append(evidenceButton(value.evidence_ids));
      states.append(item);
    });
    wrap.append(states);

    // 图放在状态卡之后: 先给结论(是否一致), 再给结构。
    const doc = state.document;
    const ents = itemsById(architecture.as_is.entity_ids, doc.entities);
    const rels = itemsById(architecture.as_is.relation_ids, doc.relations);
    const diagram = architectureDiagram(ents, rels);
    if (diagram) wrap.append(diagram);
    return wrap;
  }

  function flowRow(entity) {
    const row = node("article", null, "flow-row");
    const steps = Object.values(state.document.relations).filter(
      (relation) => relation.kind === "flow_step" && relation.source_id === entity.id
    );
    row.append(node("h3", entity.name), node("p", entity.summary));
    if (steps.length) {
      const list = node("ol", null, "flow-steps");
      steps.forEach((step) => {
        const target = state.document.entities[step.target_id]?.name || step.target_id;
        list.append(node("li", `${step.label} · ${target}`));
      });
      row.append(list);
    }
    row.append(evidenceButton(entity.evidence_ids));
    return row;
  }

  function activateNavigation(active) {
    [ui.home, ...ui.layers.querySelectorAll("button"), ...ui.viewpoints.querySelectorAll("button")]
      .forEach((button) => button.classList.toggle("active", button.dataset.nav === active || (active === "home" && button === ui.home)));
  }

  function setNavigationMode(mode) {
    state.navigationMode = mode;
    const map = mode === "map";
    ui.layers.hidden = !map;
    ui.viewpoints.hidden = map;
    ui.mapMode.setAttribute("aria-selected", String(map));
    ui.viewMode.setAttribute("aria-selected", String(!map));
  }

  function renderHome() {
    const doc = state.document;
    const model = projectModel();
    activateNavigation("home");
    ui.kicker.textContent = profileLabel(state.payload.project.profile_state);
    ui.title.textContent = state.payload.project.name;
    ui.sectionSummary.textContent =
      projectOneLiner(model) || doc.identity.description ||
      "这个目录里没有可识别的项目结构 —— 详见下方说明。";
    clear(ui.primary);

    const applications = itemsById((model.applications || []).map((item) => item.id), doc.entities);
    const modules = itemsById(
      (model.modules || []).filter((item) => item.kind !== "technology").map((item) => item.id),
      doc.entities
    );
    const technologies = itemsById(
      [
        ...(model.runtimes || []).map((item) => item.id),
        ...(model.modules || []).filter((item) => item.kind === "technology").map((item) => item.id)
      ],
      doc.entities
    );
    const flowIds = [
      ...(model.flows || []).map((item) => item.id),
      ...(model.state_machines || []).map((item) => item.id)
    ];
    const flows = itemsById(flowIds, doc.entities);
    const documents = Object.values(doc.entities).filter((item) => item.kind === "project_document");
    const relations = itemsById(doc.architecture.as_is.relation_ids, doc.relations);
    const priorities = itemsById(doc.home.priority_finding_ids, doc.findings);

    clear(ui.metrics);
    // 四个计数器只在**至少有一项非零**时才显示。全 0 时它们没有任何信息量, 却是
    // 页面上最醒目的元素 —— 用户实测反馈: "关键数据全是空白", 而真正的答案
    // (没有清单所以读不出) 被这四个 0 压在下面。

    // 本工具服务 vibecoding 的人: 用来**学架构、看问题**。据此排序内容, 而不是
    // 无条件铺满六个区块 —— 实测一个只有脚本没有清单的目录, 页面渲染出四个大 0 和
    // 六个"尚未识别出…", 而唯一能动手的「当前需要关注」被压在最底部。
    const hasStructure =
      applications.length || modules.length || technologies.length ||
      flows.length || relations.length || documents.length;

    // 问题永远排在最前: 它是"看问题"这一半用途的全部载体, 且是空项目里唯一有内容的东西。
    if (hasStructure) {
      ui.metrics.append(
        metric("应用", applications.length),
        metric("模块", modules.length),
        metric("技术", technologies.length),
        metric("流程", flows.length)
      );
    }

    // 按 origin 分流: 项目问题是主角, 工具内务收进折叠条。
    // 实测暑假古诗 8 条里 5 条是 codegraph/baseline/safe-view 未就绪 —— 那是 Moth
    // 自己的前置条件, 学习者既看不懂也不该关心, 混在一起会把 3 条真问题挤没。
    const projectFindings = priorities.filter((f) => f.origin !== "tooling");
    const toolingFindings = priorities.filter((f) => f.origin === "tooling");

    if (projectFindings.length) {
      ui.primary.append(section("当前需要关注", projectFindings, findingRow, {}));
    }
    if (toolingFindings.length) {
      ui.primary.append(toolingSelfCheck(toolingFindings));
    }

    if (!hasStructure) {
      // 无证据时不铺空壳: 直接讲清"为什么什么都没有"和"要看到东西需要补什么",
      // 这对学习者才有用。诚实地报 0 但不解释, 等于给一堵白墙。
      ui.primary.append(emptyProjectExplainer(model));
      return;
    }

    ui.primary.append(section("应用入口", applications, entityRow, {
      empty: "尚未从项目清单或入口文件识别出应用。"
    }));
    ui.primary.append(architectureBlock());
    if (relations.length) ui.primary.append(relationSection("组件关系", relations));

    const split = node("div", null, "section-split");
    if (modules.length) split.append(section("核心模块", modules, entityRow, {}));
    if (technologies.length) split.append(section("技术栈", technologies, entityRow, {}));
    if (split.children.length) ui.primary.append(split);

    const learning = node("div", null, "section-split");
    if (flows.length) learning.append(section("业务与系统流程", flows, flowRow, {}));
    if (documents.length) learning.append(section("项目文档", documents, entityRow, {}));
    if (learning.children.length) ui.primary.append(learning);
  }

  function renderLayer(layerId) {
    const doc = state.document;
    const layer = doc.layers.find((item) => item.id === layerId);
    if (!layer) return;
    activateNavigation(layerId);
    ui.kicker.textContent = "项目地图";
    ui.title.textContent = layer.label;
    ui.sectionSummary.textContent = layer.summary;
    clear(ui.primary);
    clear(ui.metrics);

    const findings = itemsById(layer.finding_ids, doc.findings);
    const entities = itemsById(layer.entity_ids, doc.entities);
    const relations = itemsById(layer.relation_ids, doc.relations);
    ui.metrics.append(metric("对象", entities.length), metric("关系", relations.length), metric("问题", findings.length));

    if (layerId === "architecture") ui.primary.append(architectureBlock());
    if (layerId === "flows") {
      ui.primary.append(section("已验证流程", entities, flowRow, {
        empty: "项目尚未声明可验证流程。"
      }));
    } else {
      ui.primary.append(section(layerId === "evidence" ? "证据入口" : "组成对象", entities, entityRow));
    }
    if (relations.length || layerId === "architecture") ui.primary.append(relationSection("关系", relations));
    ui.primary.append(section("需要关注", findings, findingRow, { empty: "此层没有需要关注的问题。" }));
  }

  function renderViewpoint(viewpoint) {
    const doc = state.document;
    const descriptions = {
      product: "项目向用户提供什么，以及哪些产品事实仍缺少证据。",
      system: "系统由哪些对象组成，它们如何连接并承担职责。",
      risk: "哪些已验证问题会影响当前判断和下一步行动。"
    };
    activateNavigation(viewpoint.id);
    ui.kicker.textContent = "工作视角";
    ui.title.textContent = viewpoint.label;
    ui.sectionSummary.textContent = descriptions[viewpoint.id] || "从同一份项目证据切换观察角度。";
    clear(ui.primary);
    clear(ui.metrics);
    const entities = itemsById(viewpoint.entity_ids, doc.entities);
    const relations = itemsById(viewpoint.relation_ids, doc.relations);
    const findings = itemsById(viewpoint.finding_ids, doc.findings);
    ui.metrics.append(metric("对象", entities.length), metric("关系", relations.length), metric("问题", findings.length));
    ui.primary.append(
      section("观察对象", entities, entityRow),
      relationSection("关联关系", relations),
      section("需要关注", findings, findingRow, { empty: "该视角没有重复或独立问题。" })
    );
  }

  function buildNavigation(doc) {
    clear(ui.viewpoints);
    clear(ui.layers);
    ui.home.dataset.nav = "home";
    (doc.navigation.layers || []).filter((item) => item.id !== "overview").forEach((item) => {
      const button = node("button", item.label);
      button.type = "button";
      button.dataset.nav = item.id;
      button.addEventListener("click", () => {
        setNavigationMode("map");
        renderLayer(item.id);
      });
      ui.layers.append(button);
    });
    (doc.navigation.viewpoints || []).forEach((viewpoint) => {
      const button = node("button", viewpoint.label);
      button.type = "button";
      button.dataset.nav = viewpoint.id;
      button.addEventListener("click", () => {
        setNavigationMode("view");
        renderViewpoint(viewpoint);
      });
      ui.viewpoints.append(button);
    });
    setNavigationMode(state.navigationMode);
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
    ui.summary.textContent = `${doc.status.label} · ${profileLabel(payload.project.profile_state)}`;
    ui.generated.textContent = doc.source.generated_at
      ? `更新于 ${new Date(doc.source.generated_at).toLocaleString()}`
      : "";
    buildNavigation(doc);
    renderHome();
    ui.json.disabled = false;
    ui.main.focus();
  }

  async function inspectProject() {
    if (!ui.project.value) return;
    if (state.controller) state.controller.abort();
    const controller = new AbortController();
    state.controller = controller;
    setLoading(true);
    try {
      const payload = await api("/api/v1/inspections", {
        method: "POST",
        signal: controller.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: ui.project.value })
      });
      if (state.controller === controller) renderPayload(payload);
    } catch (error) {
      if (error.name !== "AbortError" && state.controller === controller) showError(error);
    } finally {
      if (state.controller === controller) {
        state.controller = null;
        setLoading(false);
      }
    }
  }

  async function loadProjects(selectedId = "") {
    const registry = await api("/api/v1/projects");
    state.projects = registry.projects || [];
    ui.addProject.hidden = registry.capabilities?.project_selection !== true;
    clear(ui.project);
    state.projects.forEach((project) => {
      const option = node("option", project.name);
      option.value = project.id;
      option.title = profileLabel(project.profile_state);
      ui.project.append(option);
    });
    const preferred = state.projects.find((project) => project.id === selectedId);
    if (preferred) ui.project.value = preferred.id;
    ui.project.disabled = state.projects.length === 0;
    ui.refresh.disabled = !ui.project.value;
    return state.projects.length;
  }

  async function addProject() {
    setLoading(true, "正在等待选择项目目录…");
    try {
      const result = await api("/api/v1/projects/select", { method: "POST" });
      if (!result.selected) return;
      await loadProjects(result.project?.id || "");
      await inspectProject();
    } catch (error) {
      showError(error);
    } finally {
      if (!state.controller) setLoading(false);
    }
  }

  async function initialize() {
    state.token = readToken();
    if (!state.token) {
      showError(new Error("缺少本次服务的 capability token。请使用 Moth 输出的完整地址。"));
      return;
    }
    try {
      if (!await loadProjects()) throw new Error("配置中没有可选择的项目。");
      await inspectProject();
    } catch (error) {
      showError(error);
      setLoading(false);
    }
  }

  ui.project.addEventListener("change", inspectProject);
  ui.addProject.addEventListener("click", addProject);
  ui.refresh.addEventListener("click", inspectProject);
  ui.retry.addEventListener("click", inspectProject);
  ui.home.addEventListener("click", renderHome);
  ui.mapMode.addEventListener("click", () => setNavigationMode("map"));
  ui.viewMode.addEventListener("click", () => setNavigationMode("view"));
  ui.json.addEventListener("click", () => {
    if (!state.payload) return;
    const blob = new Blob([JSON.stringify(state.payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  });
  initialize();
})();
