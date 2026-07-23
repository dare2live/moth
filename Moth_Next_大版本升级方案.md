# Moth Next 大版本升级方案

## 面向 Vibe Coder 的可视化项目理解、诊断与变更安全平台

---

## 一、方案定位与实施前提

本方案是 Moth 下一大版本的产品方向、信息架构和工程边界设计，不是已经锁定的技术实现清单。

在本机正式实施前，必须先读取并评估：

- Moth 本机当前完整代码；
- 尚未提交或尚未推送的开发内容；
- 当前 CLI、Profile、Snapshot、Assertion、Takeover、Gates 等已有能力；
- 当前 `evidence_paths`、`instruction_sources` 的实际数据结构、校验范围和下游消费者；
- CodeGraph、Omen、Complexity Optimizer 等工具的实际安装方式和版本；
- Mio、Architect Controller、项目 Controller 等本地 Skill 的实际安装、触发规则、职责边界和隐私属性；
- 当前 Python、Node.js、Rust、Xcode 等本机环境；
- 用户正在开发的真实项目类型和规模；
- 现有测试、数据结构和下游调用方式；
- 是否已经存在可复用的网页服务、前端组件或图谱能力；
- 当前项目中哪些设计已经合理，不需要重新实现。

后续具体采用什么前端框架、后端框架、图谱组件、存储方式、端口、命令名称和版本节奏，应在本机调查后再综合决定。

本方案规定的是：

- Moth 应解决什么问题；
- 用户应获得什么体验；
- 各层能力之间如何分工；
- 哪些原则不能被破坏。

不应为了严格套用本文而推翻已经合理运行的本机实现。

---

# 二、Moth 的最终产品定位

Moth 不再只是一个输出 JSON 或 Markdown 的代码检查工具，而应逐步成为：

> 面向 Vibe Coder 的本地项目理解、架构可视化、风险诊断和变更安全工作台。

它既服务于用户，也服务于大模型。

```text
                         Moth Core
       项目识别、证据模型、协作上下文、通用关联和编排
                             │
              ┌──────────────┴──────────────┐
              │                             │
        CLI / MCP / API                Chrome 工作台
              │                             │
        Codex 等大模型                  用户直接查看
```

用户只需要记住 Moth，而不需要分别学习：

- CodeGraph；
- Omen；
- Complexity Optimizer；
- Git 分析；
- 依赖图；
- 测试框架；
- 复杂度指标；
- 数据断言工具。

Moth 在后台调度这些专业能力，最终以适合用户理解的方式呈现。

---

# 三、适用项目范围

Moth 不能以微信小程序为中心设计，也不能假定项目一定是传统网页系统。

它应采用与具体平台无关的通用项目模型，并逐步适配不同技术生态。

可能包括但不限于：

## 苹果平台

- iOS；
- iPadOS；
- macOS；
- watchOS；
- tvOS；
- visionOS；
- Swift；
- Objective-C；
- SwiftUI；
- UIKit、AppKit；
- Xcode Project 和 Workspace；
- Swift Package Manager；
- CocoaPods；
- App Extension、Widget、Share Extension；
- Entitlements、Info.plist；
- Targets、Schemes、Build Configurations；
- App Store 相关配置。

## Web 项目

- 普通网页；
- SPA；
- SSR；
- 前端与后端分离；
- 全栈框架；
- 管理后台；
- API 服务；
- Node.js、Python、Java、Go、Rust 等后端；
- React、Vue、Svelte 等前端；
- Nginx、Docker、云平台与 CDN。

## 微信与其他小程序

- 页面；
- 组件；
- 分包；
- 云函数；
- 小程序配置；
- 登录、支付和平台接口；
- 小程序前端与独立后端的关系。

## 数据和 AI 项目

- Python 脚本；
- Notebook；
- ETL；
- 数据库；
- DuckDB、SQLite、MySQL、PostgreSQL；
- 模型调用；
- 向量数据库；
- 批处理任务；
- 大规模数据文件；
- 数据质量和事实断言。

## 多仓库和混合项目

例如一个完整产品可能同时包含：

```text
iOS App
网页管理端
后端 API
数据处理项目
AI 服务
共享配置仓库
数据库和对象存储
```

Moth 应能够将多个代码仓库视为一个完整产品工作区，而不是把每个仓库孤立分析。

---

# 四、Moth 的核心设计思想：逐层理解，而不是一次展示全部

传统代码图工具常把所有文件、函数和依赖一次性展示出来，结果是一团无法理解的线。

Moth 应采用“渐进式展开”的认知设计：

```text
先回答：这个项目是什么
        ↓
再回答：它由哪些系统组成
        ↓
再回答：使用了什么技术
        ↓
再回答：技术内部如何组织
        ↓
最后才展示文件、函数和原始证据
```

用户不需要先成为程序员，才能获得项目的全局认知。

建议把一个项目划分为五个认知层级。

---

# 五、第一层：项目全景

## 目标

让用户在一个简洁优雅的页面里，迅速掌握项目最重要的信息。

这一层不应出现大量文件名、函数名和专业指标。

它首先回答：

- 这个项目是做什么的？
- 有哪些主要使用端？
- 有哪些核心能力？
- 数据大致怎么流动？
- 当前整体是否健康？
- 最大风险在哪里？
- 现在最应该做什么？
- 哪些地方暂时不要碰？

## 建议页面结构

### 项目身份

```text
项目名称
项目用途
当前版本或分支
项目包含的平台
最近一次体检时间
```

平台可用直观标签表示：

```text
iOS    macOS    Web    API    数据库    AI    小程序
```

### 一句话项目说明

例如：

> 这是一个由 iOS 客户端、网页管理后台、后端服务和数据分析模块共同组成的内容管理产品。

这句话可以来自项目文档、Profile 和代码证据的综合判断，并明确标记可信度。

### 项目全局地图

默认只展示系统级节点：

```text
用户
 ├── iOS App
 ├── Web 管理端
 └── 小程序
        ↓
      后端 API
        ↓
 ┌──────┼────────┐
数据库  文件存储  AI 服务
```

