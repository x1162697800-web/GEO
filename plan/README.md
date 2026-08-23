# GeoLook 平台 + 插件 · 总执行规划

> 本目录是内部规划文档，**不要放进 geolook 公开仓库**：含竞品拆解与商业策略。
> 需要版本化请单独建私有仓库。

制定日期：2026-08-23
依据：本轮对 Nile（nile.app / Shopify app「Nile: AI Commerce」）的技术拆解，
以及对 geolook 现有代码的实测。证据见 [`reference/nile-teardown.md`](reference/nile-teardown.md)。

---

## 0. 文档索引

| 文档 | 作用 |
|---|---|
| `README.md`（本文） | 全局规划、阶段划分、依赖关系、节奏 |
| [`RULES.md`](RULES.md) | **贯穿纪律**。所有阶段都不许破的红线 |
| [`DECISIONS.md`](DECISIONS.md) | 决策记录（4 项已于 2026-08-23 定案），持续追加 |
| [`P0-windows.md`](P0-windows.md) | Windows 支持（阻塞项） |
| [`P1-extension.md`](P1-extension.md) | 插件独立化 + 上架 |
| [`P2-compile-targets.md`](P2-compile-targets.md) | 品牌 SKILL.md + MCP server |
| [`P3-ecommerce-criteria.md`](P3-ecommerce-criteria.md) | 电商审计维度 + sitemap 时区归一 |
| [`P4-open-research.md`](P4-open-research.md) | 开源研究做增长 |
| [`reference/nile-teardown.md`](reference/nile-teardown.md) | Nile 拆解的全部实测证据 |

执行任何子文档前先读 `RULES.md`。

---

## 1. 现状判断

### 1.1 两条腿不对等

**平台侧比预想的更接近目标架构。** `scripts/generate.py:452`：

```python
ASSETS = ["llms", "jsonld", "snippets", "outlines", "attribution"]
```

一个 `parse_facts()` 品牌事实库编译出 5 个目标。Nile 官网 `/protocol` 整页在讲的
「一份上下文编译到多个 target」，geolook 已经做完了，只是没这么命名。

**插件侧被硬绑在平台上。** `extension/manifest.json`：

```json
"host_permissions": ["http://127.0.0.1:8765/*"]
```

只能回传本机 8765，平台不跑插件就没用。它是**配件，不是入口**。
安装漏斗：装 Python → clone 仓库 → 起 dashboard → load unpacked（v0.1.0，未上商店）。
非技术用户在第一步就流失。

### 1.2 自己的开发环境是断的

Windows 上 `scripts/geolib.py:8` 的 `import fcntl` 阻塞全部代码——一行都跑不了。
实测：塞一个 no-op 锁替身后 87 个测试全过，`crawl` / `audit` / `score_page` 全部正常。
**核心代码本来就可移植，只差一个锁的抽象。**

### 1.3 已落地的改动（本轮）

`probe_ai_ua` 信号分类修复已完成并通过全部测试，改动 4 个文件：

- `scripts/crawl.py` — 新增 `UA_DENY_STATUS` / `UA_RATE_STATUS`，429/503 分流到
  `ai_ua_rate_limited`（判为「未测」），加退避重试与默认 UA 基线对照
- `scripts/ui.html` — 限速状态不再显示成「实测放行」
- `SKILL.md` / `references/method.md` — 补上判据说明

修复前会把站点限速误报成「WAF 封禁全部 AI 爬虫」（P0 级结论，诱导用户去动 WAF，
按 `method.md` 第 7 节属最高风险改造）。第一轮跑批报了 4 个假阳性，修复后归零。

---

## 2. 战略结论（来自 Nile 拆解）

三条直接影响规划的结论：

**① Nile 的技术护城河不存在。** 权限清单显示它用 `write_publications` 把自己注册成
Shopify 的 sales channel，商品发布进去后由 Shopify 自己的 Agentic Storefronts / UCP
管道对外暴露。**它不实现 UCP 服务端**，官网宣称的 ACP / MCP / Agent Skills 三条
在真实产品里完全不存在（App Store「Works with」只有 UCP）。

**② 最值得抄的东西他们承诺了但没交付。** 官网「Nile Skills — Install in your agent」
点进去是 `/waitlist?intent=pro` 等待列表，`/skill`、`/SKILL.md`、`/.well-known/mcp`、
`/mcp/sse` 全部 404。而 geolook 本身已经带 `SKILL.md`，离 MCP 只差一层封装。

**③ 他们打不到非电商品类。** Nile 在 `/compare` 专门开一节打 GEO/AEO 工具，论点是
「内容优化让你被提及，不让你被购买」。这个论点只在电商 SKU 场景成立——B2B、SaaS、
专业服务、本地服务没有 SKU 可上架，而这些是 GEO 的主战场。

