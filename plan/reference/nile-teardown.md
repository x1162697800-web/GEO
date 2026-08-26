# Nile 技术拆解 · 实测证据

拆解日期：2026-08-20 ~ 2026-08-22
对象：`nile.app`（官网）+ Shopify App Store「Nile: AI Commerce」
方法：站点抓取与端点探测、`llms.txt` / `robots.txt` / sitemap 分析、
App Store 权限清单读取、以及用 geolook 引擎对其公开研究数据做 50 品牌交叉验证

**标注约定**：〔实测〕= 直接观测到；〔推断〕= 由观测推导；〔他述〕= 对方自己的说法。

---

## 1. 官网技术结构

### 1.1 前端与托管〔实测〕

**没有使用任何前端框架。** 99KB 首页 HTML 里搜 `/_next/`、`/_nuxt/`、
`astro-island`、`sveltekit`、`gatsby`、`webflow`、`framer`、`wp-content` 全部零命中。

`<script src>` 只有两个：

```
https://cdn.jsdelivr.net/npm/lenis@1.3.23/dist/lenis.min.js   平滑滚动
https://www.googletagmanager.com/gtag/js?id=G-5KVV8Y41PK      GA4
```

**应用层 JS 为零。** `<link rel="stylesheet">` 只有三条外部字体
（Fontshare General Sans、Google DM Sans、Geist Mono），**无任何本地样式表**——
CSS 全部内联进那 99KB。

资源路径 `/_marketing/assets/media-<16位hex>.<ext>`，内容哈希命名〔推断：有构建步骤〕。
对应 `robots.txt`：

```
Allow: /_marketing/assets/
Disallow: /_marketing
```

先屏蔽父目录、再单独放行子目录——顺带一提，这正是逐行正则解析 robots 最易判错的
场景，按 RFC 9309 最长路径匹配才判得对（`Allow` 长度 21 > `Disallow` 长度 12）。

托管：`server: Google Frontend` + `x-cloud-trace-context`，
`cache-control: public, max-age=0, s-maxage=300, stale-while-revalidate=86400`，
带 `last-modified` 与弱 ETag。安全头齐全（HSTS、nosniff、SAMEORIGIN、
Permissions-Policy 关掉 camera/mic/geolocation/browsing-topics）。

**这个选型是刻意的**〔推断〕：产品在卖「你的商品页对 AI 不可读」，
官网就不可能是 SPA。零 JS + 服务端完整 HTML，对不执行 JS 的爬虫
（GPTBot / ClaudeBot / PerplexityBot）满血可读。

### 1.2 GEO 自我实现〔实测〕

首页一页挂 **7 种 JSON-LD**：

```
Organization · WebSite · WebPage · FAQPage(Question+Answer) · Service · SoftwareApplication · Offer
```

`SoftwareApplication` + `Offer` 在给「这是什么产品、怎么收费」做机器可读声明。
`FAQPage` 的 Question/Answer 节点与页面可见问答**一致**（不是自我声明）。

`llms.txt` 是三段式设计，值得借鉴：

1. 一段自我定义（是什么、给谁、怎么收费）
2. What / Pricing / Products 三个事实块，把关键口径写成纯文本
3. Canonical pages 清单，每条是 `[标题](URL): 一句话说明这页回答什么问题`

等于给 AI 递了**带摘要的站点索引 + 官方口径事实表**——AI 不抓取就知道每页讲什么，
关键数字直接可引。

`sitemap.xml` 只有 21 条 URL，架构刻意收窄：首页 → `/protocol`（技术枢纽）→
5 个 `/solutions/*`（按角色切）→ `/compare`、`/glossary`、`/research`（GEO 收口页）→
商务页。内链锚文本全是长尾问句形态。

**但他们自己的 C3 不及格**：`robots.txt` 声明了
`Sitemap: https://nile.app/blog/sitemap.xml`，该 URL 返回 **500**；
主 sitemap 里**一个 blog 页面都没有**，而 blog 是其主要内容资产（5 篇长文）。

---

## 2. 官网宣称的产品架构〔他述〕

「品牌上下文编译器」四阶段：Ingest → Normalize → **Compile** → Sync。

四个编译目标：

| 目标 | 宣称作用 |
|---|---|
| UCP | Google 系商品 schema（Google + Shopify/Etsy/Target/Wayfair/Walmart） |
| ACP | OpenAI × Stripe 结算轨，对话内完成购买 |
| MCP（含 MCP Apps） | 工具调用面，暴露给私有/企业 agent |
| Agent Skills（SKILL.md） | 分发面，装进 Claude / Codex / ChatGPT |