第一层节点数量应受控，不能把几十个模块直接铺满。

### 整体状态

不建议只显示一个模糊的健康分数。

可以展示：

```text
当前状态：需要谨慎

可以继续开发，但任务处理和用户权限两个区域
需要先增加测试和日志，不建议立即整体重构。
```

### 当前最重要的五件事

分成：

- 立即处理；
- 近期关注；
- 暂时不处理。

每项都用普通语言说明，而不是只给出技术指标。

### 当前不建议做什么

这是对 Vibe Coder 特别重要的内容。

例如：

- 暂时不要重写登录模块；
- 不要删除旧接口，仍有两个页面调用；
- 不要同时修改数据库结构和前端状态管理；
- 不要在缺少回归测试时升级核心框架。

---

# 六、第二层：系统架构

用户点击全景图中的某个区域后，进入系统架构层。

这一层回答：

- 项目由哪些独立应用和服务组成？
- 它们如何通信？
- 哪个部分是入口？
- 哪个部分负责业务？
- 哪个部分负责数据？
- 哪些属于第三方平台？
- 系统实际运行在哪里？

## 建议显示内容

### 应用与服务

例如：

```text
iOS 应用
macOS 应用
网页前端
管理后台
API 服务
后台任务服务
AI 分析服务
数据库
对象存储
第三方认证
支付平台
```

### 连接关系

连接箭头不只表示“有关系”，还应说明关系类型：

```text
HTTP API
WebSocket
数据库读写
文件上传
消息队列
本地调用
共享配置
第三方 SDK
```

### 实际架构与期望架构

这是 Moth 可以形成独立价值的重要设计。

Moth 应尽可能区分：

```text
当前真实架构
```

和：

```text
项目声明或设计中的期望架构
```

例如：

```text
设计上：
前端 → API → 业务层 → 数据层

实际上：
部分前端页面绕过业务层直接访问数据服务
```

界面可以将架构偏差叠加展示，并明确说明证据来自哪里。

### 部署关系

按本机和项目实际情况，可能展示：

```text
用户设备
App Store 版本
浏览器
Nginx
应用服务器
Docker 容器
数据库服务器
云存储
第三方 API
```

不应预设所有项目都使用 Docker 或云服务。

---

# 七、第三层：技术栈

用户继续点击某个系统，进入技术栈层。

这一层回答：

- 这个部分使用什么语言？
- 使用了什么框架？
- 如何构建和运行？
- 数据存在哪里？
- 使用了哪些关键第三方组件？
- 哪些技术是核心依赖？
- 哪些技术可能已经过时或同时存在多个版本？

## 技术栈不应只是一串 Logo

Moth 应按职责组织技术，而不是简单罗列依赖包。

例如一个苹果项目可以展示：

```text
开发语言
- Swift
- 少量 Objective-C 兼容代码

界面技术
- SwiftUI
- UIKit

项目组织
- Xcode Workspace
- 4 个 Target
- 2 个 App Extension

依赖管理
- Swift Package Manager
- CocoaPods 遗留依赖

数据
- Core Data
- Keychain
- 后端 REST API

构建与发布
- Debug / Release
- TestFlight
- App Store
```

一个 Web 项目可以展示：

```text
前端
- TypeScript
- Vue
- Vite

后端
- Python
- FastAPI

数据
- PostgreSQL
- Redis

部署
- Nginx
- Docker
- Linux 服务器
```

## 技术栈状态

每项技术可显示：

- 主要用途；
- 当前版本；
- 被哪些模块使用；
- 是否存在重复技术；
- 是否属于核心依赖；
- 升级风险；
- 检测可信度。

例如：

```text
Vue 3
用途：网页前端
范围：管理后台
状态：主要技术

jQuery
用途：两个旧页面
状态：遗留技术
建议：暂不立即删除，仍有实际调用
```

---

# 八、第四层：模块与业务流程

这一层是用户理解项目真正如何工作的关键。

## 8.1 模块视图

Moth 应尽量把代码目录和文件转化成业务意义明确的模块：

```text
用户与权限
内容管理
订单与支付
文件处理
AI 分析
消息通知
数据统计
系统配置
```

用户不应该首先看到：

```text
src/services
src/utils
src/common
src/helpers
```

而应看到这些目录和文件共同承担什么业务职责。

模块识别可综合使用：

- 目录结构；
- 文件和符号命名；
- API 路由；
- 页面入口；
- 数据库模型；
- 项目文档；
- Profile；
- CodeGraph 关系；
- 大模型辅助归纳。

所有由大模型推断的业务含义必须标记可信度，不能假装为确定事实。

## 8.2 业务流程视图

用户可以选择一个功能，例如：

- 用户登录；
- 文件上传；
- 数据查询；
- 内容发布；
- AI 分析；
- 支付；
- 苹果应用内购买；
- 数据同步；
- 报表生成。

Moth 将它展示为一条容易理解的流程：

```text
用户点击登录
→ iOS 登录页面
→ 身份验证服务
→ 后端登录接口
→ 用户数据库
→ 返回令牌
→ 本地 Keychain 保存
→ 进入首页
```

每一步可以继续展开查看：

- 对应应用；
- 对应模块；
- 对应文件和函数；
- 输入和输出；
- 失败处理；
- 相关日志；
- 相关测试；
- 当前已知问题。

## 8.3 状态变化

对于订单、任务、上传、支付等业务，应显示状态转换：

```text
待提交
→ 已提交
→ 处理中
→ 已完成
```

以及失败和恢复路径：

```text
处理中
→ 处理失败
→ 等待重试
→ 处理中
```

Moth 应帮助用户发现：

- 同一个状态在多个位置重复保存；
- 状态转换缺少规则；
- 前端和后端状态定义不一致；
- 存在无法恢复的失败状态。

---

# 九、第五层：工程与代码细节

这一层才进入传统开发者视角。

适合：

- 用户进一步追问；
- 大模型执行修改；
- 专业人员审查；
- 定位具体 Bug。

可以展示：

