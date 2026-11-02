# 智能体操作系统与自进化运行时

产品介绍见 [README](../README.md)。本文记录真实执行范围、恢复协议、独立评测与工程依据。

## 可以执行的操作

网页侧栏的**执行模式**调用 `POST /api/agent/run`；**策略模式**调用 `/api/agent/plan`，只生成计划。

| 能力 | 工具 | 服务端约束 |
| --- | --- | --- |
| 读取工作区 | `workspace.read` | 仅允许声明的业务分区，过滤用户级决策数据 |
| 打开站内页面 | `page.navigate` | 使用固定路由白名单，由浏览器执行并反馈 |
| 打开搜索、时间或渠道筛选，定位活动名称 | `ui.control` | 使用固定命令白名单，浏览器核对可见状态或焦点 |
| 创建活动草案 | `campaign.draft` | 先读取工作区，再取得当前用户的草案授权，复用业务参数校验 |
| 请求人工审批 | `approval.review` | 中断任务并导航到审批页，模型不能批准 |

模型返回严格结构化的单步提案。服务端校验工具名、参数、重复调用与步数预算；模型没有原始 JavaScript、任意 DOM、Shell、外站浏览器、活动发布或外部发送权限。Demo 模式不调用外部模型；未配置模型时返回 `model_unavailable`，不会编造执行结果。

## 持久化检查点与恢复

`RunJournal` 和 `RecoverableOperator` 复用原有 `GrowthOperator` 的响应校验与 `GrowthTools`，不建立另一套工具目录。`PostgresAgentBackend` 复用产品的 PostgreSQL 连接池。

- 配置 `GROWTHEVO_DATABASE_URL` 后，新增的 `agent_execution` 迁移创建 `growthevo_agent_state`，保存运行、操作去重记录和自进化状态。配置数据库却无法连接或迁移时，启动失败，不降级为内存。
- 未配置数据库的开发环境使用 `MemoryAgentBackend`，明确显示“进程内记录”。它不能跨重启恢复。
- 每次模型调用前保留既有上下文；每次工具执行前，先保存确切工具名、参数、步骤索引与参数指纹；完成后保存工具结果。恢复不让模型重新生成尚待落账的写操作。
- 活动草案和该步骤的幂等结果在**同一个数据库事务**中写入。若提交后、结果检查点写入前退出，恢复取得同一草案，不会再创建一份。此保证只覆盖现有 PostgreSQL 草案工具，不能推广到尚未接入的外部服务。
- 运行使用 120 秒租约、30 秒心跳和随机执行令牌。短事务在行锁取得后读取数据库时钟；过期工作者和被取消的工作者不能保存新结果或写入草案。同一任务最多恢复 16 次，审计事件最多 256 条。
- 请求取消保存 `interrupted`；显式停止任务保存 `cancelled` 并撤销租约。取消不能撤销已经提交的草案。进程硬退出的运行在租约到期后可继续；当前通过执行轨迹按钮或 API 手动恢复，没有后台调度器自动领取任务。
- 恢复使用保存的目标、策略快照和步数预算，并重新检查当前请求的草案授权。旧运行不会因策略晋升而中途换规则。
- 自进化候选分析失败不会掩盖已保存的执行结果，可在自进化中心重新分析。

### 接口

| 接口 | 用途 |
| --- | --- |
| `GET /api/harness/runs` | 当前身份的公开运行摘要，不返回模型上下文或确认令牌 |
| `GET /api/agent/runs/{run_id}` | 查看自己的任务；待确认时返回当前浏览器确认令牌 |
| `GET /api/agent/runs/{run_id}/events` | 查看有序的启动、操作准备、保存、回执、恢复与停止事件 |
| `POST /api/agent/runs/{run_id}/resume` | 从已保存检查点继续；请求体为 `{"allow_draft_writes": false}` |
| `POST /api/agent/runs/{run_id}/cancel` | 撤销后续执行权并保留已发生的效果 |
| `POST /api/agent/runs/{run_id}/ui-confirmation` | 保存当前浏览器操作的有序回执 |

开始任务的示例：

```json
{"goal": "检查增长机会并打开实验页面", "allow_draft_writes": false, "max_steps": 6}
```

## 浏览器反馈之后才继续

运行在发出界面操作后立即保存并暂停为 `awaiting_ui_confirmation`。浏览器按 `ui_actions` 的顺序执行操作，核对实际页面、菜单或输入框焦点，再提交：

```json
{"token": "<current-round-token>", "receipts": [{"step_index": 1, "status": "confirmed"}]}
```

回执必须准确覆盖当前步骤。每轮令牌不同，相同回执可幂等重试；旧轮次重试不能确认下一轮操作，冲突回执不能覆盖已记录的结果。浏览器成功回执被加入模型的下一轮工具反馈，网页再请求继续。失败回执会显示失败，保留手动继续入口。

`ui_confirmed` 表示浏览器报告了结果；`completed` 表示受限执行循环已结束，均不是独立证明业务目标成功。浏览器回执是用户端报告，不能冒充独立评测、客户收益或生产推广证据。

## 身份与数据边界

配置 OIDC 后，即使 API 模式下，智能体、自进化和执行轨迹接口也要求有效 Bearer Token，拒绝重复 Authorization 头。执行作用域来自**验证后的 issuer 与 subject**，调用方传入的租户头、运行编号、确认令牌都不能选择其他账号。不同账号不能查看、继续、停止或确认对方任务，候选与策略也按账号存储。

这实现的是**执行与自进化记录的账号隔离**。原有活动、审批等业务对象仍属于共享工作空间，不能称为整个产品已实现多租户业务隔离。无认证的本地开发环境使用单一开发作用域。

