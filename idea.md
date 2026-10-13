# User Message

我正在设计一套面向 AI Agent Harness 的 SOP（Standard Operating Procedure）体系，希望你作为 AI Agent 架构师、工作流引擎设计者和企业自动化系统架构师，帮助我进行开放式架构研究。
我的目标不是构建传统的固定工作流引擎，也不是简单地将 SOP 写入 Prompt，而是构建一个能够支持 SOP 定义、加载、动态实例化、稳定执行、运行记录、分析与优化的全生命周期体系。
我的设想是：
企业业务人员可以发布不同的 Skill，例如财务报销、员工借款、差旅管理等。每个 Skill 可以通过 SKILL.md 或独立的 graph.md 定义业务 SOP。
当用户提出任务时，Agent 识别并加载对应的 Skill 和 SOP，结合用户身份、业务上下文、企业规则和外部系统数据，动态实例化一个适用于本次任务的具体工作流。
例如，同样是财务报销，不同城市、职级、发票类型、部门和报销金额，可能对应不同的验证、计算和审批流程。
工作流实例化后，Agent 应当按照该工作流执行任务。执行过程可能涉及 LLM 推理、工具调用、API/CLI 操作、用户确认、人工审批、等待外部系统，以及异常处理。
任务可能持续数天，不能依赖单次 Agent 会话维持执行状态。
执行过程中也可能出现新情况，因此需要考虑工作流的受控动态调整。
我希望有一套 SOP Runtime 或类似机制，负责管理 SOP 实例的完整生命周期，并对执行过程进行记录、验证、恢复、分析和优化。
请不要直接沿用我提到的技术概念或预设架构，也不要局限于传统 Workflow Engine、DAG 或状态机。
请先从问题本质出发，分析：
1. 我真正试图解决的核心问题是什么？是否存在比“SOP Runtime”更准确的系统抽象？
2. 这个体系应该包含哪些核心概念？这些概念之间是什么关系？



# AI Response

# 面向 AI Agent Harness 的 SOP 体系：从第一性原理重新定义问题与核心抽象

## 一、先给出我的核心判断

我认为，你想构建的东西，比 SOP Runtime、Workflow Engine、Agent Orchestrator 都要更大一些。

**你真正想解决的是：如何让一个具有自主推理和行动能力的 AI Agent，能够在企业规则约束下，持续、可靠、可审计地承担并完成真实的业务任务。**

这里有几个关键区别：

- 不是让 Agent 知道应该怎么做，而是让它**承担一个需要最终完成的业务责任**。
- 不是把业务 SOP 翻译成一张流程图，而是让系统**根据当前任务生成合规的执行方案，并允许方案受控演化**。
- 不是简单地让 Agent 调用工具，而是让每一次行动都有**明确的权限、依据、前提和可验证的结果**。
- 不是让一次 Agent Session 执行完所有任务，而是让**业务任务拥有独立于 Agent Session 的持久生命周期**。
- 不是只记录 Agent 做了什么，而是能够回答**为什么这样做、是否做对了、是否符合当时的企业规则，以及如何改进**。

因此，我建议暂时不要从 SOP、Skill、DAG 或 Workflow 作为最顶层抽象开始设计。

我们可以从一个更本质的对象开始：

> **一个被委托给智能系统、需要在特定约束下达成业务结果的 Work（工作事项）。**

Agent 是执行者之一。

Skill 是能力与业务知识的载体。

SOP 是企业认可的工作规范。

Workflow 是具体任务的一种执行计划。

而真正需要长期存在和被管理的，是 **Work Instance（工作实例）**。

由此，我建议将整个研究对象暂时命名为：

**Governed Agentic Work Runtime：受治理的智能体工作执行运行时。**

也可以简称为 **Work Runtime**。

这个名称不是现有行业标准，而是我基于你的目标提出的系统级抽象。

它强调三个属性：

1. **Work**：管理的是持续存在的业务工作，而不是一次模型调用。
2. **Agentic**：执行方案可以由智能体根据情况生成和调整。
3. **Governed**：智能体的自由度始终受到业务规则、权限、承诺和验证机制的约束。

接下来从问题本身展开。

---

# 二、问题一：你真正试图解决的核心问题是什么？

## 2.1 企业业务任务本质上不是一串操作

我们用财务报销来分析。

假设用户提出：

> 帮我报销上周去上海出差的费用。

从传统 Workflow Engine 的视角，这可能被建模成：

```text
提交申请
    ↓
上传发票
    ↓
验证发票
    ↓
计算报销金额
    ↓
发起审批
    ↓
财务付款
    ↓
完成
```

但这种建模隐藏了很多重要问题。

例如：

**第一，业务事实可能尚不完整。**

系统不知道：

- 出差是否已经经过批准？
- 实际发生了哪些费用？
- 哪些发票属于本次出差？
- 有没有公司统一支付的费用？
- 用户所属的部门、职级是什么？
- 是否存在需要特殊处理的费用？

**第二，业务规则具有条件性。**

例如：

- 城市不同，住宿标准可能不同。
- 职级不同，费用额度可能不同。
- 发票类型不同，验证要求可能不同。
- 金额不同，审批权限可能不同。
- 特殊费用可能需要额外说明。

**第三，执行过程中会产生新的事实。**

例如：

Agent 开始认为这是普通差旅报销。

但验证发票时发现一张发票存在异常。

那么可能产生新的任务：

```text
发票异常
    ↓
要求用户补充证明
    ↓
用户提供新材料
    ↓
再次验证
    ↓
通过或进入人工复核
```

这些任务在最初可能并不存在。

**第四，任务存在跨系统、跨时间的依赖。**

例如：

Agent 已经调用 OA API 发起审批。

接下来需要等待部门负责人批准。

审批可能持续三天。

在此期间：

- Agent Session 可能已经结束。
- 用户可能关闭了电脑。
- OA 系统可能进行了升级。
- 审批人员可能拒绝申请。
- 企业报销政策可能发生变化。

但任务本身并没有消失。

**第五，操作执行成功不等于业务目标实现。**

例如：

```text
API 返回 HTTP 200
```

只能说明一次请求得到了成功响应。

它不能直接证明：

```text
报销申请已经创建成功
报销申请的内容正确
审批链配置正确
财务已经付款
用户已经收到款项
```

这些是不同层级的事实。

所以，**企业业务任务不能简单建模为一个 Action Sequence（动作序列）。**

它更接近：

> 一个持续演化的业务事项，系统必须在约束条件下，通过一系列可验证的行动，使它达到目标业务状态。

这与传统流程思维有本质区别。