- 文件；
- 类；
- 函数；
- 调用关系；
- 导入关系；
- API；
- 数据库表和字段；
- 配置项；
- 测试；
- Git 提交；
- 复杂度；
- 重复代码；
- 循环依赖；
- 修改影响范围。

## 代码图必须可控

默认不能展示整个项目的所有代码节点。

应支持：

- 只看当前业务流程；
- 只看某个模块；
- 只看某个文件的上下游；
- 限制调用深度；
- 隐藏第三方依赖；
- 隐藏生成文件；
- 隐藏测试或单独显示测试；
- 按风险突出节点。

点击某个文件时，侧边栏可以显示：

```text
它负责什么
谁调用它
它调用什么
影响哪些业务流程
最近是否经常修改
是否属于高风险热点
有哪些相关测试
当前是否建议修改
```

---

# 十、第六层：证据与原始数据

这是所有判断的最底层。

用户通常不需要首先看到，但必须随时能够追溯。

包括：

- CodeGraph 原始调用关系；
- Omen 原始分析结果；
- Complexity 扫描结果；
- Git 历史；
- 测试输出；
- Assertion 观测值；
- 文件和行号；
- 工具版本；
- 分析时间；
- Moth 规则匹配过程；
- 大模型推断内容及置信度。

每一个重要结论都应允许用户点击“为什么”，看到证据链：

```text
结论：
任务服务是当前最高风险区域

证据：
1. 被 9 个核心模块依赖
2. 最近两个月修改 17 次
3. 相关提交中多次出现 fix 和 bug
4. 内部存在两个高复杂度函数
5. 没有发现完整的集成测试

证据性质：
- 结构事实：2 项
- Git 事实：2 项
- 启发式提示：1 项
```

这样 Moth 既不会让用户面对原始数据，也不会变成无法验证的“AI 黑箱”。

---

# 十一、三种观察视角

除逐层展开外，Moth 还应提供三种横向观察视角。

## 11.1 产品视角

回答：

- 用户能做什么；
- 核心功能有哪些；
- 功能之间如何连接；
- 哪些功能当前存在风险。

## 11.2 系统视角

回答：

- 有哪些应用、服务和数据；
- 它们如何通信；
- 技术栈是什么；
- 如何部署和运行。

## 11.3 风险视角

回答：

- 哪些区域最容易产生 Bug；
- 哪些区域反复修改；
- 哪些区域缺少测试；
- 哪些依赖形成纠缠；
- 哪些项目声明与现实不一致；
- 当前修改可能影响什么。

用户可以在同一个项目上切换视角，而不是在完全不同的页面中迷失。

---

# 十二、Moth 首页不应按技术术语导航

面向 Vibe Coder 的顶部导航可以优先采用问题式入口：

```text
这个项目是什么？
用户操作后发生什么？
项目哪里最容易出问题？
修改这里会影响什么？
当前修改是否安全？
项目最近发生了什么变化？
Moth 检查是否完整？
```

专业功能可以作为次级导航：

```text
架构
技术栈
模块
流程
数据
依赖
风险
变更
证据
工具
```

这种设计能让用户从自己的真实问题出发，而不是先理解软件工程术语。

---

# 十三、每个问题的统一解释模板

无论问题来自哪个分析工具，Moth 都应使用统一方式解释。

## 问题名称

用业务语言表达。

## 它在哪里

说明应用、模块、文件和必要的行号。

## 它负责什么

解释该区域承担的实际业务职责。

## 为什么值得注意

用普通语言解释风险。

## 证据是什么

区分：

- 确定事实；
- 运行结果；
- 项目断言；
- 启发式信号；
- 大模型推断。

## 可能造成什么

说明用户可能实际遇到的现象：

- 页面无法打开；
- 数据无法保存；
- 登录失效；
- 修改一个功能破坏另一个功能；
- 性能下降；
- 重复数据；
- 状态错乱；
- 发布失败。

## 最安全的第一步

不能默认建议重构。

优先考虑：

- 增加日志；
- 增加测试；
- 复现问题；
- 确认调用关系；
- 固定接口契约；
- 清理重复实现；
- 小范围修改。

## 暂时不要做什么

例如：

- 不要整体重写；
- 不要同时升级框架；
- 不要删除仍有调用者的旧模块；
- 不要修改数据库后再补迁移脚本。

---

# 十四、Moth 的统一核心架构

Moth 应保留“一套核心、多种入口”。

```text
          Project Discovery + Guidance Discovery
     识别项目边界，也识别本次判断依赖的指令和 Skill
                           │
                           ↓
            Moth Adapters + Context Resolver
 CodeGraph / Omen / Git / Tests / Repo Rules / Codex Skills
                           │
                           ↓
                   Unified Project Model
 系统、模块、流程、数据、代码、问题、证据、协作上下文
                           │
                           ↓
             Generic Correlation and External Rules
 关联证据、执行仓库声明的规则，但不替项目或用户创设规则
                           │
                           ↓
                    Moth Snapshot
                           │
          ┌────────────────┼────────────────┐
          ↓                ↓                ↓
       CLI/MCP         Chrome UI       Markdown/JSON
```

## 统一项目模型

Moth 不应只存储“文件和函数”，还应逐步形成通用对象：

```text
Workspace
Product
Repository
Application
Service
Module
Feature
User Flow
API
Data Store
Table / Entity
External System
Deployment Unit
File
Symbol
Test
Finding
Evidence
Guidance Source
Decision Context
Activation Receipt
Snapshot
```

不同技术项目都映射到这套模型。

例如：

```text
iOS Target
Web Application
微信小程序
Python 后台服务
```

在统一模型中都可以是 `Application`。

Swift Package、Node Package 和 Python Package 都可以映射成可依赖的技术组件，但保留各自原始类型。

---

# 十五、项目识别与平台适配

Moth 应采用可扩展的探测器和适配器，不把平台规则写死在核心中。

候选探测器包括：

## Apple 探测器

可根据本机实际情况逐步识别：