由此确定第三条腿：**MCP / Skill = 分发**。原规划是「平台 + 插件」两条腿，
这次拆解新长出来的第三条恰好是对手没做出来的那条。

### 2.4 来源归属（防止未来误判）

**这份规划不是「geolook + Nile 的结合」，两个最高优先级的阶段与 Nile 无关。**

| 阶段 | 来源 | 与 Nile 的关系 |
|---|---|---|
| **P0** Windows 支持 | 在 Windows 上实跑 geolook 撞到的 | **完全无关**。纯 geolook 内部缺陷 |
| **P1** 插件独立化 | 审 `manifest.json` 的 `host_permissions` | **完全无关**。Nile 没有浏览器插件 |
| **P2** SKILL.md + MCP | Nile 拆解 | **直接来自 Nile**（他们承诺未交付的那部分） |
| **P3** 电商维度 | Nile 的判据 | 来自 Nile，但已重新归类为门票判据 |
| **P4** 开源研究 | Nile 的打法 | 抄方法，不抄内容 |
| `probe_ai_ua` 修复（已落地） | 做交叉验证时暴露的 | 间接——geolook 自身 bug |

**为什么要写这一节**：如果日后 Nile 死了、转型了或不再相关，
容易有人认为整份规划过期，连带把 P0 降级。
**而 P0 修的是一个会杀掉正在运行任务的 bug（`jobs.py:230`），
它的紧急程度与 Nile 的存亡毫无关系。**

### 2.5 Nile 在本规划中的三种作用

**① 正面借鉴**（最表层）——编译多目标的叙事命名、开源研究的增长打法、电商判据。
其中「编译多目标」geolook 本来就做完了（`ASSETS` 的 5 个目标），Nile 只提供了更好的说法。

**② 反面教材**（更有价值）——贡献了 `RULES.md` 里两条最硬的红线：
R3「测不到 ≠ 不通过」来自他们把 Adwoa Beauty 打成 0 分并写进「无法抓取」排除组；
R8「声明必须与实现一致」来自他们官网写「只读、nothing more」而实际权限是
改商品、改订单、改主题和结算页。**这两条现在约束的是 geolook 自己**——
R8 直接催生了 P0 里「Windows 上 `.env` 权限保证不成立必须写进文档」那条。

**③ 边界标定**——拆到 Shopify 权限清单才发现他们的护城河不存在
（不实现 UCP，借 Shopify 的 publication 机制）。这把结论从「打不过」
变成「能做但不该做」，直接产出了第 7 节的「不做 Shopify app」。

**另外一项容易忽略的贡献**：Nile 开源了数据，才使 50 品牌交叉验证成为可能，
而那轮跑出的 geolook 独有层基线（120 个 PDP、六维均分 53.0、平均 683 词、
可引段落 22%、10/40 零可引段落）是 geolook 之前**没有的资产**，与「抄 Nile」无关。

---

## 3. 三条腿的分工

| | 职责 | 形态 | 关键约束 |
|---|---|---|---|
| **平台** | 实施与验收，**唯一指标真相源** | 重，本地，数据主权 | 指标只能有一份实现 |
| **插件** | 取证 + 获客入口 | 轻，浏览器，**可独立跑** | 只产原始样本，不算指标 |
| **MCP / Skill** | 分发，让 geolook 被 agent 调用 | 无界面，接口即产品 | 不破坏「三个依赖」 |

---

## 4. 阶段总览

| 阶段 | 内容 | 状态 | 风险等级 | 依赖 |
|---|---|---|---|---|
| **P0** | Windows 支持 | ✅ **已完成** 2026-08-23 | 高风险技术改造 | 无 |
| **P2a** | 品牌 SKILL.md 编译目标 | ✅ **已完成** 2026-08-23 | 低（纯新增） | 无 |
| **P2b** | MCP server | ✅ **已完成** 2026-08-23 | 低（纯新增） | 无（D1 已定） |
| **P1a** | 插件商店上架材料 | 待办（审核是长杆，宜尽早启动） | 低 | 需外部素材 |
| **P1b** | 插件独立化开发 | 待办 | 需观察 | 无（D2 已定） |
| **P3** | 电商维度 + 时区归一 | 待办 | 需观察 | 无（D3 已定） |
| **P4** | 开源研究做增长 | 待办 | 低 | P1 |

### 4.1 已落地的提交（2026-08-23）

| Commit | 内容 |
|---|---|
| `5a8ba74` | `fix(crawl)`：429/503 不再误判为 WAF 封禁 AI 爬虫 |
| `d402ae2` | `feat`：原生支持 Windows，不再需要 WSL |
| `8c1a0f3` | `fix(ui)`：补齐 WAF/UA 限速分支的三语文案 |
| `cc22030` | `fix(dashboard)`：端口被占时拒绝启动，不再静默绑定 |
| `8c517de` | `feat(generate)`：新增品牌 SKILL.md 编译目标 |
| `e322974` | `feat(mcp)`：把 geolook 暴露成 MCP server |