---

## 2.2 真正需要统一的是五个问题

我认为，你的体系本质上是在同时解决五个不同层次的问题。

| 核心问题 | 本质 | 系统必须回答的问题 |
|---|---|---|
| 业务规范 | Normative | 什么必须做、允许做、禁止做？ |
| 工作规划 | Planning | 当前情况下应该如何完成任务？ |
| 持续执行 | Execution | 如何跨会话、跨系统可靠推进？ |
| 业务证明 | Verification | 如何证明行动与最终结果正确？ |
| 运行治理 | Governance | 谁负责、谁授权、如何追溯与改进？ |

现有技术通常只重点解决其中的一部分。

例如：

- **Prompt / Skill** 主要提供行为指导和能力知识。
- **Workflow Engine** 主要负责执行顺序、状态和任务调度。
- **Agent Framework** 主要负责模型推理、工具使用和任务规划。
- **Policy Engine** 主要负责确定哪些决策或行动符合规则。
- **Observability System** 主要负责记录系统运行情况。

但你想做的是把这些能力组合成一个具有统一业务语义的运行体系。

关键不是将这些技术简单拼接，而是要建立它们共同遵循的基础概念和执行规则。

---

## 2.3 一个关键转变：从 Procedure-Centric 到 Outcome-Centric

传统 SOP 通常强调：

> 按照什么步骤完成工作？

而你想构建的体系，应当更重视：

> 在哪些约束下，通过哪些被允许的行动，达到什么业务结果？

我们可以先用一个抽象表达式描述：

\[
Work = (Goal,\ Context,\ Constraints,\ Authority,\ Evidence)
\]

其中：

| 要素 | 含义 | 报销示例 |
|---|---|---|
| Goal | 希望达到的业务结果 | 完成一笔合规报销 |
| Context | 当前业务事实 | 用户、城市、职级、费用、发票 |
| Constraints | 必须遵守的约束 | 报销政策、审批规则、财务制度 |
| Authority | 允许采取哪些行动 | Agent 可以核验，但付款可能需要授权 |
| Evidence | 如何证明结果成立 | 验证结果、审批记录、付款凭证 |

这只是一个初步的业务抽象，不是完整的数据结构。

它带来一个重要变化：

**SOP 不再必须完整描述所有可能的步骤，而是可以定义完成业务目标时必须满足的条件。**

例如，一个报销 SOP 可以同时包含：

```text
目标：
    创建一笔符合公司政策的报销申请。

强制要求：
    必须验证发票。
    必须检查费用是否符合适用标准。
    必须检查是否重复报销。
    必须经过具备相应权限的审批人批准。

禁止行为：
    不得自行修改发票金额。
    不得绕过必要审批。
    不得将未经确认的费用标记为已付款。

条件性要求：
    特定费用类型需要额外证明。
    超过适用额度需要特殊审批。
    验证异常需要人工复核。

完成条件：
    报销申请已被正式受理，
    或根据该任务的目标，进一步完成审批和付款。
```

这里尤其要注意：最后一项必须由具体 Work 的目标决定。

“成功提交报销”“完成审批”和“款项到账”是三个不同的业务目标，不能混为一谈。

系统可以根据目标、约束和事实，生成不同的执行方案。

但不能仅仅因为 Agent 找到了一条更短的执行路径，就自动放弃强制要求。

这意味着：

> **SOP 可以从一份规定步骤的操作手册，发展为一份定义业务结果、义务、约束和验证标准的可执行规范。**

步骤仍然可以存在。

只是步骤不再是唯一的业务建模方式。

---

## 2.4 另一个关键转变：计划不应该等于任务本身

你提出了一个非常重要的设计：

> 在任务开始时，由 Agent 根据当前情况实例化具体工作流。

我认同这个方向，但认为需要进一步修正一个前提：

**不应该要求 Agent 在任务开始时，就确定整个生命周期中所有的执行步骤。**

原因很简单：很多业务信息只有在执行过程中才能获得。

例如：

```text
任务：报销差旅费用

当前已知：
    用户身份
    出差地点
    出差日期

当前未知：
    发票是否有效
    是否存在重复报销
    是否超过费用标准
    是否需要额外审批
```

此时生成的最优计划可能只是：

```text
收集费用材料
    ↓
验证基础信息
    ↓
根据验证结果继续决定
```

而不应该凭空生成一个看似完整、实际上依赖大量假设的工作流。

因此，我建议区分三个对象：

**Work Instance**

代表正在被处理的业务事项。

**Execution Plan**

代表系统目前决定采用的执行方案。

**Plan Revision**

代表执行过程中经过验证的计划调整。

它们的关系是：

```text
Work Instance
│
├── Goal
├── Business Context
├── Applicable Constraints
├── Current Business State
│
└── Execution Plan
      │
      ├── Revision 1
      │      ├── 收集材料
      │      └── 验证发票
      │
      ├── Revision 2
      │      ├── 收集材料
      │      ├── 验证发票
      │      ├── 人工复核
      │      └── 计算金额
      │
      └── Revision 3
             ├── ...
             └── 发起审批
```

注意，这里不是说执行计划可以任意修改。

已经执行的历史不能被覆盖。

已经产生外部业务效果的操作不能因重新规划而被当作没有发生。

计划变更必须受到同一套业务规则、权限和执行承诺的约束。

**任务是持续存在的，计划是随知识和事实逐步演化的。**

这是整个架构非常重要的一个基础判断。

---

## 2.5 第三个关键转变：Agent 不是最终的规则裁判

这里存在一个容易被忽略的问题。

假设 Agent 同时负责：

1. 读取 SOP。
2. 解释 SOP。
3. 生成工作流。
4. 判断工作流是否合规。
5. 执行工作流。
6. 判断自己是否执行成功。

那么从系统治理角度看，几乎所有权力都集中在同一个不确定性组件中。

这在企业自动化环境下风险很大。

因为 LLM 的能力特点是：

- 擅长理解自然语言。
- 擅长处理不完整的信息。
- 擅长提出执行方案。
- 擅长对复杂情况进行推理。

但这不意味着它应当自行决定：

- 是否可以跳过财务审批。
- 是否有权修改报销标准。
- 是否可以代表审批人批准申请。
- 某个具有法律或财务后果的操作是否获得了有效授权。

因此，一个原则非常重要：

> **Agent 可以提出行动，但不能仅凭自己的判断赋予行动合法性。**

这意味着系统至少需要区分：

```text
Proposal（行动提议）
          ↓
Validation（规则与条件验证）
          ↓
Authorization（权限与授权判断）
          ↓
Execution（实际执行）
          ↓
Verification（结果确认）
```