- `.xcodeproj`；
- `.xcworkspace`；
- `Package.swift`；
- `Podfile`；
- Targets；
- Schemes；
- Build Configurations；
- Entitlements；
- App Extensions；
- Info.plist；
- Swift 和 Objective-C 比例；
- 关键框架。

## Web 探测器

识别：

- `package.json`；
- 前端框架；
- 后端框架；
- 路由；
- API；
- 构建工具；
- SSR 或 SPA；
- 环境变量；
- 部署配置。

## 小程序探测器

识别：

- 页面；
- 分包；
- 组件；
- 云函数；
- 小程序配置；
- 平台接口；
- 后端连接。

## 数据项目探测器

识别：

- 数据库；
- Notebook；
- ETL 脚本；
- 数据文件；
- 表结构；
- 数据断言；
- 批处理和定时任务。

探测器应返回标准化结果，但允许保留平台特有信息。

---

# 十六、当前架构与期望架构

Moth 的长期重要能力，应包括两种架构的对比。

## 当前架构 As-Is

从真实代码、配置、运行环境和依赖中发现。

## 期望架构 To-Be

可能来自：

- `.moth/profile.yaml`；
- 架构文档；
- AGENTS 文件；
- 用户确认；
- 项目规则；
- 预设分层要求。

Moth 可以展示架构漂移：

```text
期望：
UI 只能调用 Service

实际：
3 个 UI 模块直接引用 Database 层
```

或：

```text
期望：
所有登录逻辑通过 AuthService

实际：
iOS 和 Web 各自维护了一套独立登录规则
```

不能自动确定的内容，应交由用户确认后写入项目 Profile，成为后续持续检查的规则。

---

# 十七、可视化设计原则

## 简洁优先

首页只展示：

- 项目身份；
- 全景架构；
- 当前状态；
- 最高优先级问题；
- 下一步行动。

## 渐进披露

专业信息通过点击、展开和下钻获得，不一次堆满。

## 业务名称优先

优先显示：

```text
用户登录
文件处理
数据分析
```

而不是：

```text
AuthManager
FileProcessor
AnalyticsServiceImpl
```

必要时同时显示技术名称。

## 证据随时可见

每个结论都有“查看证据”，但证据不应干扰初始阅读。

## 避免毛线球

全局图按系统和模块聚合，代码节点只在用户下钻后加载。

## 不用颜色代替文字

风险必须同时有：

- 标签；
- 文字说明；
- 图形区别。

## 不虚构确定性

Moth 应明确展示：

```text
已确认
高可信推断
低可信推断
尚未检查
工具不可用
```

---

# 十八、AI 与网页的协作方式

浏览器界面负责让用户“看见”。

大模型负责帮助用户“理解和行动”。

在某个节点或问题旁，可以提供：

```text
用普通话解释
为什么会这样
它影响哪些功能
制定安全修复计划
让 Moth 进一步检查
交给 Codex 处理
```

但网页不应直接把原始项目全部发送给远程模型。

具体如何连接本机 Codex、MCP 或其他模型，应在读取本机能力后评估。

修改流程不应把“每一步都问用户”写成唯一模式。应先按动作后果分层：

- 只读、本机、可逆、边界明确的动作，可以由 Controller 直接推进并事后汇报；
- 范围较宽、方向性较强或会改变共享状态的动作，应先展示计划；
- 不可逆、外部写入、付费、敏感数据或跨仓库动作，必须显式确认；
- 目标仓库存在更严格门禁时，以仓库门禁为准；
- Mio 等个人协作契约可以改变交互方式，但不能覆盖项目真相源、业务规则或安全门禁。

完整闭环应是：

```text
解析项目规则与协作上下文
→ 分析并给出 PROCEED / REVISE / BLOCK
→ 按动作风险决定直接推进或请求确认
→ Codex 修改
→ Moth 重新体检
→ 对比修改前后
```

---

# 十九、Mio 与协作上下文层

Mio 不能只作为方案中的一个工具名称，也不能被复制成 Moth Core 内的一组固定规则。

它的正确定位是：

> Mio 决定“这个用户希望 Controller 如何判断和协作”；目标仓库决定“项目什么算正确”；Moth 证明“本次用了哪些规则、证据是否新鲜、是否真的激活”，但不替两者立法。

## 19.1 为什么 Moth 必须认识 Mio

仅有代码图、复杂度和测试结果，仍不足以让不同 Agent 或不同模型稳定接手同一个项目。

新的执行者还需要知道：

- 哪些判断必须先回到第一手真相源；
- 什么时候应先搭地基，什么时候可以直接执行；
- 什么时候应主动找反例或进行对抗审阅；
- 哪些动作可以自主推进，哪些必须保留给用户；
- 结果应该如何诚实标记为 `confirmed`、`partial`、`unknown` 或 `blocked`；
- 当前 Mio 是否已经被修改，旧会话加载的版本是否已经过期。

如果这些信息只靠用户在每次换 Agent、换模型后重新解释，Moth 就没有完成“接管与持续上下文”的目标。

但 Moth 只能管理这份上下文的发现、来源、新鲜度和激活证据，不能把 Mio 的个人化判断语义改写为项目健康规则。

应明确区分两个平面，并由 Controller 独占最终裁决：

```text
Evidence Plane
CodeGraph / Git / Tests / Assertions / DB / 官方源
              │
              ├── 提供事实、观测和证据链
              │
Judgment & Collaboration Plane
Mio / Architect Controller / 项目 Controller
              │
              ├── 提供审问框架、计划约束和验证要求
              ↓
Controller → PROCEED / REVISE / BLOCK
```

协作 Lens 不得向证据平面注入“事实”，工具输出和子 Agent 输出也不得越权成为最终 Verdict。

## 19.2 定义权和职责边界

这些来源不能被简单拼成一条线性优先级。它们属于不同维度：