三条硬约束（在四个页面重复，是核心信任设计）：买家显式确认、
购物车与结算两点各校验一次活价活库存、商家规则在每条 rail 同构执行。
另有沙箱 agent 会话与保守归因（只计点击穿透且完成的订单）。

**商家只需暴露三个接口**：目录只读、checkout 入口、服务端订单事件。

---

## 3. Shopify app 的真实技术结构

### 3.1 基本信息〔实测〕

```
apps.shopify.com/nile     200
上线                      2026-01-23
开发者 / 技术支持          FIFTEEN AI
注册地址                  1111B S Governors Ave, STE 21888, Dover, DE, 19904, US
分类                      Marketing - Other（排名 22 / 338）
评价                      6 条，全 5 星
定价                      Free to install，佣金 1% 起
```

Dover DE 那个地址是知名的注册代理/虚拟信箱地址〔推断〕。

评价细节：一条写于「使用约 1 小时」之后；FitVille 那条把它称作
"a geo app for shopping catalogs"（当成地理位置应用），通篇讲 catalog 管理便利，
完全没提 AI 卖货；CHESONA（香港）报告 3 个月 8 单、共 500 余美元。

### 3.2 权限清单〔实测 — 最关键的一手材料〕

Shopify 强制公开每个 app 的数据访问范围：

```
View customer data
  Device and activity data
    → 地理位置、IP、浏览器与操作系统、浏览行为、client ID cookie
View staff and contributor data
  Store owner → 姓名、邮箱、电话、实际地址
View and edit store data
  Edit products          → 商品、商品 listing、collection
  Edit orders            → 最近 60 天全部订单历史、退货
  Edit store analytics   → Web pixels、报表
  Edit Online Store      → 主题、结算页
  Edit other data        → 商品在销售渠道上的 publication
  View customers         → 浏览行为
  View discounts         → 折扣码与促销
  View Shopify admin     → 法律政策
```

### 3.3 由权限反推的六层架构〔推断〕

**第 1 层 · 授权**：标准 OAuth。推断 scope 组合 `write_products`、
`write_publications`、`write_orders`、`read_customers`、`read_discounts`、
`read_legal_policies`、`write_pixels`、`write_themes`、`read_users`。

**第 2 层 · 摄取**：Admin GraphQL 批量拉商品/变体/库存/价格，
配 `products/update`、`inventory_levels/update` webhook 增量同步。
政策走 `read_legal_policies`，折扣走 `read_discounts`。

**第 3 层 · 上下文增强（唯一有技术含量的一层）**：生成 use case / audience /
buying logic / bundles / shipping。`Edit products` 说明结果**要写回 Shopify**，
几乎必然是 product metafields。

**第 4 层 · 分发（枢纽）**：`Edit other data → Publications of products on
sales channels` 意味着 **Nile 把自己注册成 Shopify 的一个 sales channel
（publication）**，商品发布进去后由 Shopify 自己的 Agentic Storefronts / UCP
管道对外暴露。

> **所以 Nile 不实现 UCP 服务端。** 「Works with: UCP」是兼容，不是「我实现了协议」。
> 第 3 层必须写回 metafields，正是因为读取方是 Shopify 而不是 Nile。

**第 5 层 · 归因与计费**：Web Pixel extension 收 client ID cookie + IP +
地理位置 + 浏览行为；`write_orders` 的 60 天窗口 + 退货用于成单归因与退款冲销；
Shopify Billing API usage-based charge 按佣金开票。
`Edit Online Store（主题、结算页）` 大概率是注入落地参数捕获与会话拼接。

**第 6 层 · 商家面板**：Admin 内嵌应用（App Bridge + Polaris），
面板为 sessions / orders / attribution / channel performance / product performance /
reports，外加付费 AI 商品广告管理。

---

## 4. 官网叙事与真实实现的矛盾〔实测〕

### 4.1 「只读 sidecar」是假的

官网 `/solutions/headless-commerce` 原话：

> "Nile needs to read catalog, price, and inventory from your API, PIM, or feed —
> **nothing more**. Storefront, checkout, and OMS code are untouched."

实际权限：Edit products、Edit orders、**Edit Online Store（主题、结算页）**、
Edit store analytics。

### 4.2 归因实现与声明相反

官网：

> "server-side attribution, so measurement does not depend on a browser pixel"