并不是每个动作都必须分别调用五个独立服务。

这些是必须在语义上区分的责任。

例如：

- LLM 可以判断一张发票看起来可能不合规。
- 确定性的发票验证服务负责返回正式验证结果。
- 规则系统判断异常是否必须人工复核。
- OA 系统中的有效审批记录证明审批已经完成。

即使 LLM 是整个流程的主要组织者，它也不应该成为唯一的事实来源和权限来源。

---

## 2.6 那么，“SOP Runtime”是不是合适的名称？

我认为它可以是一个子系统名称，但不一定适合作为整个体系的顶层名称。

我们可以比较几种抽象。

| 名称 | 强调的核心对象 | 优势 | 可能的局限 |
|---|---|---|---|
| SOP Runtime | 业务操作规范 | 非常贴近你的初始需求 | 容易被理解成 SOP 解释执行器 |
| Workflow Runtime | 工作流程 | 工程界容易理解 | 容易陷入步骤、节点、边的模型 |
| Agent Orchestrator | Agent 与工具 | 容易融入 Harness | 容易忽视业务状态与制度治理 |
| Case Management Runtime | 持续存在的业务事项 | 适合动态、长时、人工参与的业务 | Agent 自主规划和行动不是名称重点 |
| Task Runtime | 任务生命周期 | 简洁、通用 | Task 通常过于宽泛 |
| Governed Work Runtime | 受治理的业务工作 | 同时覆盖目标、规范、执行和责任 | 需要自行建立精确定义 |
| Enterprise Agent Execution Runtime | Agent 的企业级执行 | 技术定位明确 | 容易把 Agent 置于业务对象之上 |

这里值得注意的是，**Case Management 并不是凭空构造的概念**。