| 来源类型 | 例子 | 定义什么 | Moth 的职责 |
|---|---|---|---|
| 运行时权威指令 | 系统和开发者约束 | 当前执行环境不可越过的边界 | 在可见范围内记录来源，不尝试覆盖 |
| 项目权威 | `AGENTS.md`、Profile、项目 Gates | 项目什么算正确，真相源和业务门禁是什么 | 读取、校验、执行或展示结果 |
| 个人协作 Lens | `skill:mio` | Controller 应如何判断、协作、质疑和汇报 | 解析、验鲜、记录激活状态，不复制语义 |
| Controller 协议 | Architect Controller、项目 Controller | 如何拆解、分配注意力、验证和收口 | 路由到正确 Controller，保留决策证据 |
| 工具证据 | CodeGraph、Complexity、Git、Tests | 代码和运行状态的可观测事实 | 适配、标准化、关联和溯源 |

Mio 可以在实质任务开始前最先加载，但“先加载”不等于“高于项目规则”。出现冲突时：

1. Moth 标记 `CONFLICT_NEEDS_JUDGMENT`；
2. Moth 展示冲突双方的来源、摘要、digest 和适用范围；
3. Controller 负责裁决；
4. Moth 不得自动让 Mio 覆盖目标仓库，也不得把冲突本身算成项目代码失败。

## 19.3 通用数据模型，不做 Mio 专属硬编码

现有 Moth 已能在 Profile 中保存 `evidence_paths` 和原样透传
`instruction_sources`，Snapshot 也能输出这些字段。这是可复用地基，但还不能证明一个 Skill
可解析、内容新鲜或已被执行器真正加载。

第一轮实现已把它向后兼容地演进为通用 `GuidanceSource` discovery 契约：

```yaml
instruction_sources:
  active:
    - AGENTS.md
    - Codex skills
    - live tooling output
  sources:
    - id: mio
      kind: collaboration_lens
      provider: codex_skill
      ref: skill:mio
      activation: substantive_judgment
      requirement: required_when_active
      scope: user
      owner: user
      sensitivity: personal
      egress_policy: metadata_only
```

跨机器契约使用 `skill:mio` 这样的逻辑引用。运行时 Resolver 再从当前 Codex
环境解析真实文件；`${CODEX_HOME}`、`~` 或本机绝对路径只能作为本地发现线索和证据，
不能成为产品级主键。

`GuidanceSource` 至少包含：

```text
id
kind
provider
logical_ref
scope
activation
requirement
owner
resolved_path_local_only
source_digest
source_mtime
discovered_at
sensitivity
egress_policy
state
```

一次具体任务再产生 `DecisionContext`：

```text
run_id
task_intent
active_guidance_sources
project_authorities
controller_protocols
tool_evidence
snapshot_ref_and_freshness
definition_authority
truth_sources_primary_and_derived
foundation_gate
consumer_and_consumption_step
real_world_consequence
floor_review
ceiling_review
falsification_and_counterexamples
adversarial_review
pre_change_impact
post_change_verification
conflicts
missing_required_sources
activation_receipts
decision
```

这些字段是通用的 Controller Contract，不是 Moth 对 Mio 正文的翻译。Mio、项目
Controller 或其他外部协议决定本次哪些字段为必填；Moth 只校验字段、freshness、证据引用和
状态转换。例如：

- Snapshot 不新鲜时不得给 `PROCEED`；
- 高风险任务的地基门不是 `PASS` 时应 `BLOCK`；
- 声称确定事实却没有第一手证据时，应降级为 `UNKNOWN` 或阻断；
- 有方向性、价值权衡或过拟合风险但缺少对抗复核时，应 `REVISE`；
- 破坏性变更缺少新鲜影响面证据时，应 `BLOCK`；
- floor 已通过但 ceiling 未复核时，可以允许边界明确的局部执行，但不能声称整体完成；
- `PROCEED` 必须引用当前 Snapshot 中可解析的 evidence ID，不能只有自然语言理由。

## 19.4 激活状态不能假绿

Moth 必须区分：

```text
UNAVAILABLE
→ DISCOVERED
→ LOADED
→ APPLIED_WITH_EVIDENCE
```

- 找到文件，只能证明 `DISCOVERED`；
- 执行器回传与当前 `source_digest` 一致的加载回执，才能证明 `LOADED`；
- `APPLIED_WITH_EVIDENCE` 还需要本次 Controller 给出 `contract_id`、`run_id`、
  `loaded_at`、决策摘要和可审计的执行证据；
- `APPLIED_WITH_EVIDENCE` 只表示契约字段和证据完整，不能诚实证明模型“真正理解了 Mio”；
- Moth 不能仅凭 Agent 自述把状态升为绿色；
- 源 Skill 更新后，旧回执自动变成 `STALE`；
- 未触发 Mio 的机械任务应标记 `NOT_APPLICABLE` 和原因，而不是伪装成已加载。

对于已声明 `required_when_active` 的来源：

- 普通 Snapshot 可以显示 `WARN`，说明当前尚未绑定具体任务；
- 一旦任务分类命中 `activation`，缺失、过期或 digest 不匹配必须使接管/执行前门禁
  `FAIL` 或 `NO-GO`；
- 可选来源缺失只能显示能力降级，不能冒充完整上下文。

## 19.5 Mio 的触发矩阵

第一版不需要把 Mio 的全部语义解析成规则引擎，只需准确判断是否必须加载：

| 任务类型 | Mio 状态 | 还应加载 |
|---|---|---|
| 判断、分析、架构、诊断、方案取舍 | 必须 | 相关 Controller 与项目权威 |
| 大改、跨模块、花钱、部署、迁移 | 必须 | Architect Controller、项目治理 Skill、Grill Gate |
| 审计、研究、接手、复检 | 必须 | 项目证据路径、只读工具、必要的对抗审阅 |
| 低风险机械读取、格式转换、确定性小改 | 可不加载，但记录 `NOT_APPLICABLE` | 直接适用的项目规则 |

任务分类结果本身也应进入证据层，避免不同 Agent 对“这次算不算实质任务”各自猜测。

## 19.6 隐私与出站边界

Mio 正文包含个人化协作信息和可修订历史，默认不能进入可分享的 Snapshot、静态 HTML、
远程 MCP payload 或发送给远程模型。

默认对外只输出：