实际申请 Web pixels 权限，采集 client ID cookie、IP、地理位置、浏览行为——
就是浏览器 pixel 归因。（headless 客户可能确实走服务端，Shopify 这条线不是。）

### 4.3 四条 rail 只落地一条，且是借来的

App Store「Works with」：`Checkout · Shopify Admin · Agentic Storefronts ·
ChatGPT · Gemini · Perplexity · UCP`

**无 ACP、无 MCP、无 Agent Skills。**

端点探测：`/skill`、`/SKILL.md`、`/.well-known/mcp`、`/mcp/sse`、
`/.well-known/ai-plugin.json` **全部 404**；`/mcp` 与 `/api` 404 且被 robots 屏蔽。
官网「Nile Skills — Install in your agent」指向 `/waitlist?intent=pro`
（等待列表表单）。

### 4.4 评论数据没有权限来源

官网称 reviews 进 brand context 用于解释商品适配性。但 Shopify 原生无评论对象
（评论都在 Judge.me / Yotpo / Okendo 等第三方 app），而 Nile 未申请相关权限。

### 4.5 定价与主体不一致

App Store 写「Commission starts at 1%」，官网写「2–15%」。
主体是 FIFTEEN AI 而非 Nile。域名从 `nohi.ai`（现 DNS 失效，探测返回 000）
迁到 `nile.app`，Twitter 仍挂 `x.com/ShopNohi`，研究仓库描述仍是
"Nohi Readiness Index 2026"，逐品牌审计 JSON 的 `disclosure` 仍指向 `nohi.ai`。

---

## 5. 交叉验证结果（geolook 引擎 vs Nile 判据）

### 5.1 方法

样本：他们公开的 `scores.csv`（50 品牌，CC BY 4.0）。
复刻 C1–C7，调用 geolook 自身函数（RFC 9309 robots 判定、`analyze_page`、
`score_page`、UA 差异探测）。串行 + 退避 + 品牌间隔，92 分钟，零限流污染。

**重要前提**：他们评分于 **2026-04-18**，本次复现 **2026-08-22**，间隔 4 个月。
除 C3 外的差异无法干净地区分「口径差异」与「站点变化」。

### 5.2 总体

39 个七项全测出：偏高 28、持平 8、偏低 3，均值 **+1.03**。

### 5.3 逐判据归因

| 判据 | 一致率 | 我过它不过 | 它过我不过 | 净贡献 |
|---|---|---|---|---|
| C3 sitemap 新鲜度 | **51%** | 19 | **0** | **+19** |
| C5 Review schema | 72% | 10 | 1 | +9 |
| C2 PDP 服务端渲染 | 72% | 8 | 3 | +5 |
| C6 FAQPage/HowTo | 87% | 5 | 0 | +5 |
| C4 Product schema | 74% | 7 | 3 | +4 |
| C1 AI 爬虫放行 | 95% | 2 | 0 | +2 |
| C7 Organization | 90% | 0 | 4 | **−4** |
| | | | | **+40** |

### 5.4 C3 是确定性 bug（证据闭环）

19 个「他们判 fail 我判 pass」的品牌，`lastmod` **全部**带非 UTC 时区偏移：

```
Glow Recipe            2026-08-22T05:22:59-04:00   0天前   123 个商品页
Herbivore Botanicals   2026-08-22T02:27:12-07:00   0天前    54
Kosas                  2026-08-22T02:31:30-07:00   0天前    72
Rare Beauty            2026-08-22T03:03:00-07:00   0天前   134
```

三个条件同时成立：**方向 100% 单向**（19 : 0）、**全部命中触发条件**、
**有异常原文**（Adwoa Beauty 的 `fetch_error` 为
`can't compare offset-naive and offset-aware datetimes`）。

站点改版不会产生「只朝一个方向错、且全部集中在带时区偏移的样本上」这种形态。

### 5.5 必须如实披露的反向项

- **C7 的 −4 是我们更严**：我要求 `name` + `url` + `≥2 个 sameAs` 在同一个
  Organization 节点上，他们大概跨节点合并判。这 4 分算我们头上
- **C5 的 +9 无法归因**：他们文章明确写了「启用 review schema 是最快的 +1」，
  4 个月里品牌方真去开了 widget 开关是完全合理的解释。
  **这部分差异可能恰恰是他们那份报告起了作用**
- **我方解析更松**：C2 的描述判据（词数 ≥50 或 LD 有 description）、
  C4/C5 递归展开 `@graph`，这部分偏高算我们的

