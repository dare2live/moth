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

  // 术语表。屏幕上这些大写词是模型的词汇表, 不是常识 —— 看的人不该去别处查字典。
  // 只解释**模型真的会发出**的值(取自视觉文档 schema 的枚举与 visual_model 里的字面量);
  // 表里没有的词一律不解释: 编一个说法比留着原词更糟。
  // tests/test_web_console.py 会拿 schema 对着这张表点名, 加了新状态而没写解释会报红。
  const TERMS = {
    // 措辞按 2026-08-17 的实测改过: 此前写"从仓库里实际看到的结构", 而实测本仓 18 个对象里
    // 15 个只存在于 .moth/architecture.yaml —— 那句话把"读来的"说成了"看到的"。
    OBSERVED: "至少有一部分是扫描出来的 —— 具体几个看下面的来源拆分",
    DECLARED_ONLY: "全部来自项目手写的声明文件, 没有一个是扫描出来的",
    DECLARED: "项目自己写下的目标结构",
    NOT_DECLARED: "还没写下目标结构 —— 不是错, 是没声明",
    NOT_OBSERVED: "既没扫到, 也没声明",
    PARTIAL: "只覆盖了一部分, 其余没查到",
    CONFORMANT: "写下的和看到的一致",
    DETECTED: "扫描代码或清单文件读出来的",
    CONFIRMED: "声明里写了, 扫描也独立看到了",
    VIOLATION: "写下的和看到的对不上",
    UNVERIFIABLE: "证据不够, 判不了一致与否",
    CONFIRMED_BY_IMPORT: "这条关系不仅声明了, 还被 import 图独立验证到",
    NOT_VERIFIABLE: "关系不在 import 图能验证的范围内（跨语言/非 Python/图未配置等）, 判不出有没有被代码证实",
    AVAILABLE: "这项检查跑过了",
    NOT_CHECKED: "这项没查 —— 不等于没问题",
    TOOL_UNAVAILABLE: "所需工具不在, 这项无从查起",
    EXPECTED_REQUIRED: "目标结构要求有这个",
    EXPECTED_FORBIDDEN: "目标结构要求没有这个",
    UNKNOWN: "查不出来, 没有替它猜一个"
  };

  function termHint(value) {
    return TERMS[String(value || "").toUpperCase()] || "";
  }

  /** 给一个术语挂上大白话: 有解释才加提示与虚线, 没有就原样留着。 */
  function withTerm(element, value) {
    const hint = termHint(value);
    if (hint) {
      element.title = `${value} — ${hint}`;
      element.classList.add("term");
    }
    return element;
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
    meta.append(node("span", entity.kind), withTerm(node("span", entity.status), entity.status));
    // 抽屉是"来这儿看明白"的地方, 大白话直接写出来, 不留给 hover。
    const statusPlain = termHint(entity.status);
    if (statusPlain) meta.append(node("span", statusPlain, "term-plain"));
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
    meta.append(node("span", entity.kind), withTerm(node("span", entity.status), entity.status));
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
  // 节点两行(名字 + 定位), 高度得跟着两行文字调 —— 34px 只够放一行。
  const NODE_H = 44, GAP_X = 22, GAP_Y = 64, PAD = 16, SUB_LABEL_DY = 15;
  const NODE_W_MIN = 132, NODE_W_MAX = 240, CHAR_PX = 7.2;
  // diagram_policy 缺失(旧文档)时的兜底 —— 数值来自 visual_policy.yaml 当前的默认值。
  const DEFAULT_SPARSE_RULE = { min_edges: 2, min_connected_ratio: 0.5 };

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

  function diagramPolicy() {
    return state.document?.diagram_policy || null;
  }

  // 稀疏判据的两个数从 diagram_policy.sparse_rule 读, 不再硬编码 —— 这两个数
  // 是"这张图还算不算得上在表达结构"的判据, 项目应该能按自己的连接密度调它。
  // diagram_policy 是可选字段(旧文档可能没有), 缺失时退回脚本原来的默认值。
  function sparseRule() {
    const raw = diagramPolicy()?.sparse_rule || {};
    return {
      min_edges: typeof raw.min_edges === "number" ? raw.min_edges : DEFAULT_SPARSE_RULE.min_edges,
      min_connected_ratio: typeof raw.min_connected_ratio === "number"
        ? raw.min_connected_ratio
        : DEFAULT_SPARSE_RULE.min_connected_ratio
    };
  }

  // provenance -> 线型(solid/dashed) 的映射来自 diagram_policy.provenance_legend,
  // 不在这里硬编码 —— "证实到什么程度才画实线"是 policy 的判断, 不是前端的判断。
  function provenanceLineStyles(policy) {
    const map = {};
    (policy?.provenance_legend || []).forEach((item) => {
      if (item && item.id) map[item.id] = item.line === "dashed" ? "dashed" : "solid";
    });
    return map;
  }

  function basename(path) {
    const parts = String(path || "").split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : String(path || "");
  }

  // N3: verification.reason -> 大白话的映射来自 diagram_policy.verification_reason_labels,
  // 不在这里硬编码中文文案。reason 可能带一个用 "; " 拼接的动态导入标记后缀
  // (architecture_model._dynamic_import_marker 加的), 只用分号前的主码去查表 ——
  // 查不到就显式标"未登记原因", 不静默吞掉、也不编一个像的(与 kindReading 的
  // "未登记读法"同一套规矩)。
  function verificationReasonText(policy, reason) {
    const raw = String(reason || "").trim();
    const code = raw.split(";")[0].trim();
    const map = new Map((policy?.verification_reason_labels || []).map((item) => [item.id, item.label]));
    return map.get(code) || `未登记原因: ${code || raw || "unknown"}`;
  }

  function locationText(locations) {
    const list = (locations || []).filter((item) => item && item.path && item.line);
    if (!list.length) return "";
    return list.map((item) => `${item.path}:${item.line}`).join(", ");
  }

  // 边的 hover 提示在原有 label 基础上追加"来源 + 证据": 来源文案取自
  // diagram_policy.provenance_legend(与图例同一份数据, 不重编一份)。
  // CONFIRMED/DETECTED 且带 verification.locations 时附代码坐标(path:line);
  // DECLARED 没有坐标, 只能附 verification.reason 翻成的大白话说明"为什么没有"。
  // relation.source 查不到时(既有行为)整句都不追加, 不猜一个来源出来。
  function edgeProvenanceSuffix(relation, policy) {
    const source = relation.source;
    if (!source) return "";
    const legend = new Map((policy?.provenance_legend || []).map((item) => [item.id, item.label]));
    const sourceLabel = legend.get(source);
    if (!sourceLabel) return "";
    const verification = relation.verification;
    if (verification && (source === "CONFIRMED" || source === "DETECTED")) {
      const loc = locationText(verification.locations);
      if (loc) return `${sourceLabel} · ${loc}`;
    }
    if (verification && source === "DECLARED" && verification.reason) {
      return `${sourceLabel} · ${verificationReasonText(policy, verification.reason)}`;
    }
    return sourceLabel;
  }

  // 节点第二行: 回答"改这个组件该动哪个文件"。locator 优先(most entities);
  // 没有 locator 但有 entrypoint 的(如 python_console_script)退到 entrypoint;
  // 两者都没有就不画第二行 —— 不编一个出来。
  function nodeLocatorLabel(entity) {
    const attrs = entity.attributes || {};
    if (attrs.locator) return basename(attrs.locator);
    if (attrs.entrypoint) return String(attrs.entrypoint);
    return "";
  }

  // 图头一行: 组件数 / 关系数 / 箭头怎么读, 外加 policy 给的坐标轴免责声明 ——
  // 没有这句, 纵向位置会被读成调用层级、架构分层或启动顺序, 而它只是最长路径。
  function architectureMeta(ids, edges, policy, asIs) {
    const meta = node("div", null, "arch-meta");
    const axisNote = policy?.axis_note || "";
    const headline = node("p");
    headline.textContent =
      `${ids.length} 个组件 · ${edges.length} 条关系 · 箭头 = 关系方向（读法见图例）` +
      (axisNote ? ` ${axisNote}` : "");
    meta.append(headline);
    // complete 键**不存在**是"项目没声明", 不是 false —— 只有显式声明为 false
    // 才提醒"画出来的不是全部", 用 hasOwnProperty 把两种情况分开, 不能用 `!asIs.complete` 判断。
    if (asIs && Object.prototype.hasOwnProperty.call(asIs, "complete") && asIs.complete === false) {
      meta.append(node(
        "p",
        "这份架构声明自称不完整（complete: false），未画出的组件不等于不存在",
        "arch-meta-note"
      ));
    }
    return meta;
  }

  // 图例只列**这张图上真的有的**: provenance 来源和 relation kind 都从边集里现算,
  // 不遍历 policy 的全量表 —— 全量表里的东西这张图不一定出现过, 遍历全量表就是
  // 在编"读法", 而不是在报告"这张图实际用到了什么"。
  function architectureLegend(edges, policy) {
    const legend = node("div", null, "arch-legend");
    const provenanceUsed = new Set(edges.map((r) => r.source).filter(Boolean));
    const provenanceItems = (policy?.provenance_legend || []).filter((item) => provenanceUsed.has(item.id));
    const kindsUsed = [...new Set(edges.map((r) => r.kind).filter(Boolean))];
    const kindReading = new Map((policy?.kind_reading || []).map((item) => [item.id, item.label]));

    if (provenanceItems.length) {
      const group = node("div", null, "arch-legend-group");
      group.append(node("h3", "来源"));
      const list = node("ul");
      provenanceItems.forEach((item) => {
        const li = node("li");
        li.append(node("span", null, `legend-swatch ${item.line === "dashed" ? "dashed" : "solid"}`));
        li.append(node("span", `${item.id} — ${item.label}`));
        list.append(li);
      });
      group.append(list);
      legend.append(group);
    }

    if (kindsUsed.length) {
      const group = node("div", null, "arch-legend-group");
      group.append(node("h3", "关系读法"));
      const list = node("ul");
      kindsUsed.forEach((kind) => {
        const li = node("li");
        li.append(node("span", kind, "legend-kind"));
        // kind_reading 里找不到这个 kind 时, 显式说"未登记读法" —— 不静默跳过
        // (跳过=读的人以为没有这类关系), 也不编一个读法(编的比没有更误导)。
        li.append(node("span", kindReading.get(kind) || "未登记读法"));
        list.append(li);
      });
      group.append(list);
      legend.append(group);
    }

    return legend.children.length ? legend : null;
  }

  // 图下锚点句: business_flow / state_machine 不画进架构图(它们是执行顺序记录,
  // 不是组件), 但看的人得有路子找到它们, 不然这张图会显得"漏画了"。
  // 数量从 doc.entities 现数, 不写死 —— 写死的数字会在数据变了以后悄悄撒谎。
  function architectureFlowNote(doc) {
    const count = Object.values(doc.entities).filter(
      (e) => e.kind === "business_flow" || e.kind === "state_machine"
    ).length;
    if (!count) return null;
    const p = node("p", null, "arch-flow-note");
    p.append(document.createTextNode(
      `此图不包含业务流程与状态机（共 ${count} 个）—— 它们是执行顺序, 不是架构组件。`
    ));
    const link = node("button", "查看「模块与流程」", "link-button");
    link.type = "button";
    link.addEventListener("click", () => {
      setNavigationMode("map");
      renderLayer("flows");
    });
    p.append(link);
    return p;
  }

  function architectureDiagram(entities, relations, asIs) {
    const ids = entities.map((e) => e.id);
    const idSet = new Set(ids);
    const edges = relations.filter((r) => idSet.has(r.source_id) && idSet.has(r.target_id));

    const wrap = node("div", null, "arch-diagram");
    if (!ids.length) return null;
    // 判据是"关系密度"而非"边数下限": chunkymonkey 有 17 个实体却只有 2 条边,
    // `edges.length < 2` 放它过去, 结果是 15 个孤立方块排成 2342px 宽的一行 ——
    // 那不是架构图, 是一张误导人以为组件互不相关的图。两个阈值从
    // diagram_policy.sparse_rule 读, 缺失时兜底 2 条边 / 一半节点连通。
    const connected = new Set();
    edges.forEach((r) => { connected.add(r.source_id); connected.add(r.target_id); });
    const policy = diagramPolicy();
    const rule = sparseRule();
    if (edges.length < rule.min_edges || connected.size < ids.length * rule.min_connected_ratio) {
      // 没有足够关系可画 —— 说清楚为什么, 而不是给一张没有连线的图让人以为组件互不相关。
      const hint = node("p", null, "muted");
      hint.textContent =
        `已识别 ${ids.length} 个组件, 其中只有 ${connected.size} 个被关系连接` +
        `(共 ${edges.length} 条关系), 不足以画出能说明结构的图。` +
        "Moth 不会按名称猜测调用关系 —— 关系需要来自代码或声明中的证据。";
      wrap.append(hint);
      return wrap;
    }

    wrap.append(architectureMeta(ids, edges, policy, asIs));

    // 先按最长名定宽(留 16px 内边距), 夹在 [MIN, MAX] 之间; 超过 MAX 才截断。
    const longest = Math.max(...entities.map((e) => String(e.name || e.id).length));
    const NODE_W = Math.min(NODE_W_MAX, Math.max(NODE_W_MIN, Math.round(longest * CHAR_PX) + 16));
    const maxChars = Math.floor((NODE_W - 16) / CHAR_PX);
    const truncate = (text) => (text.length > maxChars ? text.slice(0, maxChars - 1) + "…" : text);

    // 零边节点单独成区, 不混进第 0 层 —— 混进去会被读成"入口组件", 而它们只是
    // "没有已知关系", 两件事不能共用同一个视觉位置。
    const connectedIds = ids.filter((id) => connected.has(id));
    const unconnectedIds = ids.filter((id) => !connected.has(id));

    const layer = assignLayers(connectedIds, edges);
    const byLayer = new Map();
    connectedIds.forEach((id) => {
      const l = layer.get(id);
      if (!byLayer.has(l)) byLayer.set(l, []);
      byLayer.get(l).push(id);
    });
    const layers = [...byLayer.keys()].sort((a, b) => a - b);
    const layerCols = layers.length ? Math.max(...layers.map((l) => byLayer.get(l).length)) : 0;
    const unconnectedCols = unconnectedIds.length
      ? Math.max(Math.ceil(Math.sqrt(unconnectedIds.length)), layerCols, 1)
      : 0;
    const unconnectedRows = unconnectedIds.length ? Math.ceil(unconnectedIds.length / unconnectedCols) : 0;
    const cols = Math.max(layerCols, unconnectedCols, 1);
    const width = PAD * 2 + cols * (NODE_W + GAP_X);

    const pos = new Map();
    layers.forEach((l, li) => {
      const row = byLayer.get(l);
      const rowW = row.length * (NODE_W + GAP_X) - GAP_X;
      row.forEach((id, i) => {
        pos.set(id, { x: (width - rowW) / 2 + i * (NODE_W + GAP_X), y: PAD + li * GAP_Y });
      });
    });
    const mainBottom = layers.length ? PAD + (layers.length - 1) * GAP_Y + NODE_H : PAD;

    // 未连接区: 画在主分层图下方独立的一块, 带一句 unconnected_note 说明
    // "为什么这些节点没有连线", 不是图没画完。
    const SECTION_GAP = 36, HEADING_OFFSET = 20;
    let headingY = null;
    if (unconnectedIds.length) {
      headingY = mainBottom + SECTION_GAP;
      const gridTop = headingY + HEADING_OFFSET;
      const rowW = unconnectedCols * (NODE_W + GAP_X) - GAP_X;
      unconnectedIds.forEach((id, i) => {
        const r = Math.floor(i / unconnectedCols);
        const c = i % unconnectedCols;
        pos.set(id, { x: (width - rowW) / 2 + c * (NODE_W + GAP_X), y: gridTop + r * GAP_Y });
      });
    }
    const height =
      (unconnectedIds.length
        ? headingY + HEADING_OFFSET + (unconnectedRows - 1) * GAP_Y + NODE_H
        : mainBottom) + PAD;

    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("width", String(width));
    svg.setAttribute("height", String(height));
    svg.setAttribute("class", "arch-svg");
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", `架构图: ${ids.length} 个组件, ${edges.length} 条关系`);

    // 两个箭头: 实心配实线(CONFIRMED/DETECTED, 或来源不明的中性关系),
    // 空心配虚线(DECLARED) —— 线型由 provenanceLineStyles(policy) 决定,
    // marker 只是跟着线型走的视觉后缀, 不重复判断一次。
    const defs = document.createElementNS(ns, "defs");
    const solidMarker = document.createElementNS(ns, "marker");
    solidMarker.setAttribute("id", "arch-arrow-solid");
    solidMarker.setAttribute("markerWidth", "8");
    solidMarker.setAttribute("markerHeight", "8");
    solidMarker.setAttribute("refX", "7");
    solidMarker.setAttribute("refY", "4");
    solidMarker.setAttribute("orient", "auto");
    const solidPath = document.createElementNS(ns, "path");
    solidPath.setAttribute("d", "M0,0 L8,4 L0,8 Z");
    solidPath.setAttribute("class", "arch-arrow-fill");
    solidMarker.append(solidPath);

    const hollowMarker = document.createElementNS(ns, "marker");
    hollowMarker.setAttribute("id", "arch-arrow-hollow");
    hollowMarker.setAttribute("markerWidth", "9");
    hollowMarker.setAttribute("markerHeight", "9");
    hollowMarker.setAttribute("refX", "8");
    hollowMarker.setAttribute("refY", "4.5");
    hollowMarker.setAttribute("orient", "auto");
    const hollowPath = document.createElementNS(ns, "path");
    hollowPath.setAttribute("d", "M0.5,0.5 L8.5,4.5 L0.5,8.5 Z");
    hollowPath.setAttribute("class", "arch-arrow-hollow-shape");
    hollowMarker.append(hollowPath);

    defs.append(solidMarker, hollowMarker);
    svg.append(defs);

    // 箭头方向恒为 source_id -> target_id: 线从 source 底边画到 target 顶边,
    // marker-end 画在 target 这一端, 不新增/推断任何 direction 字段。
    const lineStyles = provenanceLineStyles(policy);
    edges.forEach((r) => {
      const a = pos.get(r.source_id), b = pos.get(r.target_id);
      if (!a || !b) return;
      const line = document.createElementNS(ns, "line");
      line.setAttribute("x1", a.x + NODE_W / 2); line.setAttribute("y1", a.y + NODE_H);
      line.setAttribute("x2", b.x + NODE_W / 2); line.setAttribute("y2", b.y);
      // 线型只认 relation.source: 没有这个字段的关系按中性(细实线/无 dash)处理,
      // 不当成 DECLARED —— "不知道来源"和"只来自声明"是两件不同的事。
      const style = r.source ? (lineStyles[r.source] || "solid") : "solid";
      line.setAttribute("class", `arch-edge${style === "dashed" ? " dashed" : ""}`);
      line.setAttribute("marker-end", `url(#${style === "dashed" ? "arch-arrow-hollow" : "arch-arrow-solid"})`);
      const title = document.createElementNS(ns, "title");
      const base = r.label || r.kind || "";
      // N3: hover 提示在关系读法基础上追加"来源 + 证据" —— 这是"图上看见"到
      // "由哪一行代码证实"的桥, 不新起一个面板。
      const suffix = edgeProvenanceSuffix(r, policy);
      title.textContent = suffix ? `${base}\n${suffix}` : base;
      line.append(title);
      svg.append(line);
    });

    const entityById = new Map(entities.map((e) => [e.id, e]));
    [...connectedIds, ...unconnectedIds].forEach((id) => {
      const e = entityById.get(id);
      const p = pos.get(id);
      if (!e || !p) return;
      const g = document.createElementNS(ns, "g");
      g.setAttribute("class", "arch-node");
      g.setAttribute("tabindex", "0");
      g.dataset.entityId = e.id;
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", p.x); rect.setAttribute("y", p.y);
      rect.setAttribute("width", NODE_W); rect.setAttribute("height", NODE_H);
      rect.setAttribute("rx", "5");
      const sub = nodeLocatorLabel(e);
      const label = document.createElementNS(ns, "text");
      label.setAttribute("x", p.x + NODE_W / 2);
      label.setAttribute("y", p.y + (sub ? NODE_H / 2 - 3 : NODE_H / 2 + 4));
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("class", "arch-label");
      label.textContent = truncate(String(e.name || e.id));
      g.append(rect, label);
      // 第二行: 改这个组件该动哪个文件 —— locator 的 basename, 没有 locator
      // 就退到 entrypoint; 两者都没有(nodeLocatorLabel 返回空串)就不画这一行。
      if (sub) {
        const subLabel = document.createElementNS(ns, "text");
        subLabel.setAttribute("x", p.x + NODE_W / 2);
        subLabel.setAttribute("y", p.y + NODE_H / 2 + SUB_LABEL_DY);
        subLabel.setAttribute("text-anchor", "middle");
        subLabel.setAttribute("class", "arch-sub-label");
        subLabel.textContent = truncate(sub);
        g.append(subLabel);
      }
      const title = document.createElementNS(ns, "title");
      title.textContent = `${e.name || e.id}\n${e.kind || ""}\n${e.responsibility || ""}`;
      g.append(title);
      // 点节点 -> 复用既有的实体详情抽屉(kind / 职责 / 属性 / 证据)。
      // 这是"图上看见"到"知道在哪个文件"的桥 —— 没有它, 图停在好看但学不到。
      // 不另造面板: openEntity 已经在做同一件事, 多一个面板就是多一份会漂的实现。
      g.addEventListener("click", () => openEntity(e));
      g.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openEntity(e); }
      });
      svg.append(g);
    });

    if (unconnectedIds.length) {
      const heading = document.createElementNS(ns, "text");
      heading.setAttribute("x", PAD);
      heading.setAttribute("y", headingY);
      heading.setAttribute("class", "arch-unconnected-label");
      heading.textContent = `未连接组件 —— ${policy?.unconnected_note || "没有任何已知关系"}`;
      svg.append(heading);
    }

    // 只有 svg 本身包在横向滚动容器里 —— 图例和 meta 行留在外面, 滚动查看
    // 宽图时它们不会跟着滚出视野。
    const scroller = node("div", null, "arch-diagram-scroll");
    scroller.append(svg);
    wrap.append(scroller);

    const legend = architectureLegend(edges, policy);
    if (legend) wrap.append(legend);
    return wrap;
  }

  // "当前结构"这张卡最容易骗人: 它可以是一份人手写的 yaml, 却读起来像扫描结果。
  // 所以对象数后面必须跟上来源拆分 —— 有几个是真扫到的, 有几个只是被声明过。
  function provenanceLine(asIs) {
    const counts = asIs.entity_ids.length + asIs.relation_ids.length;
    const base = `${asIs.entity_ids.length} 个对象，${asIs.relation_ids.length} 条关系`;
    const p = asIs.provenance;
    if (!p || !counts) return base;
    const parts = [];
    if (p.detected) parts.push(`${p.detected} 个扫描到`);
    // confirmed 为 0 时也要显式说出来 —— 这是最该让人警醒的一项("没有一个被独立
    // 证实"), 静默省略等于把它藏起来。detected / declared 只在非零时才提。
    parts.push(p.confirmed ? `${p.confirmed} 个声明且被证实` : "0 个被独立证实");
    if (p.declared) parts.push(`${p.declared} 个只来自声明文件`);
    return parts.length ? `${base}（${parts.join("，")}）` : base;
  }

  // "写下的和看到的一致"只有在"看到的"确实是看到的时候才成立。
  // 当前结构里若绝大多数对象本身就来自那份声明文件, 这场比对就是声明与自己对照,
  // 永远 CONFORMANT —— 不说破的话, 这个绿色会被当成"架构没漂"的证据。
  function driftLine(summary, asIs) {
    const base = `${summary.counts.CONFORMANT} 符合 · ${summary.counts.VIOLATION} 冲突 · ${summary.counts.UNVERIFIABLE} 未验证`;
    const p = asIs.provenance;
    if (!p) return base;
    const total = p.detected + p.declared + p.confirmed;
    if (!total || p.declared * 2 <= total) return base;
    return `${base} —— 但当前结构里 ${p.declared}/${total} 本身来自这份声明, 这一栏多半是声明在跟自己比`;
  }

  function architectureBlock() {
    const architecture = state.document.architecture;
    const summary = architecture.summary;
    const wrap = node("section", null, "section architecture-section");
    const header = node("div", null, "section-header");
    const stateBadge = withTerm(
      node("span", summary.state, `text-status ${statusClass(summary.state)}`),
      summary.state
    );
    header.append(node("h2", "系统架构"), stateBadge);
    wrap.append(header);
    const states = node("div", null, "architecture-grid");
    [
      ["当前结构", architecture.as_is, provenanceLine(architecture.as_is)],
      ["目标结构", architecture.to_be, architecture.to_be.state === "DECLARED" ? `${architecture.to_be.entity_ids.length} 个对象` : "项目尚未声明 To-Be"],
      ["一致性", summary, driftLine(summary, architecture.as_is)]
    ].forEach(([label, value, description]) => {
      const item = node("article", null, "architecture-state");
      item.append(node("small", label), node("strong", value.state));
      // 这三个词是整页最显眼的结论, 大白话就直接摆出来 —— 不藏在 hover 后面。
      const plain = termHint(value.state);
      if (plain) item.append(node("small", plain, "term-plain"));
      item.append(node("p", description));
      if (value.evidence_ids?.length) item.append(evidenceButton(value.evidence_ids));
      states.append(item);
    });
    wrap.append(states);

    // 图放在状态卡之后: 先给结论(是否一致), 再给结构。
    const doc = state.document;
    const ents = itemsById(architecture.as_is.entity_ids, doc.entities);
    const rels = itemsById(architecture.as_is.relation_ids, doc.relations);
    const diagram = architectureDiagram(ents, rels, architecture.as_is);
    if (diagram) wrap.append(diagram);
    const flowNote = architectureFlowNote(doc);
    if (flowNote) wrap.append(flowNote);
    return wrap;
  }

  function flowRow(entity) {
    const row = node("article", null, "flow-row");
    const steps = Object.values(state.document.relations).filter(
      (relation) => relation.kind === "flow_step" && relation.source_id === entity.id
    );
    row.append(node("h3", entity.name), node("p", entity.summary));
    if (steps.length) {
      // 顺序取模型给的 order, 不靠数组下标 —— 文档输出前 relations 按 id 排过序。
      steps.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
      // 横排的步骤条: 一眼看出"先干什么、再干什么、各由谁干",
      // 竖排列表读起来是一堆并列的句子, 看不出这是一条链。
      const strip = node("ol", null, "flow-strip");
      steps.forEach((step, index) => {
        const target = state.document.entities[step.target_id];
        const item = node("li", null, "flow-step");
        const card = node("button", null, "flow-step-card quiet");
        card.append(
          node("span", String(step.order ?? index + 1), "flow-step-no"),
          node("span", step.label, "flow-step-action"),
          node("span", target?.name || step.target_id, "flow-step-actor")
        );
        // 点某一步 -> 打开执行它的那个组件, 与架构图节点是同一座桥。
        if (target) card.addEventListener("click", () => openEntity(target));
        else card.disabled = true;
        item.append(card);
        strip.append(item);
      });
      row.append(strip);
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