```yaml
provider: codex_skill
id: mio
state: DISCOVERED
source_digest: "..."
sensitivity: personal
body_exported: false
```

要求：

- 本机 UI 可以在授权后打开真实来源；
- 默认导出隐藏绝对路径、用户名、正文、amend trail 和个人行为描述；
- 只有显式 opt-in 才能导出正文；
- 远程模型获得什么上下文必须留下 egress 记录；
- Moth 不缓存 Mio 的“精简摘要”，避免形成第二真相源。

## 19.7 Mio 与架构师的组合顺序

Moth 不把 Mio 和架构师做成两个需要用户记忆的入口。用户只调用 Moth，Moth 根据
用户级 Guidance 注册表生成有序计划：

```text
Mio collaboration_lens
→ architect-controller controller_protocol
→ 可选的项目专属 controller
```

顺序由 `load_after` DAG 决定，不用整数优先级冒充跨权威裁决。Mio 定义协作与判断
视角，架构师定义真相源、边界、证伪门禁和收口协议；二者都不能覆盖项目自己的业务
权威。任何环或缺失依赖都 fail closed。

## 19.8 当前实现进度与诚实边界

截至 2026-07-23，已经实现：

- 用户级 Guidance 注册表与项目 Profile 合并；
- Mio → architect-controller 的 DAG 顺序；
- 任务分类、`DecisionContext`、`ActivationReceipt` 和 digest `STALE` 判定；
- `DISCOVERED`、适用性、receipt 和 application 四个正交状态面；
- `moth inspect` 单入口，且项目健康与任务上下文 readiness 分离；
- Moth Codex Skill 执行桥：按计划读取真实 Skill 后只能生成
  `SELF_ATTESTED` 自证；只有 host-native 可信遥测才能验收到 `READY`；
- 默认输出不包含 Skill 正文、解析路径、任务原文或 amend trail。

仍缺少：

- 冲突回报和 `APPLIED_WITH_EVIDENCE` 的任务完成态；
- 显式正文 opt-in、远程 egress 记录和分享模式；
- `.agents`、插件 Skill 等 `codex_skill` 默认目录之外的 provider；
- 插件新任务中的独立前向验收。

Moth Core 自己读取文件最多只能证明 `DISCOVERED`。只有实际 Codex/Agent 执行桥完整
读取 Skill 并回传当前 run/source/digest 匹配的本地收据，只能把上下文判为
`SELF_ATTESTED`；本地 helper 不能自称不可伪造证明。只有宿主签发、绑定可信
executor contract 的遥测才能把上下文判为 `READY`；
不得由 CLI 自签或把“找到文件”显示成“已应用”。

---

# 二十、Moth 大版本建议实施路线

以下是建议顺序，不是不可调整的固定版本计划。

## 阶段零：本机现状审计

先完成：

- 读取 Moth 本机代码；
- 检查未提交内容；
- 运行全部现有测试；
- 运行现有 Moth 自检；
- 检查已有 Web、API 和 Schema 能力；
- 检查 CodeGraph 和 Omen；
- 检查 Mio 和其他 Controller Skill 的逻辑 ID、实际路径、frontmatter、digest、触发条件和隐私边界；
- 验证现有 `instruction_sources` 只是原样透传，不能把“字段存在”当成“Skill 已应用”；
- 选择若干真实项目作为样本；
- 输出“现有能力与目标方案差距报告”。

阶段零完成前，不进行大规模重构。

### 阶段零实测结论（2026-07-23）

- 官方上游识别为 `panbanda/omen`，本机通过
  `brew install panbanda/brews/omen` 安装；`omen 4.25.0` 只是本轮实测版本，
  不是允许版本上限；
- CodeGraph 已从本机观测到的 `1.2.0` 更新至官方最新稳定版 `1.5.0`，既有
  `status`、`affected`、`explore` 和 Moth 归一化合同重跑通过；该数字同样只是
  观测证据，后续更新仍以能力和 JSON 输出合同为准；
- `hotspot --top 10` 与 `changes --top 10` 均能对 Moth 仓库输出紧凑 JSON，
  且运行前后未产生仓库文件；
- 首个适配面限定为 `hotspot`、`changes`、`diff`，记录观察到的版本和归一化状态，
  不导出 raw stdout/stderr、作者或提交消息；
- 兼容性以每次运行的命令能力和 JSON 输出契约探针为准，不锁定某个 minor 版本；
  新版本契约兼容即可继续，契约变化则 fail closed 并要求更新 adapter/fixture；
- 不把 `omen all` 设为门禁，因为聚合成功不能替代对子分析器失败的逐项判定；
- Omen 当前公开语言清单未显式包含 Swift，因此不能用它单独声称 Apple 项目覆盖；
- 上游仓库标注 Apache-2.0，而 Homebrew formula 的 license 字段标为 MIT；在引入
  任何 vendored 代码前必须先向上游核实。当前只调用外部 CLI，不复制其源码；
- Omen 实测把 `src/moth/report.py` 与 `src/moth/cli.py` 列为 Critical hotspot，
  所以本轮只落 Guidance discovery 和薄契约，不在这两个入口继续堆叠新编排。

## 阶段一：统一项目模型

目标：

- 在现有 Snapshot 基础上建立兼容的项目模型；
- 统一表示应用、服务、模块、技术、流程、风险和证据；
- 加入通用 `GuidanceSource`、`DecisionContext` 和 `ActivationReceipt`，保持旧 Profile 可读；
- 保留现有下游兼容性；
- 不急于制作复杂网页。

## 阶段二：Mio 与架构师协作上下文最小闭环

先完成一个不依赖复杂网页的机器可验收闭环：

```text
识别任务是否属于实质判断
→ 合并用户 Guidance 注册表与项目 Profile
→ 按 DAG 解析 skill:mio → skill:architect-controller
→ 校验每个来源的身份、digest、隐私策略和适用范围
→ Codex 执行桥逐个读取并返回加载回执
→ 生成包含真相源、地基、消费者、反证和 Verdict 的 Controller Contract
→ Takeover / Snapshot 展示真实激活状态和证据完整性
→ 源 Skill 变化后旧回执自动失效
```

