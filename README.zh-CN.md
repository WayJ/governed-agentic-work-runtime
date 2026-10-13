# Governed Work Runtime

**让 Agent 自主规划，让每次业务行动都有依据。**

面向长期业务工作的持久运行时：Agent 提议行动，规则决定能否执行，证据证明是否完成。

[English](README.md) · [核心语义](docs/RFC-001-core-semantics.md) · [交互协议](docs/RFC-003-runtime-protocol.md) · [验证覆盖](docs/verification.md) · [贡献指南](CONTRIBUTING.md)

当前是本地参考原型，使用 Python 3.9+ 和标准库，Apache-2.0 许可证，无第三方运行依赖。报销制度与 OA 均为演示，不需要模型 API Key。

## 一条命令体验真实崩溃恢复

```bash
git clone https://github.com/WayJ/governed-agentic-work-runtime.git
cd governed-agentic-work-runtime
python3 -m work_runtime demo
```

演示会完成以下过程：

1. Agent 提议提交，被“缺少特别批准”阻断。
2. 工作进入持久等待，Agent 无需持续在线。
3. 财务批准当前版本内容，Runtime 保存提交意图。
4. 独立模拟 OA 受理申请后，工作进程直接退出，尚未保存响应。
5. 重启 Runtime，通过原业务键查回受理记录。
6. 验收完成；模拟 OA 数据库中的受理申请数量严格为 1。

每次运行创建新的临时目录，保留 SQLite 状态和业务事件；输出提供查看命令。

## 这套模型解决什么

业务工作可能跨越数天、多个会话和外部系统。计划可以修订，但必须履行的要求不会因删掉计划步骤而消失；一次调用超时，也不能意味着现实世界没有发生操作。

Runtime 管理 Work 的持久状态、规则评估、命令回执、操作身份、证据和等待。Agent 基于这些状态提出下一步，而不直接修改“已批准”或“已完成”。

当前已实现两层操作去重、外部事件去重、对象版本匹配、未知条件阻断、等待恢复、派发前授权检查，以及外部结果核实。报销规则可通过 `Policy` 接口替换；工具执行与结果查询通过 `Adapter` 接口接入。

当前接口只面向受信任的本地应用代码。示例中的主体名称和权限配置不构成远程身份认证。分布式执行、多租户授权、规范发布、证据撤销、取消与补偿尚未实现；完整范围见[验证报告](docs/verification.md)。

## 本地验证

```bash
python3 -m unittest discover -s tests -v             # 测试门禁
python3 scripts/check_docs.py                        # 文档门禁：本地链接可解析
python3 -m work_runtime demo                         # 演示门禁：真实崩溃恢复
python3 -m compileall -q work_runtime tests scripts  # 语法门禁
python3 scripts/verify_install.py                    # 全新虚拟环境安装，并在仓库外运行双入口演示
```

`scripts/verify_install.py` 在临时目录创建全新虚拟环境并真实安装本包：断言导入来自该环境而非当前检出、未安装任何第三方依赖，并在仓库外分别运行模块与控制台入口演示，最终从模拟 OA 数据库独立核对受理申请数量严格为 1。安装阶段需要 pip 索引访问以获取构建后端。

测试包含实际子进程崩溃、并发重复请求、单据变化后旧批准失效、跨 Work 发票唯一约束，以及无法查询外部结果时转人工介入。协议验收项 P01–P15 中 14 项由命名测试覆盖，P13（分布式租约）明确延期；逐项证据见[验证报告](docs/verification.md)。

英文首页提供 Python 使用示例。后续按[路线图](docs/roadmap.md)推进适配器协议、Agent 接入、取消补偿和规范编写体验；欢迎通过可复现反例挑战当前保证。