OMG 的 CMMN 标准已经提出了一种区别于固定流程的思路：以持续变化的业务事项和相关信息为中心，根据事件和情况推进工作，而不要求所有活动都有预先确定的顺序。[Object Management Group](https://www.omg.org/cmmn/index.htm?utm_source=chatgpt.com)

IBM 关于 Business Artifact 和 Guard-Stage-Milestone 的研究也提出了另一种思路：围绕业务对象本身的数据、生命周期、阶段进入条件和业务里程碑来组织执行，而不仅是描述任务序列。[research.ibm.com](https://research.ibm.com/publications/business-artifacts-with-guard-stage-milestone-lifecycles-managing-artifact-interactions-with-conditions-and-events?utm_source=chatgpt.com)

这两个方向都和你的需求存在深层联系。

但它们本身并不能完整回答：

> 当执行者变成能够自主规划、推理、使用工具、动态调整策略的 Agent 时，如何建立可信的业务执行机制？

所以，我目前更倾向于以下术语组合：

**顶层系统：Governed Agentic Work Runtime**

**核心运行对象：Work Instance / Business Case**

**业务规范对象：SOP Specification / Business Execution Contract**

**动态规划对象：Execution Plan**

**执行治理对象：Runtime Policy & Control**

其中，Business Execution Contract 是我建议重点研究的一个方向。

它表达的不是合同法意义上的合同，而是：

> 对一次业务工作必须满足的目标、规则、责任、授权边界和验收条件作出的可执行约定。

这有可能比单纯的 SOP Graph 更接近你真正需要表达的内容。

---

# 三、问题二：这个体系应该包含哪些核心概念？

我建议先不要按照软件模块划分，例如 Planner、Scheduler、Executor、Observer。

因为软件模块是实现方式，而你现在需要的是一套**独立于具体实现技术的领域模型（Domain Model）**。

如果基础概念定义得足够好，未来可以使用 Temporal、LangGraph、自研运行时，甚至多个运行时组合实现。

反过来，如果领域模型从一开始就被某种技术的 Node、Edge 或 State 结构绑定，系统很容易受到框架能力的限制。

我建议把核心概念划分为四个层次：

| 层次 | 核心关注点 | 主要概念 |
|---|---|---|
| 规范层 | 企业希望工作如何被完成 | Skill、SOP Specification、Policy、Capability |
| 实例层 | 当前到底在处理什么事情 | Work Instance、Context、Obligation、Execution Plan |
| 执行层 | 如何实际行动并取得结果 | Work Item、Action、Decision、Evidence |
| 治理层 | 如何保证可控、可恢复、可追责 | Authority、Event Ledger、Verification、Governance |

这里是概念层次，不意味着必须对应四个独立服务。

下面逐一拆解。

---

## 3.1 Skill：能力与业务规范的分发载体

首先重新定义 Skill。

你最初的设想是：

> 财务部门发布一个报销 Skill，里面包含 SOP。

这个方向是合理的。

但我不建议把 Skill 和 SOP 视为同一个概念。

**Skill 回答：Agent 如何获得完成某类工作的知识和能力？**

**SOP 回答：某类业务工作必须满足什么规范？**

两者有联系，但生命周期不一定相同。

例如：

```text
expense-reimbursement/
│
├── SKILL.md
│
├── sop/
│   └── reimbursement.md
│
├── policies/
│   ├── expense-policy.yaml
│   └── approval-policy.yaml
│
├── capabilities/
│   └── tools.yaml
│
└── references/
    └── invoice-guide.md
```

这只是为了说明职责而给出的示意性目录，并非建议立即采用的文件规范。

其中：

`SKILL.md` 可以描述如何发现和使用这项业务能力。

`reimbursement.md` 描述业务目标、工作约束和常规办理方法。

`expense-policy.yaml` 定义需要机器严格判断的费用规则。

`tools.yaml` 描述可以使用哪些业务系统能力。

当然，一个简单的 Skill 也可以把这些内容全部放在 `SKILL.md` 中。

文件如何拆分属于发布与组织问题，不应该决定运行时的核心抽象。

还有一个值得关注的问题：

**同一份企业财务政策可能被多个 Skill 引用。**

例如：

- 报销 Skill 需要差旅补贴政策。
- 差旅预订 Skill 也需要差旅补贴政策。
- 费用预算 Skill 同样需要这份政策。

因此，Policy 应该具备独立管理和复用的可能性，而不是永远只能作为 Skill 的内部文本存在。

### 初步定义

**Skill Package = 能力说明 + 业务规范引用 + 工具能力引用 + 相关知识**

它是交付和发现入口，不是持续运行的业务实例。

---

## 3.2 SOP Specification：业务工作的规范性定义

这是整个系统最值得深入研究的概念之一。

我建议你考虑一个问题：

**SOP 究竟是在规定步骤，还是在规定企业认可的工作方式？**

如果是后者，那么一个 SOP Specification 可以包含多种不同性质的内容。

### 第一类：Goal

定义工作希望产生什么结果。

例如：

```text
完成符合公司财务制度的费用报销申请。
```

### 第二类：Invariant

定义整个执行过程中不能被违反的约束。

例如：

```text
未经有效授权，不得发起财务付款。
```

Invariant 的特点是：

无论 Agent 选择什么执行路径，都必须满足。

### 第三类：Obligation Rule

定义在特定条件下必须履行什么义务。

例如：

```text
如果包含增值税发票，
则必须执行相应的发票验证。
```

它不是立即执行的动作，而是一个**条件性业务义务**。

### 第四类：Procedure

定义必须遵循的程序或推荐操作顺序。

例如：

```text
先完成费用核验，再发起正式审批。
```

有些 Procedure 是强制的，有些只是推荐做法。

两者必须区分。

### 第五类：Decision Rule

定义具体业务判断如何进行。

例如：

```text
根据职级、城市和住宿天数确定适用住宿标准。
```

这里不一定适合由 LLM 直接计算。

它可能更适合被编译为规则表达式，或者调用专门的业务规则服务。

OMG 的 DMN 标准就是将业务决策和规则独立建模的一种成熟方法，支持通过决策模型、规则表等方式表达可执行的业务判断。[Object Management Group](https://www.omg.org/dmn/?utm_source=chatgpt.com)

### 第六类：Completion Criteria

定义什么时候可以认为工作完成。

例如：

```text
报销单创建成功。
报销单已获得正式受理。
不存在未解决的强制校验异常。
```

这里有一个重要区别：

**Completion Criteria 描述业务完成条件，而不是工作流最后一个节点已经执行。**

两者不能混淆。

### 我建议的 SOP 抽象

因此，我们可以暂时定义：

\[
SOP = (Goals,\ Rules,\ Obligations,\ Procedures,\ Decisions,\ Completion)
\]

这比将 SOP 直接定义为 Graph 更具有表达能力。

Graph 可以成为它的一种编译产物或执行视图，但不必是唯一的规范表示。

---

## 3.3 Work Instance：整个体系真正的核心对象

我认为这是最重要的实体。

假设用户说：

> 帮我报销上海出差的费用。

系统识别对应 Skill 之后，应该创建一个独立的 Work Instance。

例如：

```yaml
work_id: WRK-2026-00123

type: expense_reimbursement

requester: employee-1024

goal:
  type: reimbursement_submission
  status: pending

sop:
  id: expense-reimbursement
  version: 3.2

status: active

context:
  destination: Shanghai
  expense_period:
    start: 2026-10-01
    end: 2026-10-04

plan:
  revision: 1
```

这里的字段只是展示概念关系，不是最终 Schema。

这个 Work Instance 应当具有几个核心特征。

**第一，它具有独立身份。**

它不是某个 Conversation ID。

也不是某个 Agent Run ID。

一个 Work Instance 可以经历：

```text
Agent Session A
      ↓
等待用户补充材料
      ↓
Agent Session B
      ↓
等待 OA 审批
      ↓
外部审批回调
      ↓
Agent Session C
      ↓
完成
```

但始终属于同一个 Work。

**第二，它拥有自己的持久业务状态。**

即使没有 Agent 正在运行，Work 仍然存在。

它可能处于：

- 正在处理。
- 等待外部信息。
- 等待人工审批。
- 需要干预。
- 已完成。
- 已终止。

这些只是粗粒度状态，不应该成为描述全部业务进展的唯一方式。

**第三，它维护业务责任。**

例如：

- 谁发起了任务？
- 当前由谁负责？
- 哪些事情由 Agent 执行？
- 哪些事情必须由人类批准？
- 什么情况下需要移交？

**第四，它具有独立的生命周期。**

Work 不应该随着一次 Agent 推理结束而消失。

### 一个非常重要的区分

```text
Work Instance ≠ Agent Session

Work Instance ≠ Execution Plan

Work Instance ≠ Workflow Execution

Work Instance ≠ Conversation
```

我建议把 Work Instance 当作整个运行体系的主要聚合对象和生命周期边界。

但需要注意，Work 是一个业务概念，并不意味着系统只能通过单个数据库聚合来实现它。

---

## 3.4 Context：动态变化且具有来源的业务事实

传统 Agent 系统经常将 Context 理解为模型上下文。

但在你要做的体系里，这远远不够。

**业务 Context 应该是一个可持久化、可更新、可验证、具有来源和时间属性的事实集合。**

例如：

```text
员工职级：P6
员工部门：研发部
出差城市：上海
出差时间：4天
发票金额：2800元
部门负责人：某审批人
```

这些看起来只是数据。

但实际情况更复杂。

例如：

员工职级从哪里获得？

是用户自己告诉 Agent 的？

还是 HR 系统返回的？

职级信息是什么时候读取的？

这笔报销应该采用当前职级，还是费用发生时的职级？

因此，一个事实最好不仅包含 Value，还要能够表达：

```text
Fact
├── Name
├── Value
├── Source
├── ObservedAt
├── EffectiveAt
├── Confidence / Verification
└── Version
```

不一定所有字段都必须存在，但必须有表达这些语义的能力。

这会直接影响 SOP 实例化的可靠性。

### 为什么 Context 不应只是 JSON 参数？

因为业务事实可能发生变化，也可能相互冲突。

例如：

```text
Agent 从用户输入中获得：
    部门 = 研发部

Agent 从 HR 系统获得：
    部门 = 产品部
```

这不是简单地用新值覆盖旧值就能解决的。

系统需要知道事实来源、适用时间以及哪个来源对当前业务判断具有权威性。

因此我建议：

> Context 是 Work 对当前业务世界的受管理认知，而不是一次性传入 Planner 的参数。

---

## 3.5 Obligation：可能比 Workflow Node 更重要的概念

这是我认为最值得你关注的设计点之一。

**Obligation 可以翻译为“履行义务”或“必须满足的业务要求”。**

它与 Task、Step、Action 都不一样。

举个例子。

公司规定：

> 所有报销必须经过发票验证。

这条规则真正表达的是：

```text
在报销完成之前，
必须存在有效的发票验证结果。
```

而不是：

```text
一定要执行一个名为
validate_invoice
的 Workflow Node。
```

为什么区别很重要？

假设用户提交报销时，OA 系统已经完成了发票验证。

那么是否还需要让 Agent 再调用一次发票验证 API？

未必。

如果已有验证记录仍然有效、覆盖当前发票，且符合适用制度，就可能不需要重复执行。

这意味着：

**Obligation 关心的是业务义务是否被有效履行，而不是某个步骤是否被执行。**

这是一个重要的抽象提升。

### Obligation 的例子

```text
OBL-001
    所有发票必须验证有效。

OBL-002
    不得存在重复报销。

OBL-003
    超过适用额度必须获得额外审批。

OBL-004
    用户必须确认最终提交内容。

OBL-005
    正式申请必须由 OA 系统受理。
```

其中一些义务在任务创建时就存在。

另一些义务只有条件成立时才会被激活。

例如：

```text
IF expense_exceeds_limit
THEN activate additional_approval_obligation
```

Agent 可以通过不同方式履行这些义务。

但系统必须知道哪些义务尚未满足。

### Obligation 的生命周期

它可以具有如下语义：

```text
Not Applicable
     或
Required
    ↓
Pending
    ↓
In Progress
    ↓
Satisfied
```

也可能进入：

```text
Failed
Blocked
Disputed
```

需要注意，“豁免”也必须有明确的制度依据与授权，不能让 Agent 自行把未履行的义务标记为无需履行。

### Obligation 与 Action 的根本区别

| Obligation | Action |
|---|---|
| 必须满足什么条件 | 实际执行什么操作 |
| 描述业务责任 | 描述执行行为 |
| 可以长期存在 | 通常是一次具体尝试 |
| 不依赖特定工具 | 往往需要具体执行能力 |
| 由证据证明已经履行 | 产生执行结果和证据 |

这个区别很有价值。

因为它为你提供了一个介于“业务规范”和“动态执行计划”之间的稳定抽象。

**业务义务相对稳定，履行义务的执行路径可以变化。**

这可能成为动态 SOP 系统的重要设计基础。

---

## 3.6 Execution Plan：针对当前任务的具体履行策略

在前面的基础上，我们可以重新定义 Workflow 实例化。

Agent 并不是简单将 SOP Graph 中的分支裁剪掉。

它实际上是在求解一个问题：

> 已知当前目标、事实、约束、权限和待履行义务，应该采取哪些行动，按照怎样的依赖关系推进，才能完成工作？

因此，一个 Execution Plan 至少要能够描述：

- 当前计划履行哪些义务。
- 需要执行哪些 Work Item。
- Work Item 的依赖条件。
- 哪些事项允许并行。
- 哪些事项等待外部事件。
- 什么时候需要进一步规划。
- 哪些行动必须经过验证或批准。

例如：

```text
Goal：正式提交报销申请

Obligations：
    O1 发票验证
    O2 重复报销检查
    O3 费用标准检查
    O4 用户确认
    O5 OA 正式受理

Execution Plan：

    收集发票
        │
        ├───────────────┐
        ↓               ↓
    发票验证         重复报销检查
        │               │
        └───────┬───────┘
                ↓
           费用标准检查
                ↓
           用户确认
                ↓
           创建 OA 申请
                ↓
           查询受理状态
                ↓
             完成
```

但如果发票验证出现异常，计划就需要调整。

```text
发票验证
    ↓
发现异常
    ↓
产生新的处理义务
    ↓
暂停相关后续操作
    ↓
生成计划修订
    ↓
用户补充材料
    ↓
重新验证
```

这里很重要的一点是：

**动态计划不仅可以增加执行步骤，也可以重新选择履行义务的方法。**

比如已有合法有效的验证结果时，可以引用既有证据，而不是重复调用工具。

### 我建议计划具有三个性质

**1. 允许部分实例化**

不需要提前确定所有步骤。

**2. 允许受控修订**

新事实可以触发计划调整。

**3. 已有执行承诺不可随意抹除**

尤其是已经调用外部 API、获得审批或发生资金变化的操作。

这里可以借鉴数据库的提交语义，但不能把整个长周期业务任务等同于一个 ACID 事务。

更合适的理解是：

> Plan 是一个持续演化、但受业务承诺约束的执行策略。

---

## 3.7 Work Item 与 Action：区分待办工作和实际尝试

我建议进一步拆分两个概念。

### Work Item

表示一项需要完成的工作。

例如：

```text
验证发票 INV-001 是否有效。
```

它可能由 Agent 执行，也可能由人类、业务系统或其他 Agent 执行。

### Action

表示为完成该项工作而进行的一次具体行动。

例如：

```text
调用税务发票验证 API。
```

一个 Work Item 可能对应多次 Action。

```text
Work Item：验证发票

    Action Attempt 1
        API 超时

    Action Attempt 2
        查询成功
        验证结果：有效
```

如果不区分 Work Item 和 Action，很容易出现一个问题：

系统无法准确判断重试是在恢复同一项业务工作，还是无意中重复发起新的业务操作。

尤其是涉及：

- 发起审批。
- 创建订单。
- 发送付款请求。
- 修改账户。
- 创建正式单据。

这类带有外部副作用的 Action。

系统必须具备：

- 幂等键或等价的去重机制。
- 外部操作标识。
- 操作结果查询。
- 超时后状态核实。
- 必要时执行补偿动作。

还需要承认一个现实限制：

**并非所有外部业务系统都能提供真正的端到端 Exactly-Once 语义。**

系统不能因为一次调用超时，就假设没有发生业务效果，然后盲目重试。

微软关于 Event Sourcing 的架构指南同样强调，事件重复投递需要通过幂等处理来避免重复业务副作用。[Microsoft Learn](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing?utm_source=chatgpt.com)

---

## 3.8 Evidence：业务正确性的证明

我认为 Evidence 应当成为核心实体，而不是日志的附属字段。

例如：

Agent 调用发票验证 API。

返回：

```json
{
  "invoice_id": "INV-001",
  "valid": true,
  "verification_id": "VERIFY-123"
}
```

这个返回值可以作为 Evidence。

但它仍需要回答：

- 验证的是不是当前报销对应的发票？
- 验证结果是否来自可信系统？
- 验证发生于什么时间？
- 结果是否已经失效？
- 该结果究竟能证明哪个 Obligation 已满足？

因此，Evidence 与 Obligation 之间应该有明确关联。

```text
Obligation:
    发票必须验证有效
         │
         │ satisfied_by
         ↓
Evidence:
    发票验证记录
    来源：验证服务
    结果：有效
    时间：...
    对象：INV-001
```

它产生一个非常重要的能力：

**系统可以不依赖 Agent 的自然语言解释，判断一项业务要求是否已经得到满足。**

当然，并不是所有证据都能完全通过确定性规则验证。

例如某些材料的合理性、特殊费用的必要性，可能需要语义判断或人工确认。

因此 Evidence 应该支持不同验证级别，而不是简单地将所有 LLM 判断视为等同于正式业务证明。

### 一个值得考虑的完成模型

我们可以初步写成：

\[
Complete(W)
=
GoalSatisfied(W)
\land
ObligationsDischarged(W)
\land
NoBlockingViolation(W)
\]

也就是：

一个 Work 完成，不仅要求达成目标，还要求强制义务得到有效履行，并且不存在阻止完成的违规情况。

在这个模型中，Completion 不再由执行计划是否走到最后一步决定。

而由业务状态与证据决定。

这是非常值得深入的架构方向。

---

## 3.9 Authority：行动权与责任归属

企业 Agent 系统不能只知道“有哪些工具”。

还必须知道：

**在什么条件下，哪个主体有权执行什么操作。**

例如：

```text
读取报销政策：
    Agent 可以自动执行。

查询用户历史报销：
    需要具备相应数据访问权限。

创建报销草稿：
    可能允许 Agent 自动执行。

正式提交报销：
    可能要求用户确认。

审批报销：
    必须由具备审批权限的主体操作。

发起付款：
    必须遵守财务支付授权机制。
```

这里需要区分三个概念：

**Capability：能不能做。**

例如工具支持 `approve_expense`。

**Authority：有没有权做。**

例如当前 Agent 没有报销审批权。

**Consent / Approval：这次行动是否获得了必要授权。**

例如用户确认提交当前版本的报销单。

三个概念不能混淆。

尤其要避免：

```text
Agent 能调用某个工具
    ⇒
Agent 有权执行该业务操作
```

这是错误的推导。

在执行时，可以通过类似 Policy Decision Point 的机制，对行动进行授权判断。

OPA 这样的策略引擎已经提供了独立于应用逻辑的策略评估和决策日志能力，可以作为此类设计的参考。[Open Policy Agent](https://www.openpolicyagent.org/docs/policy-language?utm_source=chatgpt.com)

但 Authority 不只关心技术权限，还涉及代理授权、企业审批、职责分离和用户确认的有效范围。

---

## 3.10 Event Ledger：业务运行历史，而不仅是 Agent Trace

你提到希望记录、恢复、分析和优化运行过程。

这里我建议同时保留两种不同的观察视角。

### 第一种：Technical Trace

关注系统怎么运行。

例如：

```text
LLM Request
    ↓
LLM Response
    ↓
Tool Call
    ↓
API Response
```

它适合：

- 调试。
- 性能分析。
- Token 成本分析。
- 模型质量分析。
- 工具调用问题定位。

OpenTelemetry 当前的 GenAI 语义规范已经包含 Agent、Workflow、Plan 和 Tool Execution 等操作的追踪定义，可以作为技术追踪的参考。[GitHub](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md?utm_source=chatgpt.com)

### 第二种：Business Event Ledger

关注业务中发生了什么。

例如：

```text
WorkCreated

SOPBound

ObligationActivated

PlanProposed

PlanValidated

InvoiceVerificationRequested

InvoiceVerified

UserConfirmationRequested

UserConfirmed

ExpenseSubmissionRequested

ExpenseSubmitted

WorkCompleted
```

它适合：

- 业务审计。
- 责任追溯。
- 过程一致性验证。
- 工作状态重建。
- 统计分析。
- SOP 改进。

技术 Trace 和业务事件应该关联，但不宜混成一种记录。

例如：

```text
Business Event:
    ExpenseSubmitted

Technical Trace:
    调用了哪个 API
    使用哪个凭据
    耗时多少
    是否发生重试
    返回了什么
```

业务历史最好采用追加记录的方式保存，并为当前状态生成投影视图。

但这并不意味着整个系统所有数据都必须采用 Event Sourcing。

它更适合优先用于需要审计、恢复和因果分析的关键业务生命周期。

---

# 四、核心概念之间应该是什么关系？

上面介绍了不少概念。

但真正重要的是它们之间的关系。

我建议先建立下面这张概念关系图。

```text
                企业业务知识与规范
                        │
            ┌───────────┴───────────┐
            │                       │
        Skill Package         Policy / Rules
            │                       │
            ▼                       │
     SOP Specification              │
            │                       │
            └───────────┬───────────┘
                        │
                   业务请求
                        │
                        ▼
                ┌─────────────┐
                │Work Instance│
                └─────────────┘
                        │
          ┌─────────────┼──────────────┐
          │             │              │
          ▼             ▼              ▼
        Goal          Context       Authority
          │             │              │
          └─────────────┼──────────────┘
                        │
                        ▼
              Obligation Evaluation
                        │
                        ▼
                 Obligations
                        │
                        ▼
                 Agent Planning
                        │
                        ▼
                 Execution Plan
                        │
                        ▼
                    Work Items
                        │
                        ▼
                Action Proposals
                        │
                        ▼
              Policy / Auth Check
                        │
                        ▼
                    Actions
                        │
                        ▼
               External Outcomes
                        │
                        ▼
                    Evidence
                        │
                        ▼
                 Verification
                        │
              ┌─────────┴─────────┐
              │                   │
         义务已满足           新事实或异常
              │                   │
              ▼                   ▼
         更新 Work           重新评估义务
              │                   │
              │                   ▼
              │               修订 Plan
              │                   │
              └─────────┬─────────┘
                        │
                        ▼
               Completion Check
                        │
                        ▼
                   Work Closed
```

与此同时：

```text
所有关键业务事件
        │
        ▼
    Event Ledger
        │
        ├── 状态恢复
        ├── 审计追踪
        ├── 运行分析
        ├── 合规检查
        └── SOP 优化建议
```

这张图表达的是逻辑关系，不是实际调用顺序。

实际运行中，Obligation Evaluation、Planning 和 Verification 都可能被反复触发。

核心思想是：

**Work 是中心，SOP 提供规范，Obligation 描述业务责任，Plan 描述履行策略，Action 产生实际影响，Evidence 证明结果，Ledger 保留历史。**

---

# 五、用一次完整报销说明这些概念如何协作

假设某位员工提出：

> 帮我报销上周上海出差产生的费用。

为了说明模型，我们假设企业制度要求核验发票、检查额度，并在正式提交前取得用户确认。这里的规则只是示例，不代表任何具体公司的真实制度。

### 阶段一：建立工作事项

系统创建：

```text
Work ID：WRK-001

Goal：
    完成报销申请的正式提交

Status：
    Active

SOP：
    Expense Reimbursement v3.2
```

此时还不需要一个完整的固定流程。

### 阶段二：获取业务事实

系统查询：

```text
HR：
    当前部门
    员工职级

Travel System：
    出差记录
    出差批准信息

Expense System：
    历史报销记录
```

Context 随之逐步完善。

### 阶段三：绑定规则并产生义务

假设结合现有事实和适用规则，产生：

```text
O1：验证发票
O2：检查重复报销
O3：计算允许报销金额
O4：获取用户确认
O5：提交正式申请
O6：核实系统受理结果
```

这些是业务要求。

还不是具体操作序列。

### 阶段四：生成执行计划

Agent 根据当前情况生成：

```text
P1：
    读取发票
    ↓
    并行验证发票与检查重复报销
    ↓
    计算报销金额
    ↓
    用户确认
    ↓
    提交申请
    ↓
    核实受理状态
```

系统验证计划是否覆盖强制义务，以及是否存在违规步骤。

通过后进入执行。

### 阶段五：发现新情况

发票验证返回：

```text
Invoice A：有效

Invoice B：存在异常
```

这是新的业务事实。

系统据此激活新的 Obligation：

```text
O7：处理异常发票
```

此时并不应该重新创建一个 Work Instance。

而是：

```text
同一个 Work Instance

    Context 更新
         ↓
    Obligation 更新
         ↓
    Plan Revision 2
```

新计划可能变成：

```text
等待用户补充材料
    ↓
重新验证发票 B
    ↓
继续计算金额
```

### 阶段六：等待用户

系统向用户发送补充材料请求。

此时：

```text
Work Status：
    Waiting for User
```

Agent 不需要持续运行。

可以在后台持久保存业务状态，等待用户提交材料后再次被调度。

在这里，LangGraph 的持久化 Checkpoint 和 Temporal 的持久 Workflow 都可以提供部分底层技术能力，但它们解决的主要是计算及执行状态如何持久化、恢复和协调，并不天然等同于完整的企业业务责任模型。[LangChain AI](https://langchain-ai.github.io/langgraph/concepts/durable_execution/?utm_source=chatgpt.com)

### 阶段七：继续执行

三天后，用户提交材料。

系统：

```text
收到用户材料
    ↓
更新 Context
    ↓
恢复 Work
    ↓
重新评估相关义务
    ↓
继续执行
```

这里也不需要恢复原来的完整 LLM 对话。

Agent 只需要能够获取当前工作所需的：

- 已确认事实。
- 尚未解决的义务。
- 当前有效执行计划。
- 已完成行动。
- 相关证据。
- 可执行的下一步。

这可以显著降低系统对长期对话历史的依赖。

### 阶段八：完成任务

最终：

```text
O1 满足
O2 满足
O3 满足
O4 满足
O5 满足
O6 满足
O7 满足
```

系统根据 Evidence 验证：

```text
目标达成
强制义务已履行
没有阻止完成的异常
```

然后：

```text
Work Status：
    Completed
```

整个运行历史仍然保留。

---

# 六、这里还存在三个特别重要的架构问题

前面的概念模型已经形成了基础，但我认为还有三个问题会直接决定这套体系的上限。

## 6.1 什么必须固定，什么可以动态？

你希望 SOP 实例化后保持稳定执行，同时允许动态调整。

这实际上存在一个矛盾：

如果所有步骤都固定，就无法充分利用 Agent 的灵活性。

如果所有步骤都允许修改，就无法保证执行稳定性。

所以我建议不要以“整个 Workflow 是否可以修改”为核心问题。

而是将约束划分为不同性质：

| 对象 | 是否允许变化 | 变化边界 |
|---|---|---|
| 已发生的业务事实 | 不能覆盖历史 | 可以追加更正或更新事实 |
| 强制业务规则 | Agent 不可自行修改 | 由政策管理与生效机制控制 |
| 已产生的外部业务效果 | 不可假装撤销 | 需要真实补偿或纠正 |
| 已履行的义务 | 可以重新评估有效性 | 依赖证据是否仍然有效 |
| 尚未执行的计划 | 可以调整 | 必须通过适用规则校验 |
| 执行动作选择 | 可以调整 | 必须满足权限和风险要求 |
| 业务目标 | 特定情况下可以变更 | 需要按任务契约重新授权 |

因此，系统要保证的不是：

> 整个 Workflow 永远不变。

而是：

> **在允许执行策略变化的同时，维持业务约束、授权边界和已发生事实的一致性。**

这是非常不同的稳定性定义。

---

## 6.2 SOP 发生变更时，运行中的 Work 怎么办？

这是长时任务运行时无法回避的问题。

假设：

```text
10月1日：

报销 SOP v3.2

员工创建了一笔报销任务。
```

然后：

```text
10月3日：

财务发布 SOP v3.3
提高了部分费用的审核要求。
```

但报销任务还没有完成。

应该怎么办？

可能存在三种合理策略：

**策略 A：版本锁定**

继续按照创建时绑定的 SOP v3.2 执行。

**策略 B：新规则立即适用**

重新评估当前 Work，应用 v3.3。

**策略 C：按规则的适用时间和业务阶段决定**

例如费用标准按费用发生日期适用，而新的安全验证要求可能对未提交的申请立即生效。

我认为第三种情况在真实企业环境中往往更加重要。

这也说明：

**SOP Version 和 Policy Effective Version 不应该简单地视为同一个概念。**

而且版本更新不等于要求所有正在执行的 Work 自动重新规划。

这里需要显式的迁移与兼容性规则。

---

## 6.3 记录与优化的对象应该是什么？

如果主要记录：

```text
Agent 调用了多少次 LLM？
平均耗时是多少？
消耗了多少 Token？
```

那么优化的主要是 AI 系统效率。

但你的目标明显不止于此。

还应该能够回答：

- 哪些 Obligation 最容易产生阻塞？
- 哪类发票导致最多人工干预？
- 哪些审批路径等待时间最长？
- 哪些计划经常需要修订？
- 哪些 SOP 规则容易出现解释分歧？
- 哪些工具调用在失败后需要人工恢复？
- 哪些步骤事实上没有必要重复执行？

这意味着未来的分析单位不应该只有 Agent Trace。

还应包含：

```text
Work
Obligation
Plan Revision
Work Item
Action
Business Event
Evidence
Policy Decision
```

例如：

你可能发现 30% 的报销任务都因为同一种材料缺失而发生计划修订。

那么真正应该优化的未必是 Planner 的 Prompt。

而可能是：

**修改 SOP，在任务初期就要求收集该材料。**

这才是真正的业务流程持续优化。

这里也产生了一条清晰的反馈路径：

```text
SOP Definition
      ↓
Work Instantiation
      ↓
Execution
      ↓
Business Events
      ↓
Operational Analysis
      ↓
Improvement Proposal
      ↓
SOP Review & Publication
      ↓
New SOP Version
```

需要强调，生产运行数据可以生成优化建议，但不能默认直接修改正式 SOP。

企业规则变更应该保留明确的审批、测试与发布机制。

---

# 七、我建议你采用的最小核心概念模型

经过前面的分析，如果现在需要压缩概念数量，用于后续架构研究，我会保留以下 **12 个核心概念**。

| 概念 | 简要定义 | 核心职责 |
|---|---|---|
| **1. Skill** | Agent 发现和加载某项业务能力的载体 | 能力分发 |
| **2. SOP Specification** | 企业认可的业务工作规范 | 定义目标、义务、程序和完成标准 |
| **3. Policy** | 可适用、可判定的业务规则与限制 | 约束决策和执行 |
| **4. Work Instance** | 持续存在的具体业务事项 | 承载完整生命周期 |
| **5. Context** | 具有来源与时效属性的业务事实 | 支撑判断和规划 |
| **6. Obligation** | 必须履行的业务要求 | 建立稳定的业务责任 |
| **7. Execution Plan** | 当前履行义务的执行策略 | 组织动态执行 |
| **8. Work Item** | 一项需要完成的具体工作 | 管理工作单元 |
| **9. Action** | 一次具体的执行尝试 | 调用实际能力并产生效果 |
| **10. Authority** | 行动所需的权限与授权 | 控制可执行边界 |
| **11. Evidence** | 可以验证业务事实与义务履行的证明 | 支撑结果验证 |
| **12. Event Ledger** | 追加记录的业务运行历史 | 支撑恢复、审计与优化 |

其中，我特别建议把以下六个概念作为第一阶段的架构研究重点：

**SOP Specification → Work Instance → Obligation → Execution Plan → Action → Evidence**

它们构成了这套体系区别于普通 Agent Framework 和传统 Workflow Engine 的核心语义链条。

其余概念则提供必要的业务上下文、权限、持久性和治理能力。

---

# 八、一个值得进一步探索的方向：以 Obligation 为中心，而不是以 Graph 为中心

最后，我想提出一个可能具有架构突破意义的假设。

传统工作流的核心问题是：

> 下一个应该执行哪个节点？

但对于你所描述的系统，更基础的问题可能是：

> **当前还有哪些业务责任尚未履行？系统具备哪些已验证的事实？下一步采取什么行动才能安全地推进这些责任？**

如果采用这种思路，运行机制可能不是：

```text
Execute Next Node
        ↓
Execute Next Node
        ↓
Execute Next Node
```

而是：

```text
Observe Current Work
        ↓
Evaluate Outstanding Obligations
        ↓
Identify Available Actions
        ↓
Propose Next Work
        ↓
Validate Against Constraints
        ↓
Execute
        ↓
Collect Evidence
        ↓
Update Work
        ↓
Repeat
```

但这里不应该把 Obligation 当成唯一的调度依据。

因为真实工作还具有依赖关系、资源限制、截止时间、效率目标和执行承诺。

因此我更倾向于一个组合模型：

### 相对稳定的业务约束

```text
Goal
Policy
Obligation
Authority
```

### 可动态演化的执行策略

```text
Plan
Work Item
Action Selection
```

### 持续积累的业务事实

```text
Context
Evidence
Business Events
```

这三个部分共同驱动一个长期存在的 Work Instance。

在这种模型下：

- Graph 是执行计划的一种表示。
- 状态机是某些对象生命周期的实现工具。
- 规则引擎是 Policy 的一种实现。
- LLM 是推理与规划组件。
- Workflow Engine 可以是底层持久执行设施。
- SOP Runtime 则可以是负责解释规范、生成义务和验证履行情况的子系统。

但没有一个单独的技术框架天然拥有整个系统的业务语义。

---

# 九、我的阶段性结论

如果完全从第一性原理出发，我会把你想做的事情重新定义为：

> **构建一种面向 AI Agent 的企业级受约束工作执行模型，使业务人员可以声明工作目标、业务义务、执行约束和验收标准，由 Agent 根据动态业务事实自主规划并推进工作，同时通过持久化状态、权限控制、证据验证和事件记录，确保整个工作生命周期的可靠性、可解释性与可治理性。**

它可以有一个进一步精炼的表达：

**From SOP as Instructions to SOP as Executable Business Commitments.**

即：

**从“作为操作说明的 SOP”，转向“作为可执行业务承诺的 SOP”。**

这个方向比“把 SOP 动态编译成 DAG”更开放。

它并不否定 DAG、Workflow Engine、状态机或各种 Agent Framework 的价值，而是把它们放到更加基础的业务模型之下。

另外，研究中我认为应该始终保持三个关键区分：

**第一，Work 与 Plan 分离。**

Work 代表持续存在的业务责任；Plan 只是当前执行策略。

**第二，Obligation 与 Action 分离。**

Obligation 规定必须满足什么；Action 是履行义务的具体行为。

**第三，Execution 与 Verification 分离。**

Agent 执行了某件事情，不代表该事情已经产生预期的业务结果，更不代表企业义务已经有效履行。

---

## 下一步最值得研究的不是工具选型，而是“执行语义”

基于上述模型，我认为接下来有一个非常关键、也最可能决定整个架构成败的问题：

**SOP Specification 如何转化为可被运行时理解和执行的 Work Contract、Obligation 与 Execution Plan？**

这里至少涉及三种可能的设计路线：

| 路线 | 核心思想 | 值得研究的问题 |
|---|---|---|
| **Plan-Centric** | Agent 生成具体计划，Runtime 验证并执行 | 怎样实现受控动态修订？ |
| **Obligation-Centric** | Runtime 管理业务义务，Agent 自主选择履行方式 | 怎样防止执行过程缺乏整体协调？ |
| **Contract-Centric** | 用目标、约束、授权、证据构成可执行契约 | 怎样将声明式规范转化为可操作的执行语义？ |

这三种路线并不一定互斥。

我的初步倾向是：

**采用 Contract-Centric 的业务语义、Obligation-Centric 的责任管理，以及 Plan-Centric 的执行组织。**

换句话说：

> **Contract 定义什么是正确的，Obligation 定义什么还必须完成，Plan 定义现在准备怎么完成，Runtime 负责确保整个过程可信地推进。**

这或许就是你的 SOP 体系最值得继续验证的核心架构假设。