公开轨迹只展示受控事件、参数指纹与必要草案摘要。私有检查点包含目标、有限模型反馈与准备执行的参数，数据库属于受信任存储，应依部署要求设置访问控制、加密、保留周期与备份。此迁移不提供数据库行级安全、自动清理任务或防数据库管理员篡改的签名审计账本。业务备份需同时保留运行与 effects，不能只恢复其中一类后继续旧任务。

## 自进化的真实闭环

`EvolutionAuthority` 只允许修改受限的操作步数或优先读取分区。权限、业务校验、评测器和推广门槛不可被候选修改。

1. 至少八条当前策略指纹下的真实、去重运行记录才能发现候选。运行中、等待界面确认和中断中的任务不参与分析。
2. 候选从当前策略派生，保存父指纹和原因。相同父策略及提案不会重复入档。
3. 独立离线评测比较基线与候选，检查任务合约完成率、规则违反率、成本、样本数及证据身份。结果不足或退化会拒绝候选。
4. 离线通过后仅进入 `awaiting_shadow_canary`。线上影子、灰度与人工批准是独立门槛，没有公开 HTTP 晋升端点。
5. 受信任宿主晋升后，后续任务使用新策略；下一代候选从该策略继续派生。已有任务继续使用开始时的快照。

配置 PostgreSQL 后，活跃策略、候选档案、评测结果和评测执行权跨重启与副本共享。评测在短事务中领取 600 秒租约，随后释放锁运行 Replay；读取当前策略不会被长评测阻塞。评测异常释放执行权；硬退出后过期执行权可重新领取；旧评测工作者不能覆盖替代工作者的结果。父策略改变时拒绝过期证据。

现有宿主 `promote` 仍需要可信调用者，布尔批准参数不是签名生产证据。自动生产推广、已部署浏览器效果的独立证明和自主源码修改尚未接入；不能把候选发现或离线通过称为完整生产自进化。

### 配对 Replay 配置

部署者单独提供经过脱敏的保留任务集：

```bash
GROWTHEVO_AGENT_BENCHMARK_PATH=/absolute/path/to/heldout.json
GROWTHEVO_AGENT_BENCHMARK_SHA256=<sha256-of-the-exact-file-bytes>
```

文件上限 1 MB，顶层仅含：

- `suite_id`：12–128 字符的稳定标识。
- `tasks`：30–200 条不同任务，每条含 `id`、`goal`、`expected_route`、`required_section`，使用既有白名单。
- `workspace`：`dashboard`、`opportunities`、`campaigns`、`experiments`、`approvals`、`evidence`、`actions`、`decisions`、`harness`、`evolution` 十个分区的隔离快照。

摘要不匹配时 live 运行时启动失败；Demo 不打开文件。摘要只证明文件身份，不能证明数据独立性，保留任务不能泄漏给候选生成。

配置模型和任务集后，`POST /api/evolution/candidates/{candidate_id}/evaluate` 在独立线程/事件循环内以新模型池运行基线及候选，五分钟超时，不接触真实活动。客户端不能上传指标、执行代码或替换评测器。`PairedReplayEvaluator` 复用原有操作循环及同一业务校验，衡量**离线工具与路由合约**，没有声称复现真实浏览器效果或线上因果提升。证据身份为 `replay:<full-manifest-digest>`。

## 参考实现与研究依据

| 一手资料 | 本次采用的实践 | 未作出的声明 |
| --- | --- | --- |
| [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/) 及[官方会话源码](https://github.com/openai/openai-agents-python/blob/main/docs/sessions/index.md) | 持续上下文与存储解耦；会话编号本身不是授权 | 未引入其 SDK，也未把运行编号当身份 |
| [Microsoft Durable Agents](https://learn.microsoft.com/en-us/azure/durable-task/sdks/durable-agents-microsoft-agent-framework) | 持久化状态、检查点恢复、避免重复已完成操作 | 未实现 Azure Durable Task 的分布式调度器 |
| [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) | 把检查点与普通聊天记录区分，显式暂停和恢复 | 未引入第二套工作流框架 |
| [Reflexion，NeurIPS 2023](https://github.com/noahshinn/reflexion) | 用执行反馈指导后续改进 | 没有在线更新模型权重 |
| [SWE-agent，NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/hash/5a7c947568c1b1328ccc5230172e1e7c-Abstract-Conference.html) | 为智能体设计受控工具接口，使用环境反馈 | 没有复现论文性能或开放任意电脑控制 |
| [DSPy，ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/f1cf02ce09757f57c3b93c0db83181e0-Abstract-Conference.html) | 明确指标、保留评估任务、对照验证后再采用变化 | 没有把自述改进作为测量结果 |

这些资料指导工程设计，不是本项目性能的背书。现有签名证据和生产推广治理见 [推广清单](promotion_evidence_manifest.md)、[线上灰度推广](online_canary_promotion.md)；后续应接入这些权威校验，不应再建一个绕过它们的批准入口。

## 验证

```bash
python -m pytest tests/test_agent_operating_system.py tests/test_agent_ui_receipts.py tests/test_agent_replay_manifest.py tests/test_agent_execution_journal.py tests/test_durable_evolution.py tests/test_agent_scoped_api.py
```

真实 PostgreSQL 检查还需设置 `GROWTHEVO_TEST_DATABASE_URL`。Product Persistence CI 必须运行数据库分支；本地缺少数据库的跳过项不算通过。新测试覆盖提交草案后进程退出、准确恢复及去重、租约失效、停止后的旧工作者、重新授权、跨账号拒绝访问、应用重启后的界面回执及模型续跑、评测竞争与旧结果覆盖保护。Product Surface CI 使用真实 Chrome 验证界面操作、回执保存、继续请求顺序和最终状态。