测试从 **87 涨到 165**（`fcntl` 此前让 pytest 在收集阶段就中断，有几个测试
文件从未执行过）。依赖数未变，仍是 `requests` / `beautifulsoup4` / `lxml` 三个。

**编译目标从 5 个扩到 6 个**：`llms` / `jsonld` / `snippets` / `outlines` /
`attribution` / **`skill`**。加上 MCP server，第三条腿（分发）已经立起来——
这正是 Nile 承诺却没交付的那部分。

### 4.2 P0 期间新发现并修掉的两个缺陷

都不在原计划里，是执行中撞出来的：

1. **`jobs.py` 的 `os.kill(pid, 0)` 在 Windows 上会杀进程**（走 `TerminateProcess`），
   `reap_orphans()` 一跑就把正在运行的任务全杀掉。已改用
   `OpenProcess` + `GetExitCodeProcess`，并加了真起进程的回归测试。
2. **看板在端口被占时静默绑定**。Windows 的 `SO_REUSEADDR` 允许绑上正在监听的
   端口，于是看板打印「已启动」却服务不了请求——实测撞到过：首页 200（是别人的
   应用），所有 `/api/*` 全 404。已改为启动前主动探测 + Windows 上关闭地址复用。

### 4.3 仍未验证的缺口

**POSIX 回归未跑**（本机无 macOS / Linux / WSL）。影响 POSIX 的改动只有一处：
`geolib.project_lock` 的锁文件打开模式 `"w"` → `"a+"`。在 mac 或 Linux 上跑
`python3 -m pytest tests -q`（应为 165 passed，Windows 专属那条会 skip）
加 `nile-xval/verify_p0.py` 即可补齐。

## 5. 依赖关系与节奏

```
P0  Windows 支持        ─── 无依赖，正在阻塞本人开发 ──┐
P1a 插件上架材料        ─── 无技术依赖，审核长杆     ──┤
P2a 品牌 SKILL.md       ─── 独立，最便宜的一项       ──┤
                                                       ├──→ P4 开源研究
P1b 插件独立化开发      ─── 可晚于 P1a              ──┤
P2b MCP server          ─── 独立（D1 已定：手写）   ──┘
P3  电商维度            ─── 旁路，不阻塞（D3 已定）
```

四项决策已全部定案，见 [`DECISIONS.md`](DECISIONS.md)。当前**没有决策在阻塞开工**。

**建议节奏**

1. **立刻**：P0（在阻塞你本人开发）+ 启动 P1a 商店材料（唯一提前能省时间的项）
2. **接着**：P2a 品牌 SKILL.md 当快速胜利插进去
3. **然后**：P1b 插件独立化
4. **最后**：P3 / P4 的先后——D4 已定为**四周后再评估**，届时看 P1a 审核结果、
   Windows 用户真实反馈、以及有没有出现真实的代理商需求

**排序逻辑：先修漏斗，再灌水。** P4 会带来注意力，注意力落到安装漏斗上；
P0（装不上）和 P1（发不出去）不修，P4 的流量就是白灌。

---

## 6. 决策（已全部定案 2026-08-23）

详见 [`DECISIONS.md`](DECISIONS.md)。

| 编号 | 决策 | 结论 |
|---|---|---|
| **D1** | MCP 手写还是 SDK | **手写**。与 dashboard 用标准库 `http.server` 是同一条路，不是新赌注。协议层单独成模块以便日后替换 |
| **D2** | 插件独立模式边界 | **方案 A + 单向纪律**。只到「提到/没提到」；`personal` 模式偏向「更容易提到自己」，所以「没提到」是保守估计**可用**，「提及率还不错」**禁用** |
| **D3** | 电商维度归类 | **归入四层模型的理解层门票判据**。四层模型本来就区分门票与杠杆，协议 schema 即依据，不需要效果实证，但不进六维总分 |
| **D4** | 阶段目标 | **不阻塞，四周后再定**。P0/P1a/P2a 同时服务采纳量与代理商交付；现有投入（PH、三语 README vs 客户交付包）显示两边都投了，且无任何计费基建 |

---

## 7. 不做什么

规划纪律的一半是明确不做：

- **不做 Shopify app**。它会把 geolook 从「自托管开源平台」拉向「SaaS 插件」，
  与「数据全在自己机器上、`git init` 就是备份」的定位直接冲突，且渠道（审核、
  分成、分类）完全不由你控制。理由详见 `reference/nile-teardown.md` 第 6 节。
- **不把 `service.sh` / `sandbox.sh` 移植到 Windows**。便利功能，不阻塞主流程，
  保持 POSIX 专属并在文档写明。
- **不在插件里重算指标**。见 `RULES.md` R2。
- **不为加功能破坏实证锚定纪律**。见 `RULES.md` R1。