这一阶段只实现通用协议，以 Mio 和 architect-controller 作为两个不同角色的真实样本；
不得在 Moth Core 复制任一 Skill 正文或把发现状态冒充实际应用。

### 阶段二实施进度（2026-07-23）

- Moth 单入口从用户 Guidance 注册表与项目 Profile 合并来源，并按 DAG 固定得到
  `mio → architect-controller`；发现、适用性、加载回执和应用证据是四个正交状态；
- 本地 helper 只能签发与 run/source digest 绑定的 `SELF_ATTESTED` 回执，不能冒充
  宿主验证；`READY` 保留给未来真实的 host-native 可信遥测，这个诚实边界不是
  Moth Core 可以靠增加一个布尔值“实现”的能力；
- `moth.guidance-application.v1` 独立记录某个 Guidance 影响的决策、证据引用以及
  与其他 Guidance 的结构化冲突和解决方式；缺失、过期、重复、证据不足或来源未发现
  都保持 `NOT_CLAIMED`，只有有效合同才是 `APPLIED_WITH_EVIDENCE`；
- application report 的 `contract_id/loaded_at` 必须与同一来源的有效加载回执一致，
  每个决策必须有摘要，全部 evidence ref 必须能在本次 ProjectModel 证据注册表解析；
  悬空或臆造引用不能把状态升绿；
- CLI 通过 `--application-reports` 把该合同送入同一个 `moth inspect`，Core 不解析
  Skill 正文或聊天文本来猜测“是否应用”，应用证据也不会把自证加载升级成平台验证。

## 阶段三：最小可视化闭环

先实现一个真实可用的 Chrome 视图：

```text
选择项目
→ 运行体检
→ 查看项目全景
→ 查看技术栈
→ 查看最高风险问题
→ 点击查看证据
```

第一版可以根据本机实际情况选择：

- 静态 HTML；
- 本地 Web 服务；
- 现有前端工程。

## 阶段四：逐层架构浏览

增加：

- 系统层；
- 技术栈层；
- 模块层；
- 业务流程层；
- 工程细节层；
- 证据层。

## 阶段五：多平台适配

根据用户真实项目优先级逐步增加：

- Apple 项目；
- Web 项目；
- 小程序；
- Python 和数据项目；
- 多仓库工作区。

不追求第一版支持所有语言和框架。

### 阶段一、三、四、五实施进度（2026-07-23）

当前实现已经形成配置驱动、渲染器无关的第二个可恢复检查点：

- `moth.project-model.v2` 由 detector registry 与独立 ArchitectureModel 汇总，
  同时保留 v1 形状的兼容投影；探测规则和扫描预算集中在
  `platform_rules.yaml`，并由 JSON Schema fail closed 校验；Core 不按框架名写分支；
- Apple、Web/API、微信/支付宝小程序、数据/AI、多仓库 detector 只读取仓内清单和
  结构证据，不跟随 symlink，不泄露 `.gitmodules` URL，不把包名猜测成平台；
- 多 detector 合并、冲突、coverage 和 mixed composition 有统一合同；Data 与 AI
  是同一数据智能平台的子能力，不因同时存在就虚构成多平台项目；
- `moth.visual-document.v1` 是 renderer-neutral 单一视觉合同，运行时使用同一份
  打包 Schema 校验；实体、关系、问题、
  行动和证据全局去重并用引用连接；层和视角来自 `visual_policy.yaml`；
- `moth inspect --format html --output <report.html>` 通过同一个 Moth 入口生成
  自包含静态报告，包含六层、三视角、首页优先项、禁止项和统一问题解释卡；
- As-Is 只显示已观察事实；To-Be 只读取仓库拥有且经 Schema 校验的
  `.moth/architecture.yaml`，自由文本只能作为 provenance，不能自动变成架构事实；
  显式 `REQUIRED/FORBIDDEN` 约束会与 As-Is 比较，覆盖不足时返回
  `UNVERIFIABLE`，不会把未知洗成符合或违规；
- 统一模型已经承载服务、关系、真实流程和状态机；入口或 runtime 关系不会冒充
  业务流程，To-Be 中尚未存在于 As-Is 的新实体也会被保留；
- 真实浏览器验收覆盖 1280px 桌面与 390×844 移动视口：无外部资源和控制台错误，
  无重复 ID 或失效内部锚点，移动端无根文档横向溢出，导航触控高度至少 44px。
- 实体、关系、问题和证据分别受 `visual_policy.yaml` 容量预算约束；10,000 应用、
  10,000 关系和 10,000 独立证据的对抗 fixture 仍生成小于 500KB 的 HTML，并保留
  omitted 计数与所有可见证据锚点。

这批实现没有引入某个工具或平台的版本上限。平台识别规则、视觉分类、容量上限和
外部工具输出合同分别由独立配置与模块负责；渲染器只消费统一合同，不能调用探测器
或了解 CodeGraph、Omen、Mio 等具体上游。

## 阶段六：风险关联与变化分析

增加：

- CodeGraph 结构事实；
- Omen 热点和 Git 历史；
- Complexity 性能提示；
- 测试结果；
- Assertion 事实；
- 多证据关联；
- Snapshot 历史对比。

## 阶段七：变更安全工作流

增加：

- 修改前影响分析；
- 当前 Git diff 分析；
- 受影响测试；
- 修改后对比；
- GO、CAUTION、NO-GO；
- 浏览器和大模型共享结果。

### 阶段六、七实施进度（2026-07-23）

- `moth inspect` 是变更前、中、后的同一入口；机制由
  `change_safety.py` 提供，通用 verdict 与预算在包内 policy，目标仓库必须通过
  `.moth/change-safety.yaml` 声明自己的 mandatory gates；
- CodeGraph 影响范围、affected tests、Omen/Complexity 提示和 gate 结果经统一
  evidence/association 合同引用 ProjectModel 实体，不反写 ArchitectureIntent；