### 5.6 更严重的方法论缺陷：「测不到」记成 0 分

11 个品牌无法七项全测，而他们给其中 5 个记了**真实分数**：

| 品牌 | Nile 官方分 | 实测首页 | 真实情况 |
|---|---|---|---|
| Drunk Elephant | 2 | **200** | 站通，仅 PDP 取样失败 |
| Biossance | 2 | **200** | 同上 |
| Item Beauty | 1 | **200** | 同上 |
| Briogeo | 3 | **200** | 同上 |
| Adwoa Beauty | 0 | **200** | 纯粹自家 scorer 崩了 |
| Topicals | 1 | 0（SSL 证书错误） | 两边都抓不到 |

Adwoa 更被写进文章排除组，理由称「bot 防护、DNS 问题」——实测首页 200、
7 个 AI 爬虫全放行。

**他们判对的也要说清**：Tata Harper、Youth To The People（我方 403）、
Violette_FR、Ami Colé、Pinch of Color 五个实测同样抓不到，排除是对的。

「中位数 4/9」「零品牌达到 Agent-Ready」这些头条结论建立在这个混淆上。

### 5.7 geolook 独有层（他们的 9 条判据看不到）

40 品牌 120 个 PDP：

```
六维均分        53.0 / 100
平均词数        683 词        （1000 词是高影响力门槛）
可引段落        105 / 478 = 22.0%
零可引段落品牌  10 / 40
评级分布        A:2  B:30  C:53  D:35   → 73% 是 C/D
```

段落级分辨率的 Content Cliff：他们的 C9 说「描述不够好」（通过率 12.5%），
geolook 能说「478 个小节里只有 105 个含数字/定义/步骤」。

### 5.8 自查不合格、不可发布的数字

`llms.txt 41/50`（82% 采纳率）**不可信**：`fetch_text` 只看 200，
而很多 Shopify 站对不存在路径返回 200 + 404 页面模板，大概率被软 404 灌水。
要用必须先加内容特征校验——**这本身是 geolook 该修的一个真实缺陷**。

### 5.9 顺带修掉的 geolook bug

第一轮跑批（5 并发）50 个品牌里 24 个撞 HTTP 429，数据全废。
过程中暴露 `crawl.probe_ai_ua` 把 429/503 与 403 混为「WAF 封禁 AI 爬虫」，
会系统性误报并诱导用户去动 WAF（最高风险改造）。已修：429/503 分流到
`ai_ua_rate_limited`（判为未测），加退避重试与默认 UA 基线对照。
修复前报 4 个假阳性，修复后归零，87 测试全过。

---

## 6. 复刻难度评估

### 6.1 可完整复刻：整个技术栈

| 组件 | 难度 |
|---|---|
| 官网那套（零 JS 静态 + 7 种 JSON-LD + 三段式 llms.txt） | 低，纯内容工程 |
| Shopify app 骨架（OAuth + Admin API + webhook） | 低，官方模板 |
| 上下文增强 | **中，唯一核心** |
| 分发（注册 publication，交给 Shopify） | 低 |
| 归因（Web Pixel + orders webhook） | 中 |
| 计费（Billing API usage charge） | 低 |
| SKILL.md | 极低 |
| MCP server | 低（stdio JSON-RPC） |

### 6.2 修正一个早期误判

拆解初期我判断「ACP/UCP 的平台准入是不可复刻的护城河」——那是基于**营销声明**。
按权限清单看，真实产品没做 ACP/MCP/Agent Skills，走的是 Shopify 已有的
publication 机制。**那道护城河他们自己也没跨过去。**

真正的门槛只剩：Shopify 应用审核（申请 `write_themes` 和结算页访问会触发更严审核）
与商家获取——都不是技术门槛。

### 6.3 结论：为什么不做 Shopify app

技术上完全可行，但：

- **Shopify 应用商店是封闭渠道**，审核周期、分成规则、分类位置都不由你控制
- **会把 geolook 从「自托管开源平台」拉向「SaaS 插件」**，与
  「数据全在自己机器上、`git init` 就是备份」的定位直接冲突
- **对手结构性打不到的地方在别处**：Nile 在 `/compare` 打 GEO 工具的论点
  只在电商 SKU 场景成立，B2B / SaaS / 专业服务没有 SKU 可上架，
  而那是 GEO 的主战场

更贴合定位的做法是**做他们没做出来的那部分**：把 geolook 编译成
MCP server + SKILL.md。见 `../P2-compile-targets.md`。
