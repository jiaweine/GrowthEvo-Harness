# GrowthEvo / Nightfall — 设计规范

## 不是“更亮的赛博”，而是更清晰的控制台

GrowthEvo 是一个 Agent Operating System，核心不是聊天本身，而是**目标、可执行能力、证据、状态、权限与进化**。产品布局按重要性排列：**Agent OS → Evolution Lab → 业务增长工作区 → 审批和基础设施**。

Nightfall 是为现有 Web 工作台开发的全站渐进式视觉层，源文件为 growthevo/web/static/cyber-surface.css，覆盖既有 layout、dashboard、agent、product-pages 和 responsive CSS，不复制业务表单或路由逻辑。桌面与移动端的导航都把 Agent OS 和自进化放在前两位。

## 可追踪的设计参考

- [Kimi Work 的任务/聊天分流与权限确认](https://www.kimi.com/en/help/kimi-work/overview)：将“做事”与“建议”明确分开；GrowthEvo 则进一步将每次真实调用及其审查边界展示在同一工作台。
- [Linear 的设计改造说明（2026）](https://linear.app/now/behind-the-latest-design-refresh)：降低视觉噪声、统一导航和操作模式、减少无谓控制；Nightfall 只使用一个青色主强调色。
- [OpenAI ChatGPT Apps 的多模态界面经验](https://developers.openai.com/blog/15-lessons-building-chatgpt-apps)：完整桌面、窄屏和底部固定导航都需要独立布局及留白，不能将桌面界面机械缩小。
- [OpenAI Plugins UI 指南](https://developers.openai.com/plugins/concepts/ui-guidelines)：高对比文字、状态颜色语义化、品牌强调色节制。
- [Claude Artifacts 的并列工作区](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them)：让聊天和操作结果并置。GrowthEvo 保留侧栏 Agent，但主工作区优先展示真正可执行的任务与证据。

以上仅参考架构与原则，不照抄其他产品界面，也不宣称未经用户研究验证的“审美排名”。

## 设计 Token

| 类别 | Token | 用途 |
| --- | --- | --- |
| Base | #090e18 | 夜航背景 |
| Panel | #111a29 | 数据和流程面板 |
| Raised | #162235 | 悬浮、交互层 |
| Text | #eef5ff | 主要信息 |
| Muted | #a3b5ca | 辅助信息 |
| Accent | #68e4e0 | 单一主色：操作、焦点、当前状态 |
| Success | #68dfb1 | 已验证成功 |
| Warning | #f6bb78 | 待检查 |
| Danger | #ff7b95 | 高风险、错误 |

保持标题约 27–37px、面板标题约 15px、正文一般 11–13px；不要再为主要业务字段使用 7–8px 字号。数字应当来自 API；在无人执行前展示真实空状态，不制造运行次数、进化率或速度统计。

## 交互规范

1. 主菜单与移动菜单首位是 Agent OS、自进化中心；主页也有任务入口和进化路径说明。
2. 任务引导是可以点击并填入真实任务的交互组件，点击即生效，没有空壳按钮。
3. 运行记录只显示真正的受控工具动作、校验与失败状态；没有产出就不标称完成。
4. Campaign Draft 必须经过用户明确同意；发布、Canary 推广与审批不由模型自动进行。
5. 可变字号、可见焦点描边和 prefers-reduced-motion，移动端保持可访问操作区域。
6. API 不可用必须保留不可用状态；Demo 数据与正式数据分离。进程内记录不等于完整持久化审计。
7. 夜航背景中的网格、辉光仅用于局部装饰，业务表格和证据区域以清晰度为先。

## 验收

- Python: core tool contracts、运行守卫、离线 Replay 评测。
- Browser: Desktop 1536×1024、Tablet 以及 375px 移动端布局；不裁切 Agent 输入区、侧栏、表格。
- CI: 测试真实空运行记录、导航、缓存资产和静态资源生成；不依赖预置伪数据。
- 安全：将工具只读/可写权限绑定在服务端，不以 CSS 或前端开关作为唯一授权机制。

## 待改进

正式生产还需要持久化多租户运行追踪、完善的浏览器语义操作驱动、跨页面步骤流式呈现、用户可读的恢复/回滚事件，以及可量化的可用性测试。这些不能用视觉完成度代替。