- `affectedTests` 永远只是 `PLANNED`，不是执行证明；provider 返回空列表但没有
  completeness 证据时为 `UNKNOWN_EMPTY`，旧 `moth affected` 也返回 WARN/exit 2，
  已消除本轮实测的空测试假绿；
- Omen 与 Complexity 只产生 `HEURISTIC` 且 `causal_claim=false` 的提示，单独最多
  `CAUTION`，不能被提升为根因或 `NO_GO`；
- `--plan-only` 不执行任何 gate；变更安全退出码固定为
  `GO=0 / NO_GO=1 / CAUTION=2`，目标仓库 mandatory gate 与命令行附加 gate 使用
  additive 合并，不能被调用者替换或跳过。

## 阶段八：工具和上游管理

增加：

- 工具版本；
- 兼容性；
- 更新检查；
- 升级测试；
- 安全升级；
- 失败回滚。

用户说“更新 Moth 相关工具和 Skill”或同义表达时，由 Moth 单入口进入维护流程：
从官方上游盘点和更新，记录观察版本，重跑能力/输出契约探针、全量测试、插件校验与
新任务前向验收；不得因为旧的精确版本常量阻断契约兼容的新版本。

---

# 二十一、不应在方案阶段写死的内容

本机评估前，不锁定：

- Web 前端框架；
- 本地服务框架；
- 图谱库；
- 数据库存储方式；
- API 接口路径；
- 默认端口；
- CLI 命令最终名称；
- Moth 版本号；
- 是否立即接入 Omen；
- Apple 项目具体解析方案；
- 是否使用 Xcode 命令行工具；
- 是否生成静态 HTML；
- 是否使用 WebSocket；
- 是否打包桌面应用；
- 是否支持远程访问；
- Mio 的本机绝对路径；
- Mio 正文副本或内置摘要；
- Mio 的永久版本号；
- 把 Mio 设为所有用户、所有任务都必须启用的产品级默认；
- 每个阶段的工作量。

这些应由 Codex 在本机调查后提出建议并说明取舍。

---

# 二十二、验收标准

升级后的 Moth 应让没有代码基础的用户，在 Chrome 中回答以下问题：

## 全局认知

- 这个项目是做什么的？
- 包含哪些应用和平台？
- 前端、后端、数据库和第三方服务如何连接？
- 项目使用了哪些主要语言和技术？
- 哪些是核心技术，哪些是遗留技术？

## 功能理解

- 用户完成一个操作后，系统内部发生什么？
- 数据经过哪些模块？
- 哪一步会写数据库？
- 哪一步调用外部服务？
- 失败后如何处理？

## 风险理解

- 当前项目最危险的区域在哪里？
- 为什么认为它危险？
- 这是事实还是推测？
- 可能造成什么实际问题？
- 最安全的处理顺序是什么？
- 哪些地方暂时不要修改？

## 变更理解

- 修改这个文件或功能会影响哪里？
- 哪些页面、服务、数据和测试可能受影响？
- 当前修改是否适合提交？
- 修改后项目是变好了还是变坏了？

## 证据理解

- 这个判断来自哪个工具？
- 使用了哪个版本？
- 对应哪个文件和代码位置？
- 是否有测试、日志或断言支持？
- 哪些检查还没有完成？

## 协作与判断完整性

- 这次判断使用了哪些项目规则、Controller 和协作 Skill？
- Mio 是未安装、已发现、已加载，还是有执行证据？
- 加载回执是否匹配当前 Skill digest？
- 这次任务为什么触发或没有触发 Mio？
- 结论锚定了哪些第一手真相源，哪些只是派生证据或推断？
- 地基是否完整，产物由谁在什么步骤消费，真实后果是什么？
- 当前只验证了 floor，还是也检查了官方颗粒度和产品目标的 ceiling？
- 什么反例或门禁能够证伪当前结论？
- 需要对抗复核、改前影响分析或改后审计时，是否已有新鲜证据？
- 是否存在项目规则与个人协作 Lens 的冲突？
- 是否有必需上下文缺失，却被错误显示为绿色？
- 分享或远程发送结果时，是否隐藏了 Mio 正文、个人信息和本机绝对路径？
- 换 Agent、换模型或重启会话后，是否能从新鲜证据自动重建相同的决策上下文？

## Mio 接入的强制反例

验收不能只测正常路径，至少要证明以下反例会被正确识别：

1. Mio 未安装，但 Profile 将其声明为当前任务必需；
2. 存在同名文件，但 frontmatter `name` 不是 `mio`；
3. `CODEX_HOME` 或用户目录改变，逻辑引用仍能重新解析；
4. 文件已更新，但执行器沿用旧 digest 或旧缓存；
5. 文件存在，但执行器从未读取；
6. Agent 自称已加载，但没有可验证回执；
7. Mio 与目标仓库规则冲突；
8. 默认 JSON、Markdown、HTML 或远程 payload 泄漏正文、amend trail、用户名或绝对路径；
9. 低风险机械任务未触发 Mio，却被错误判为上下文失败；
10. Moth 把 Mio 的个人偏好误算成项目代码或业务健康失败。

---

# 二十三、最终愿景

Moth 最终不应只是一个“代码健康检查器”，也不应只是一个“漂亮的依赖关系图”。

它应成为一个从业务到代码逐层展开的项目认知系统：

```text
第一眼：
我知道这个项目是什么，整体是否健康。

点击一下：
我知道它由哪些应用、服务和数据组成。

继续展开：
我知道每个部分使用什么语言和技术。

再继续：
我知道核心功能内部如何运行。

需要处理问题时：
我知道问题具体在哪里、为什么重要、影响什么。

需要修改时：
我知道应该先做什么、如何验证、哪些地方不要碰。

需要深入时：
我可以看到完整代码关系、指标和原始证据。
```

Moth 的最终价值不是替代程序员，也不是用一个分数假装理解所有项目。

它真正应该做到的是：

> 把原本只有架构师和资深开发者才能逐步建立的项目认知，以简洁、优雅、可验证的方式交给 Vibe Coder；同时让每次判断都能说明自己依据了哪些项目规则、协作契约和新鲜证据。
