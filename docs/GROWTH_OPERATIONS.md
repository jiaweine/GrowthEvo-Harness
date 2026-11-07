# 数据驱动增长运营：数据库与执行边界

GrowthEvo 的客户画像、行为事件、动态人群、旅程、素材、优惠、实验分流、曝光及投递记录现在有统一的 PostgreSQL 存储路径。Nightfall 的「数据驱动运营」页面直接使用增长 API，而不是在 API 失败时回退到静态参考数据。

## 运行模式与数据来源

通过现有 GROWTHEVO_DATABASE_URL / DATABASE_URL 启用 PostgreSQL。迁移由 PostgresStore 统一执行，新增 growthevo_growth_records 表，以 (owner_scope, collection, item_id) 为主键。

- API / 自托管验证：每个工作身份首次访问时，演示客户、事件、素材、优惠、旅程、曝光和购买结果写入 PostgreSQL；所有样本都有 synthetic=true 标识，服务重启不重复插入。
- 生产模式：不会种入演示数据；无数据时返回空结果。
- 未接数据库：新增 /api/growth/* 返回 503，不使用进程内伪造数据。
- 静态 Pages：页面明确说明需要 PostgreSQL + API 模式，不把 UI 假数据当作数据库回执。

登录用户使用经过验证的 issuer + subject 派生隔离作用域；这不是完整企业组织层 RBAC、RLS 或租户管理。原有 Campaign/Approval 业务对象仍应继续完善租户隔离。

## 主要接口

| 资源 | 路径 | 说明 |
| --- | --- | --- |
| 概览 | GET /api/growth/overview | 记录数量、来源及渠道状态 |
| 客户 | GET、POST /api/growth/customers | 客户属性、营销授权 |
| 客户详情 | GET /api/growth/customers/{id} | 事件、动态分群、实验分配、投递 |
| 更新客户 | POST /api/growth/customers/{id}/update | 修改属性或撤销授权 |
| 事件 | GET、POST /api/growth/events | 去重、归档并触发旅程 |
| 分群 | GET、POST /api/growth/segments | 按属性相等条件筛选 |
| 预览 | GET /api/growth/segments/{id}/preview | 动态分群人数及客户 |
| 素材、优惠 | GET、POST /api/growth/creatives、offers | 可引用的内容与优惠目录 |
| 实验 | GET、POST /api/growth/experiments | 固定权重、显式对照组 |
| 曝光 | POST /api/growth/experiments/{id}/exposures | 稳定分组、记录曝光、幂等请求 |
| 报告 | GET /api/growth/experiments/{id}/report | 分组曝光、转化、观测差 |
| 旅程 | GET、POST /api/growth/journeys | 事件触发、动态人群和延迟步骤 |
| 激活 | POST /api/growth/journeys/{id}/activate | 人工启用旅程 |
| 到期处理 | POST /api/growth/journeys/process | 仅创建待投递记录 |
| 队列 | GET /api/growth/journeys/jobs | 持久化任务状态 |
| 投递记录 | GET /api/growth/deliveries | 区分模拟、排队、提交、渠道回执 |
| 外部提交 | POST /api/growth/deliveries/{id}/submit | 仅生产模式，需单独授权 |
| 渠道回执 | POST /api/growth/deliveries/{id}/receipt | 仅可信渠道回执可推进旅程 |

### 事件采集

~~~json
{"event_id":"signup_20261107_abc","customer_id":"customer_alpha","name":"signup","properties":{"source":"app"}}
~~~

事件 ID 不能重复代表不同内容。相同事件重发不会重复触发旅程；过去 24 小时以外的历史事件只归档，不补发营销信息。

### 实验曝光

~~~json
{"customer_id":"customer_alpha","request_id":"checkout_exposure_abc","surface":"checkout"}
~~~

哈希使用身份作用域、实验 ID 和客户 ID，确保同一客户分组稳定。曝光由明确请求单独记录，分组不能代替曝光。未取得授权的客户不能进入曝光。转化统计只计入曝光后、成熟窗口内的目标事件。

报告提供观测转化率与相对对照组的百分点差异，不声称通过显著性检验或证明因果增长。现有 CATE、OPE、Safe-PI 研究组件尚未自动接管这批新接口的在线策略。

## 持续旅程执行

启用可取消的数据库 Worker：

~~~bash
GROWTHEVO_JOURNEY_WORKER_ENABLED=1
~~~

Worker 每五秒轮询到期任务，多个进程对同一作用域使用 PostgreSQL 事务锁防止重复创建投递。Worker **只生成待发命令**，不主动访问外部营销系统。

当前实现适合有限规模验证；仍需改进批量扫描、分页、独立 Outbox Worker、调度公平性、死信、租约、补偿和限速，不宣称已具备大型营销平台的运营容量。

## 可信渠道网关

生产模式额外配置：

~~~bash
GROWTHEVO_CHANNEL_WEBHOOK_URL=https://trusted-gateway.example.com/dispatch
GROWTHEVO_CHANNEL_ALLOWED_HOSTS=trusted-gateway.example.com
GROWTHEVO_CHANNEL_WEBHOOK_TOKEN=<server-side-secret>
GROWTHEVO_CHANNEL_SUBMIT_SECRET=<operator-secret>
GROWTHEVO_CHANNEL_RECEIPT_SECRET=<receipt-secret>
~~~

外部提交要求有效认证和 X-Channel-Submit-Token；渠道回执要求有效认证和 X-Channel-Receipt-Token。密钥只能来自服务端配置，不能放入浏览器资源。

出站网关必须以 idempotency_key 去重。外部请求结果不明确时不会自动重试，以免重复造成副作用。网关 HTTP 2xx 仅代表网关接受请求，**不是实际发送或送达**；独立回执才会改变送达状态并推进后续步骤。演示状态 simulated 不会对外发送。

目前没有内置的 Braze、Salesforce、Adobe 等供应商专属实现，也没有完整的渠道退订同步、预算扣减、优惠核销、跨组织权限和统计显著性工作台。具体投放网关仍需部署者完成可信适配、审批和运营验收。

## 验证

~~~bash
python -m pytest tests/test_growth_operations.py tests/test_growth_api.py
~~~

设置 GROWTHEVO_TEST_DATABASE_URL 可运行真实 PostgreSQL 恢复与 HTTP 测试；这两组测试已加入 Product Persistence CI。所有演示数据落在 PostgreSQL，不被当成客户真实收益证明。

## 后续优先事项

1. 让训练好的 CATE 模型与 Safe-PI 策略成为真正的在线推理产物，同时保存精确行为概率、特征版本和策略证据。
2. 补客户身份解析、组织 RBAC、数据保留与删除、业务审批、渠道频控和预算账本。
3. 补实验互斥、SRM、置信区间、长期 Holdout、线上随机化和序贯分析。
4. 将现有 JSONB 记录层逐渐拆分为事件存储、运营数据库、可靠 Outbox 和分析仓库。
