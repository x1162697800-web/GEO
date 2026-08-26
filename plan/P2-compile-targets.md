# P2 · 新增编译目标：品牌 SKILL.md + MCP server

**优先级**：P2a 高（性价比最高）/ P2b 中
**风险等级**：低（纯新增，不改已有逻辑）
**依赖**：无。决策 **D1 已定（手写 stdio JSON-RPC）**
**前置阅读**：`RULES.md` R7、R8

---

## 1. 战略依据

这是 Nile 拆解里**唯一真正值得抄的东西——而且他们承诺了但没交付**。

实测（2026-08-22）：

| 官网表述 | 实际 |
|---|---|
| 「Nile Skills — Nile inside your own Codex / Claude Code」「Install in your agent」 | 指向 `/waitlist?intent=pro` 等待列表 |
| `/protocol` 整页讲编译到 ACP / UCP / **MCP** / **Agent Skills** | `/skill`、`/SKILL.md`、`/.well-known/mcp`、`/mcp/sse` **全部 404** |
| — | Shopify App Store「Works with」只列 UCP，**无 ACP / MCP / Agent Skills** |

而 geolook 的处境相反：**已经有一半了。**

`scripts/generate.py:452`：

```python
ASSETS = ["llms", "jsonld", "snippets", "outlines", "attribution"]
```

一个 `parse_facts()`（`generate.py:26`）编译出 5 个目标。加两个目标完全贴合
现有架构：同一个事实库来源，同一个 `run(which=...)` 分发，**不引入新概念**。

叙事差别很大：

- 「生成 llms.txt」= 功能
- 「你的品牌事实编译到每一条 AI 读取轨道」= 定位

---

## 2. P2a · 品牌 SKILL.md（先做，最便宜）

### 是什么

**注意与现有 `SKILL.md` 区分**：

| | 现有 `geolook/SKILL.md` | 新增的品牌 SKILL.md |
|---|---|---|
| 描述谁 | geolook 这个工具 | **被审计的那个品牌** |
| 给谁装 | 用 geolook 的人（Claude Code） | 品牌的潜在客户 / 任何 agent 用户 |
| 归类 | 仓库自带文件 | **部署资产**（和 llms.txt / JSON-LD 并列） |

从 `parse_facts()` 渲染一个 markdown：品牌是什么、做什么、关键事实、
适用与不适用场景、常见问题、口径边界。装进 Claude / Codex / Cursor 后，
agent 回答关于这个品牌的问题时按品牌自己的口径说。

### 工作量

`ASSETS` 加一项 `"skill"` + 一个渲染函数 `gen_skill_md(slug, lang)`。
参照现有 `gen_llms_txt()`（`generate.py:71`）的写法，数据源完全相同。

**这是全部规划里性价比最高的一项。**

### 关键设计点

- **只写已确认的事实**。`parse_facts` 里标「待确认」的字段不能进 SKILL.md——
  这个文件会被 agent 当权威口径用，编造的代价比 llms.txt 更高（R8）
- **指向而非内嵌**。参考 Nile 官网对 Agent Skills 的描述（这点他们说得对）：
  SKILL.md 应该指向可抓取的上下文而不是嵌一份快照，否则更新了事实库、
  已安装的 skill 还在用旧数据
- **写明不适用场景**。按 `method.md` 第 3 节，「写清楚不适合谁反而提高可信度」

---

## 3. P2b · MCP server

### 是什么

把 geolook 自己暴露成工具，让任意 MCP 助手（Claude Desktop / Cursor / Codex）
能直接调用。候选工具面：

| 工具 | 作用 |
|---|---|
| `list_projects` | 列出本机项目 |
| `run_audit` | 对某项目跑站点体检，返回六维分数与问题码 |
| `get_brand_facts` | 查品牌事实库 |
| `list_tickets` | 列工单（含优先级、风险等级、验收标准） |
| `get_question_bank` | 查问题库与诊断类型 |
| `generate_assets` | 生成部署资产 |

### 为什么值得做

它改变的是**分发方式**：geolook 从「要装的工具」变成「agent 能调的能力」。
现有 `SKILL.md` 已经做了 Claude Code 集成，MCP 是自然的下一步，而且覆盖面更广
（Claude Desktop、Cursor、任何 MCP 客户端）。

### 架构决策（D1 已定：手写）

MCP 底层是 stdio 上的 JSON-RPC 2.0，需实现的面很窄：`initialize` 握手、
`notifications/initialized`、`tools/list`、`tools/call`，可选 `resources/*`。
约 150–250 行含工具 schema，`json` + `sys.stdin/stdout` 即可。

**不引入官方 SDK**，它会带来 pydantic / anyio / httpx 一串传递依赖，
破坏 README 里「恰好三个第三方包」这个卖点（R7）。

定案依据：这与 dashboard 用标准库 `http.server` 而非 Flask 是同一条路，
不是新的赌注。stdio 传输也贴合现有形态——MCP 客户端把 server 当子进程启动，
即 `python scripts/mcp_server.py`，与 `geo.py` 的 CLI 模式一致。

**两条必须执行的对冲**（理由见 `DECISIONS.md` D1 的保留反方意见）：

1. **协议层封装在单独模块**，与工具实现分离，规范剧烈变动时可整体换成 SDK
2. **必须在至少两个 MCP 客户端上实测**——手写方案的主要风险是
   `protocolVersion` 协商，而「装了跑不起来」是致命的第一印象

### 安全边界（必须先想清楚）

MCP server 会让外部 agent 触发本机操作，这与 geolook 现有的安全模型
（绑 127.0.0.1、公网暴露必须带 token）是同一类问题：

- **只读工具与写操作工具要分开**。`run_audit` / `generate_assets` 会写 `work/`，
  `publish` 绝对不能进 MCP 工具面——发布必须保持「每次显式点击确认」
  （README 的设计原则之一）
- **不能通过 MCP 读到 `.env`**。密钥不进任何工具返回值
- **项目 slug 要走现有白名单校验**（`geolib.SLUG_OK`），不能让 agent 传任意路径

---

## 4. 验收标准

### P2a

- [ ] `python scripts/geo.py generate --asset skill --slug <项目>` 产出 SKILL.md
- [ ] 产物里没有任何「待确认」字段的内容
- [ ] 产物指向线上上下文而非内嵌快照
- [ ] 含「不适用场景」小节
- [ ] `tests/` 有对应用例（参照现有 llms.txt / JSON-LD 的测试写法）
- [ ] 部署文档说明装进 Claude / Codex / Cursor 的具体路径

### P2b

- [ ] 在至少两个 MCP 客户端上实测握手 + `tools/list` + `tools/call`
- [ ] **依赖数未增加**（D1 定案要求，R7）
- [ ] 协议层与工具实现分离在不同模块（D1 的替换对冲）
- [ ] 写操作工具与只读工具分离；`publish` 不在工具面内
- [ ] 任何工具返回值都不含 `.env` 内容
- [ ] slug 参数走 `SLUG_OK` 校验，路径穿越用例通过
- [ ] 全量测试通过

---

## 5. 顺序建议

**P2a 可以立刻做**（不阻塞于任何决策，且最便宜），建议在 P0 期间当快速胜利插进去。

**P2b 等 D1**。定了再动，别边写边改协议层选型。
