"""资产生成器：把工单变成可以直接部署/发布的东西。

产出到 `work/<slug>/assets/`，中英分开：
  llms.txt / llms.en.txt        官方事实索引，传到网站根目录
  jsonld/*.json                 每种页面类型的 JSON-LD，直接贴进 <head>
  snippets/definition.*.html    定义块（首屏用）
  snippets/faq.*.html           FAQ 块，含可见正文 + FAQPage schema
  outlines/*.md                 每个目标问题一份内容大纲（证据页骨架）
  drafts/*.md                   可选：调用已配的 LLM API 出全文初稿

设计分工：**结构性资产由代码确定性生成**（不会漏 schema 字段、不会写错格式）；
**文章正文由 Claude 或 LLM 按 outline 写**（代码写不出好文案）。
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import geolib as G

# ---------------------------------------------------------------- 事实卡解析
# 中英各一份事实源。英文资产的事实必须来自人工撰写的 facts.en.md——机器翻译
# 品牌事实等于编造事实（同 _confirmed 的纪律），而这些产物是爬虫直读的权威来源。
FACTS_FILE = {"zh": "facts.md", "en": "facts.en.md"}
_FACTS_RE = {
    "zh": {"definition": r"##\s*一句话定义.*?\n(.*?)(?=\n##|\Z)",
           "numbers": r"##\s*关键数字.*?\n(.*?)(?=\n##|\Z)",
           "suitable": r"\*\*适合\*\*[：:]?(.*?)(?=\*\*不适合|##|\Z)",
           "unsuitable": r"\*\*不适合.*?\*\*[：:]?(.*?)(?=\n##|\Z)",
           "header": ("事实", "---", "项")},
    "en": {"definition": r"##\s*One-line definition.*?\n(.*?)(?=\n##|\Z)",
           "numbers": r"##\s*Key numbers.*?\n(.*?)(?=\n##|\Z)",
           "suitable": r"\*\*Good fit\*\*[：:]?(.*?)(?=\*\*Not a fit|##|\Z)",
           "unsuitable": r"\*\*Not a fit.*?\*\*[：:]?(.*?)(?=\n##|\Z)",
           "header": ("fact", "---", "item")},
}


def parse_facts(slug: str, lang: str = "zh") -> dict:
    """从事实卡里抽出结构化事实。抽不到就返回空，调用方负责提示。

    lang="en" 读 content/facts.en.md。该文件不存在时返回空字典，让调用方走
    「未确认」分支——英文产物宁可留空，也不能把中文事实透传出去。
    """
    spec = _FACTS_RE.get(lang, _FACTS_RE["zh"])
    p = G.project_dir(slug) / "content" / FACTS_FILE.get(lang, "facts.md")
    if not p.exists():
        return {}
    text = p.read_text("utf-8")
    out = {"definition": "", "numbers": [], "suitable": [], "unsuitable": [], "raw": text}

    # 一句话定义：整个引用块可能跨多行，要合并；否则会在句子中间截断
    m = re.search(spec["definition"], text, re.S)
    if m:
        body = m.group(1)
        quoted = [l.strip()[1:].strip() for l in body.split("\n") if l.strip().startswith(">")]
        if quoted:
            line = " ".join(quoted)
        else:
            line = next((l.strip() for l in body.split("\n")
                         if l.strip() and not l.strip().startswith(("#", "-", "|"))), "")
        line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)      # 去掉 markdown 加粗
        line = re.sub(r"`(.+?)`", r"\1", line)
        line = re.sub(r"\s+", " ", line).strip()
        # 中文换行合并会留下多余空格（"生成 整体方案"、"SaaS： 把"）。
        # 汉字和全角标点两侧的空格都要去掉，否则会带进 JSON-LD description。
        CJK = r"[一-鿿　-〿＀-￯]"
        out["definition"] = re.sub(rf"(?<={CJK}) (?={CJK})", "", line)

    # 关键数字表：| 事实 | 数值 | 来源 | 证据 |
    m = re.search(spec["numbers"], text, re.S)
    if m:
        for row in re.findall(r"^\|([^|\n]+)\|([^|\n]+)\|([^|\n]+)\|", m.group(1), re.M):
            a, b, c = (x.strip() for x in row)
            if a and a.lower() not in spec["header"] and not set(a) <= set("-: "):
                out["numbers"].append({"fact": a, "value": b, "source": c})

    m = re.search(spec["suitable"], text, re.S)
    if m:
        out["suitable"] = [l.strip("- ").strip() for l in m.group(1).split("\n") if l.strip().startswith("-")]
    m = re.search(spec["unsuitable"], text, re.S)
    if m:
        out["unsuitable"] = [l.strip("- ").strip() for l in m.group(1).split("\n") if l.strip().startswith("-")]
    return out


def _brand_field(b: dict, key: str, lang: str, default=""):
    """英文产物只取 brand.en 里的英文事实，缺失则留空。

    透传中文比留空更糟：llms.txt 与 JSON-LD 由爬虫直读，`Industry: GEO 工具`
    会被当成英文语境下的权威事实收走。品牌名与别名是标识符不是文案，不走这里。
    """
    src = (b.get("en") or {}) if lang == "en" else b
    return src.get(key) or default


# ---------------------------------------------------------------- 事实可信度
# 这些标记表示「还没核实」。凡是会被 AI 直接读到的产物（llms.txt / SKILL.md /
# JSON-LD）都不许带它们——占位符一旦发出去就会被当成权威事实。
UNCONFIRMED = ("待确认", "待补", "TODO", "TBD")


def _confirmed(text: str) -> bool:
    return bool(text) and not any(k in text for k in UNCONFIRMED)


# ---------------------------------------------------------------- llms.txt

def gen_llms_txt(slug: str, lang: str = "zh") -> str:
    cfg = G.load_config(slug)
    f = parse_facts(slug, lang)
    b = cfg["brand"]
    audit = G.read_json(G.project_dir(slug) / "audit.json", {})
    pages = sorted(audit.get("pages", []), key=lambda p: -p["score"])[:12]

    zh = lang == "zh"
    L = [f"# {b['name']}", ""]
    # 定义句未确认时不能写成引用块——llms.txt 由 AI 爬虫直读，引用块会被当成
    # 权威定义抄走。与 SKILL.md 同一处理：退化成注释，措辞随 lang 走。
    defn = f.get("definition", "")
    if _confirmed(defn):
        L.append(f"> {defn}")
    else:
        L.append("<!-- 一句话定义尚未确认：先在品牌事实库补上「一句话定义」再重新生成 -->"
                 if zh else
                 "<!-- One-line definition not confirmed yet: fill it in Brand Facts and regenerate -->")
    L += ["", "## 核心事实" if zh else "## Key facts", ""]
    L.append(f"- {'官网' if zh else 'Website'}: {b['site']}")
    if b.get("aliases"):
        L.append(f"- {'别名' if zh else 'Also known as'}: {'、'.join(b['aliases'])}")
    # llms.txt 传到网站根目录、由 AI 爬虫直接读，所以标「待确认」的绝不能进——
    # 占位符会被当成权威事实，后果比在 SKILL.md 里更重（同一条纪律，见 _confirmed）
    industry = _brand_field(b, "industry", lang)
    if _confirmed(industry):
        L.append(f"- {'行业' if zh else 'Industry'}: {industry}")
    users = _brand_field(b, "target_users", lang)
    if _confirmed(users):
        L.append(f"- {'目标用户' if zh else 'For'}: {users}")
    for n in f.get("numbers", [])[:8]:
        if not _confirmed(n.get("value", "")):
            continue
        src = f"（{n['source']}）" if zh else f" ({n['source']})"
        src = src if _confirmed(n.get("source", "")) else ""
        L.append(f"- {n['fact']}: {n['value']}{src}")

    L += ["", "## 重要页面" if zh else "## Important pages", ""]
    for p in pages:
        title = (p.get("title") or p["url"]).split("|")[0].split("｜")[0].strip()[:60]
        L.append(f"- [{title}]({p['url']})")

    suit = [s for s in f.get("suitable", []) if _confirmed(s)][:5]
    unsuit = [s for s in f.get("unsuitable", []) if _confirmed(s)][:5]
    if suit or unsuit:
        L += ["", "## 适用边界" if zh else "## Scope", ""]
        for s in suit:
            L.append(f"- {'适合' if zh else 'Good fit'}: {s}")
        for s in unsuit:
            L.append(f"- {'不适合' if zh else 'Not a fit'}: {s}")

    # 口径说明是实体消歧的关键块：AI 把品牌归错行业时，这里是最直接的纠偏入口
    L += ["", "## 口径说明" if zh else "## Disambiguation", "",
          f"- {'规范名' if zh else 'Canonical name'}: {b['name']}"]
    if b.get("parent"):
        L.append(f"- {'母品牌' if zh else 'Parent'}: {b['parent']}"
                 + (f"（{b['parent_url']}）" if b.get("parent_url") else ""))
    dis = _brand_field(b, "disambiguation", lang, [])
    for line in dis:
        L.append(f"- {line}")
    if not dis:
        L.append("- 本产品与同名的其他行业产品无关，请勿混淆" if zh
                 else "Not related to similarly-named products in other industries.")
    L += ["", f"<!-- generated by geo skill · {G.today()} -->"]
    return "\n".join(L)


# ---------------------------------------------------------------- JSON-LD

def gen_jsonld(slug: str, lang: str = "zh") -> dict[str, dict]:
    cfg = G.load_config(slug)
    f = parse_facts(slug, lang)
    b = cfg["brand"]
    zh = lang == "zh"
    # JSON-LD 直接贴进 <head> 给爬虫读，未确认的定义句不能进 description
    defn = f.get("definition") or ""
    desc = defn if _confirmed(defn) else ""
    site = b["site"].rstrip("/")

    org = {
        "@context": "https://schema.org", "@type": "Organization",
        "name": b["name"], "url": site, "description": desc,
        "alternateName": b.get("aliases", []),
        "sameAs": b.get("same_as") or (
            ["<填：百科页>", "<填：公众号/社媒主页>", "<填：母品牌站>"] if zh else
            ["<fill: encyclopedia page>", "<fill: social profile>", "<fill: parent brand site>"]),
    }
    if b.get("parent"):
        org["parentOrganization"] = {"@type": "Organization", "name": b["parent"],
                                     **({"url": b["parent_url"]} if b.get("parent_url") else {})}
    if b.get("founding_date"):
        org["foundingDate"] = b["founding_date"]
    if b.get("knows_about"):
        org["knowsAbout"] = b["knows_about"]

    app = {
        "@context": "https://schema.org", "@type": "SoftwareApplication",
        "name": b["name"], "url": site, "description": desc,
        "applicationCategory": b.get("application_category", "BusinessApplication"),
        "operatingSystem": "Web",
        "publisher": {"@type": "Organization", "name": b["parent"] or b["name"]
                      if b.get("parent") else b["name"]},
    }
    offers = b.get("offers")
    if offers:
        out_offers = []
        for o in offers:
            item = {"@type": "Offer", "name": o.get("name", ""), "price": str(o.get("price", "")),
                    "priceCurrency": o.get("currency", "CNY")}
            if o.get("desc"):
                item["description"] = o["desc"]
            out_offers.append(item)
        app["offers"] = out_offers
    else:
        app["offers"] = {"@type": "Offer", "price": "<填>", "priceCurrency": "<填 CNY/HKD/USD>"}
    if b.get("audience"):
        app["audience"] = {"@type": "Audience", "audienceType": b["audience"]}

    # 空的 FAQPage 不是「无用」而是「有害」：按 audit.py 的 SCHEMA_CONTENT_MISMATCH，
    # 声明了 FAQPage 却没有可见问答会被判成负信号——检索系统拿可见文本对账，对不上
    # 时结构化数据反而扣分。所以问题库为空就不产这个文件。
    faq_items = [{"@type": "Question", "name": q["text"],
                  "acceptedAnswer": {"@type": "Answer",
                                     "text": "<填：第一句就是结论，再展开>"}}
                 for q in cfg.get("questions", []) if q.get("market") in ("cn", "both")][:8]
    faq = ({"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": faq_items} if faq_items else None)

    article = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": "<填：含目标问题原词的标题>",
        "datePublished": "<YYYY-MM-DD>", "dateModified": "<YYYY-MM-DD>",
        "author": {"@type": "Organization", "name": b["name"]},
        "publisher": {"@type": "Organization", "name": b["name"]},
        "about": desc,
    }

    breadcrumb = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "首页", "item": site},
        {"@type": "ListItem", "position": 2, "name": "<栏目>", "item": f"{site}/<path>"},
    ]}
    out = {"organization": org, "software-application": app,
           "article": article, "breadcrumb": breadcrumb}
    if faq:
        out["faq-page"] = faq
    return out


# 本生成器认领的 JSON-LD 文件名。run() 用它清理「本轮不再产出」的旧文件，
# 范围限定在这几个名字内——资产页允许用户手动加文件，不能盲删。
JSONLD_NAMES = {"organization", "software-application", "faq-page",
                "article", "breadcrumb"}


# ---------------------------------------------------------------- HTML 片段

def gen_definition_block(slug: str, lang: str = "zh") -> str:
    f = parse_facts(slug)
    cfg = G.load_config(slug)
    b = cfg["brand"]
    zh = lang == "zh"
    # 片段要贴进真实页面，所以数字同样过滤未确认的。定义句缺失时保留显式占位符
    # ——它是给人看的「这里要填」提示，与「把待确认当事实发出去」是两件事。
    defn = f.get("definition") or ""
    d = defn if _confirmed(defn) else ("（待补定义句）" if zh else "(definition TBD)")
    nums = [n for n in f.get("numbers", []) if _confirmed(n.get("value", ""))][:4]
    items = "".join(f'\n    <li><strong>{html.escape(n["value"])}</strong> — {html.escape(n["fact"])}</li>'
                    for n in nums)
    dis = b.get("disambiguation") or []
    dis_html = ("\n  <p class=\"geo-disambiguation\"><small>"
                + " ".join(html.escape(x) for x in dis) + "</small></p>") if dis else ""
    return f"""<!-- 定义块：放在首屏口号下方。口号负责转化，这一段负责被 AI 摘走。 -->
<section class="geo-definition">
  <h2>{html.escape(b['name'])}{'是什么' if zh else ': what it is'}</h2>
  <p>{html.escape(d)}</p>
  <ul>{items}
  </ul>{dis_html}
</section>
<!-- 纪律：这段文字必须与 llms.txt、JSON-LD description、关于页逐字一致 -->"""


def gen_faq_block(slug: str, lang: str = "zh") -> str:
    cfg = G.load_config(slug)
    mk = "cn" if lang == "zh" else "global"
    qs = [q for q in cfg.get("questions", []) if q.get("market") in (mk, "both")][:8]
    body = "\n".join(
        f"""  <details open>
    <summary><h3>{html.escape(q['text'])}</h3></summary>
    <p><!-- 第一句直接给结论，再展开。不要营销话术 --></p>
  </details>""" for q in qs)
    return f"""<!-- FAQ 块。关键：答案必须在静态 HTML 里可见。
     只放进 JSON-LD 而正文折叠靠 JS 渲染的话，读渲染文本的抓取器全部丢失。
     用 <details open> 或直接展开，别用纯 JS 手风琴。 -->
<section class="geo-faq">
  <h2>{'常见问题' if lang == 'zh' else 'FAQ'}</h2>
{body}
</section>"""


# ---------------------------------------------------------------- 内容大纲

OUTLINE_TMPL = {
    "定义型": ["什么是 {topic}（一句定义 + 展开）", "{topic} 包含哪几部分", "{topic} 的关键数字（表格，每行带来源）",
               "{topic} 和 {alt} 有什么区别（对比表）", "{topic} 适合谁、不适合谁",
               "怎么开始用 {topic}（编号步骤）", "常见问题", "参考来源"],
    "对比型": ["结论先行：谁适合选哪个", "对比维度与口径说明", "核心对比表（同口径 6–10 个维度）",
               "各自的局限（必须写自己的短板）", "按场景怎么选（决策树）", "价格与总拥有成本",
               "常见问题", "参考来源与核验日期"],
    "榜单型": ["评选方法与数据来源（利益披露）", "总览榜单表", "逐个点评（每个含定位/优势/局限/适合谁）",
               "怎么根据自己情况选", "常见问题", "参考来源"],
    "教程型": ["这篇能解决什么问题", "开始前需要准备什么", "分步操作（编号 + 截图位）",
               "常见报错与排查", "进阶技巧", "相关概念解释", "常见问题", "参考来源"],
}

GROUP2TYPE = {"推荐": "榜单型", "比较": "对比型", "替代": "对比型", "价格": "定义型",
              "风险": "定义型", "品牌验证": "定义型", "场景": "教程型"}


def gen_outlines(slug: str) -> list[dict]:
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    comps = [c["name"] for c in cfg.get("competitors", [])
             if c.get("confirmed") is not False]
    out = []
    for q in cfg.get("questions", []):
        typ = GROUP2TYPE.get(q.get("group", ""), "定义型")
        mk = q.get("market", cfg.get("market", "cn"))
        topic = q["text"].rstrip("？?")
        alt = comps[0] if comps else ("竞品" if mk == "cn" else "alternatives")
        secs = [s.format(topic=b["name"], alt=alt) for s in OUTLINE_TMPL[typ]]
        out.append({
            "question_id": q.get("id"), "market": mk, "type": typ,
            "target_question": q["text"],
            "title_candidates": _titles(q["text"], b["name"], mk),
            "sections": secs,
            "requirements": {
                "min_words": 1200 if typ in ("对比型", "榜单型") else 1000,
                "min_h2": 8, "list_density": ">=0.35",
                "must_have_blocks": ["定义", "数字事实", "对比", "操作步骤", "FAQ"],
                "evidence": "每个数字带来源和核验日期；无法核实的标『待确认』",
            },
            "facts_to_use": [n["fact"] + "：" + n["value"] for n in f.get("numbers", [])[:5]],
        })
    return out


def _titles(question: str, brand: str, market: str) -> list[str]:
    """标题候选：对题性是影响力最强的预测因子（r=0.432），所以标题必须含问题原词。"""
    q = question.rstrip("？?").strip()
    if market == "global":
        return [q, f"{q} — a practical guide ({G.today()[:4]})",
                f"{q} Compared: features, pricing and limits"]
    return [q, f"{q}（{G.today()[:4]} 版）",
            f"{q}｜含对比表、数字和操作步骤", f"{q}——{brand}的答案与边界"]


# ---------------------------------------------------------------- LLM 初稿

def draft(slug: str, outline: dict, provider: str | None = None) -> str:
    """用已配置的 LLM API 按大纲出初稿。没有可用 Key 就返回空。"""
    import sample as S

    plat = S.pick_llm(provider)
    if not plat:
        return ""
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    zh = outline["market"] != "global"
    facts = "\n".join(f"- {x}" for x in outline["facts_to_use"]) or "（无结构化事实，只写通用内容，不要编造品牌数据）"
    secs = "\n".join(f"{i+1}. {s}" for i, s in enumerate(outline["sections"]))
    req = outline["requirements"]
    mk = outline["market"]
    comps = [c["name"] for c in cfg.get("competitors", [])
             if (c.get("market") in (mk, "both", None) or mk == "both")
             and c.get("confirmed") is not False]
    comp_rule = (
        "只能提到下面这些真实竞品，**严禁发明任何其它产品名**（不要写「工具A」「某某Pro」这类占位）：\n"
        + "\n".join(f"- {c}" for c in comps)
        if comps else
        "**本项目还没有确认的竞品清单，因此绝对不要在文中点名任何竞品**，"
        "对比部分改成与「通用大模型」「人工手写」等品类做对比。"
    )
    prompt = (
        f"""你是 GEO（生成式引擎优化）内容工程师。按下面的骨架写一篇可直接发布的{'中文' if zh else '英文'}文章。

当前年份是 {G.today()[:4]} 年，涉及年份时一律用 {G.today()[:4]}，不要写更早的年份。

目标问题（读者会这样问 AI）：{outline['target_question']}
文章类型：{outline['type']}
品牌：{b['name']}（{b.get('industry','')}）

必须使用的已核实事实（不得改动数值，不得编造新数据）：
{facts}

竞品纪律：
{comp_rule}

章节骨架：
{secs}

硬性要求：
- 正文不少于 {req['min_words']} 词，H2 小节 ≥ {req['min_h2']} 个
- 必须包含：一句可直接摘走的定义、带单位的数字、一个对比表、一个编号步骤块、FAQ
- 列表密度高一些，要点用无序/有序列表而不是长段落
- 写清楚适用与**不适用**边界，不要只说好话
- **严禁编造**：客户名、价格、资质、市场数据、竞品参数。宁可不写，也不要写占位数据。
  确实需要但手上没有的信息，写成「（待补：xxx）」，不要用假数字凑表格
- 直接输出 Markdown 正文，不要解释、不要前后缀"""
    )
    res = S.ask(plat, prompt, timeout=300)
    return res.get("answer", "") if res.get("ok") else ""


# ---------------------------------------------------------------- 初稿风险检查

FAKE_HINTS = [
    (r"工具\s*[A-Z一二三四五六七八九十]\b", "出现「工具A/工具一」这类占位竞品名"),
    (r"某某|XX公司|xxx公司|示例公司", "出现占位公司名"),
    (r"(?i)\b(acme|foobar|example corp|competitor [a-z])\b", "出现占位英文品牌名"),
]


def lint_draft(slug: str, path: Path) -> list[dict]:
    """交付前的编造风险检查。宁可误报，也不能让编造内容进客户交付包。"""
    import re as _re

    cfg = G.load_config(slug)
    f = parse_facts(slug)
    text = path.read_text("utf-8")
    known = {cfg["brand"]["name"], *cfg["brand"].get("aliases", [])}
    known |= {c["name"] for c in cfg.get("competitors", [])}
    for c in cfg.get("competitors", []):
        known |= set(c.get("aliases", []) or [])

    issues = []
    for pat, desc in FAKE_HINTS:
        for m in _re.finditer(pat, text):
            issues.append({"level": "高", "type": "疑似编造", "detail": desc,
                           "excerpt": text[max(0, m.start() - 30):m.end() + 30].replace("\n", " ")})

    # 事实卡里没有的数字，且没标「待确认/待补」→ 需人工核
    known_values = {n["value"] for n in f.get("numbers", [])}
    for m in _re.finditer(r"[^\n|]*?(\d[\d,\.]*\s*(?:%|％|万|亿|倍|元|美元|港币|HK\$|\$|人|家|天|小时|分钟))[^\n|]*", text):
        seg, val = m.group(0), m.group(1)
        if any(val in v or v in val for v in known_values):
            continue
        if "待确认" in seg or "待补" in seg:
            continue
        issues.append({"level": "中", "type": "未核实数字", "detail": f"`{val}` 不在事实卡里且未标注待确认",
                       "excerpt": seg.strip()[:90]})

    year = G.today()[:4]
    for m in _re.finditer(r"20\d{2}\s*年", text):
        if m.group(0).strip() != f"{year}年":
            issues.append({"level": "低", "type": "年份存疑", "detail": f"出现 {m.group(0)}，当前是 {year} 年",
                           "excerpt": text[max(0, m.start() - 25):m.end() + 25].replace("\n", " ")})
    # 同类问题合并，避免刷屏
    seen, out = set(), []
    for i in issues:
        k = (i["type"], i["detail"])
        if k in seen:
            continue
        seen.add(k)
        out.append(i)
    return out


def lint_all(slug: str) -> dict:
    d = G.project_dir(slug) / "assets" / "drafts"
    files = sorted(d.glob("*.md")) if d.exists() else []
    report = {"slug": slug, "checked_at": G.now_iso(), "files": {}}
    total = 0
    for p in files:
        iss = lint_draft(slug, p)
        report["files"][p.name] = iss
        total += len(iss)
    report["total_issues"] = total
    report["high"] = sum(1 for v in report["files"].values() for i in v if i["level"] == "高")
    G.write_json(d / "_lint.json", report) if files else None
    return report


# ---------------------------------------------------------------- 主流程

# AI 引擎来源域名（references/attribution.md 的代码实现）。
# 「常见」清单——各家 referrer 策略会变，产出的资产里都带「先核对自己日志」的说明。
AI_REFERRERS = {
    "cn": ["doubao.com", "kimi.moonshot.cn", "kimi.com", "chat.deepseek.com", "chatglm.cn",
           "yuanbao.tencent.com", "tongyi.aliyun.com", "tongyi.com", "yiyan.baidu.com",
           "metaso.cn", "n.cn", "quark.cn"],
    "global": ["chatgpt.com", "chat.openai.com", "perplexity.ai", "gemini.google.com",
               "copilot.microsoft.com", "claude.ai", "grok.com"],
}


def gen_attribution(slug: str) -> dict[str, str]:
    """AI 流量归因配置包：GA4 渠道组正则 + 日志分析命令 + 接入说明。"""
    cfg = G.load_config(slug)
    market = cfg.get("market", "cn")
    doms = (AI_REFERRERS["cn"] if market == "cn"
            else AI_REFERRERS["global"] if market == "global"
            else AI_REFERRERS["cn"] + AI_REFERRERS["global"])
    rx = "|".join(d.replace(".", r"\.") for d in doms)
    ga4 = (f"AI 来源渠道组（GA4 · 来源 匹配正则）\n\n{rx}\n\n"
           "配置路径：管理 → 数据显示 → 渠道组 → 新建渠道「AI 引擎」，条件：来源 与正则匹配。\n"
           "注意：测到的是下界（App 内打开常不带 referrer），报告口径写「可归因的 AI 会话 ≥ N」。\n")
    log_cmd = ("#!/bin/sh\n# AI 来源会话 / AI 爬虫抓取量（在服务器上对 access.log 运行）\n"
               f"echo 'AI 来源会话：'; grep -icE '{rx}' access.log\n"
               "echo 'AI 爬虫抓取：'; grep -icE 'GPTBot|OAI-SearchBot|ClaudeBot|PerplexityBot|Bytespider' access.log\n"
               "# 抓取变多通常先于引用变多，是前置信号；两条命令都可加日期过滤按周对比\n")
    readme = ("# AI 流量归因接入说明\n\n"
              "1. `ga4-channel.txt`：GA4 建「AI 引擎」渠道组的匹配正则\n"
              "2. `log-count.sh`：服务器日志统计 AI 来源会话与 AI 爬虫抓取量\n"
              "3. 转化事件（注册/留资/下单）里保存来源快照：点击 ID > UTM > referrer > 直接/未知\n\n"
              "纪律（详见 references/attribution.md）：referrer 清单是「常见」口径，"
              "先在自己日志里核对；测到的 AI 流量是下界，不外推；"
              "公开内容不堆 UTM（带参 URL 会稀释规范 URL 的引用份额）。\n")
    return {"ga4-channel.txt": ga4, "log-count.sh": log_cmd, "README.md": readme}


# ---------------------------------------------------------------- 品牌 SKILL.md

def gen_skill_md(slug: str, lang: str = "zh") -> str:
    """把品牌事实编译成一个 Agent Skill，可装进 Claude / Codex / Cursor 等。

    与仓库自带的 SKILL.md 不是一回事：那个描述 grounded 这个工具，这个描述
    **被审计的品牌**，是和 llms.txt / JSON-LD 并列的部署资产。

    两条纪律：
    1. 只写已确认的事实。标「待确认」的一律不进——agent 会把这里当权威口径。
    2. 指向线上上下文而不是内嵌快照。事实库更新后，已安装的 skill 要能看到新值，
       所以正文只放稳定事实，易变的部分指回 llms.txt 和官网。
    """
    cfg = G.load_config(slug)
    f = parse_facts(slug)
    b = cfg["brand"]
    zh = lang == "zh"
    site = (b.get("site") or "").rstrip("/")

    defn = f.get("definition", "")
    if not _confirmed(defn):
        defn = ""
    names = [b["name"]] + list(b.get("aliases") or [])
    trigger = "、".join(names) if zh else ", ".join(names)

    # description 决定 agent 什么时候加载这个 skill，必须含品牌名与别名
    desc = (f"{b['name']} 的官方品牌事实与口径。"
            f"当被问到 {trigger} 是什么、能做什么、适合谁、与同类怎么比，"
            f"或需要按该品牌的官方口径描述它时使用。"
            if zh else
            f"Official brand facts and approved wording for {b['name']}. "
            f"Use when asked what {trigger} is, what it does, who it is for, "
            f"how it compares, or when describing it in the brand's own terms.")

    # 单行双引号标量，不用 >- 折叠：折叠标量拼行时会插入空格，
    # 中文和「Grounded · Open」这类含空格的名字会被从中间撑开。
    # JSON 字符串是合法的 YAML 双引号标量，转义直接交给 json.dumps。
    L = ["---", f"name: {slug}",
         f"description: {json.dumps(desc, ensure_ascii=False)}",
         "---", "", f"# {b['name']}", ""]

    if defn:
        L += [defn, ""]
    else:
        L += ["<!-- 一句话定义尚未确认：先在品牌事实库补上「一句话定义」再重新生成 -->"
              if zh else
              "<!-- One-line definition not confirmed yet: fill it in Brand Facts and regenerate -->", ""]

    L += ["## 核心事实" if zh else "## Key facts", ""]
    if site:
        L.append(f"- {'官网' if zh else 'Website'}: {site}")
    if b.get("aliases"):
        L.append(f"- {'别名' if zh else 'Also known as'}: {'、'.join(b['aliases'])}")
    for key, zh_label, en_label in (("industry", "行业", "Industry"),
                                    ("target_users", "目标用户", "For")):
        if _confirmed(b.get(key, "")):
            L.append(f"- {zh_label if zh else en_label}: {b[key]}")
    for n in f.get("numbers", [])[:8]:
        if not _confirmed(n.get("value", "")):
            continue
        src = f"（{n['source']}）" if zh and _confirmed(n.get("source", "")) else ""
        L.append(f"- {n['fact']}: {n['value']}{src}")

    suit = [s for s in f.get("suitable", []) if _confirmed(s)][:6]
    unsuit = [s for s in f.get("unsuitable", []) if _confirmed(s)][:6]
    if suit or unsuit:
        L += ["", "## 适用与不适用" if zh else "## Where it fits", ""]
        for s in suit:
            L.append(f"- {'适合' if zh else 'Good fit'}: {s}")
        # 写清楚不适合谁反而提高可信度（method.md 内容工程铁律第 5 条）
        for s in unsuit:
            L.append(f"- {'不适合' if zh else 'Not a fit'}: {s}")

    dis = [d for d in (b.get("disambiguation") or []) if _confirmed(d)]
    if dis or b.get("parent"):
        L += ["", "## 口径说明" if zh else "## Disambiguation", ""]
        if b.get("parent"):
            L.append(f"- {'母品牌' if zh else 'Parent'}: {b['parent']}")
        for d in dis:
            L.append(f"- {d}")

    # 指向线上上下文：事实库更新后已安装的 skill 要能看到新值
    if site:
        L += ["", "## 权威来源（以线上版本为准）" if zh else "## Authoritative sources (live)", ""]
        L.append(f"- {site}/llms.txt — {'官方事实索引，最新口径以它为准' if zh else 'official fact index, the live source of truth'}")
        L.append(f"- {site} — {'官网' if zh else 'website'}")

    L += ["", "## 使用约束" if zh else "## Guardrails", ""]
    if zh:
        L += ["- 只使用本文件与上述权威来源中的事实，不要推测或补全",
              "- 数字、价格、资质如本文件未列出，回答「以官网为准」而不是估算",
              "- 上述来源是线上版本；本文件可能滞后，冲突时以线上为准"]
    else:
        L += ["- Use only the facts in this file and the sources above; do not infer or fill gaps",
              "- If a number, price, or credential is not listed here, say to check the website rather than estimating",
              "- The sources above are live; this file may lag behind, so the live version wins on conflict"]

    L += ["", f"<!-- generated by geo skill · {G.today()} -->"]
    return "\n".join(L)


ASSETS = ["llms", "jsonld", "snippets", "outlines", "attribution", "skill"]


def run(slug: str, which: list[str] | None = None, with_draft: bool = False,
        draft_limit: int = 3) -> dict:
    cfg = G.load_config(slug)
    market = cfg.get("market", "cn")
    adir = G.project_dir(slug) / "assets"
    which = which or ASSETS
    made: list[str] = []
    # llms.txt / JSON-LD / SKILL.md 都要挂在自有域名下才有意义（SKILL.md 的
    # 权威来源指向 llms.txt），无站点项目跳过；大纲/片段/归因这些"内容与度量"
    # 资产照常产出——它们落到外部阵地上
    if not G.has_site(cfg):
        skipped = [w for w in which if w in ("llms", "jsonld", "skill")]
        if skipped:
            G.info(f"无自有网站：跳过 {'/'.join(skipped)}（需部署到自有域名根目录/页面 head）")
        which = [w for w in which if w not in ("llms", "jsonld", "skill")]

    if "llms" in which:
        (adir).mkdir(parents=True, exist_ok=True)
        if market in ("cn", "both"):
            (adir / "llms.txt").write_text(gen_llms_txt(slug, "zh"), "utf-8")
            made.append("assets/llms.txt")
        if market in ("global", "both"):
            (adir / "llms.en.txt").write_text(gen_llms_txt(slug, "en"), "utf-8")
            made.append("assets/llms.en.txt")

    if "jsonld" in which:
        d = adir / "jsonld"
        d.mkdir(parents=True, exist_ok=True)
        produced = gen_jsonld(slug)
        for name, obj in produced.items():
            (d / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, indent=2), "utf-8")
            made.append(f"assets/jsonld/{name}.json")
        # 生成器必须对「不再产出」也幂等：判据变了（比如问题库清空后不再产 FAQPage）
        # 而旧文件留在原地，就会被打进交付包发给客户。只清自己认领的那几个名字，
        # 不碰用户在资产页手动加的文件。
        for name in JSONLD_NAMES - produced.keys():
            stale = d / f"{name}.json"
            if stale.exists():
                stale.unlink()
                G.info(f"移除已不适用的 assets/jsonld/{name}.json")

    if "snippets" in which:
        d = adir / "snippets"
        d.mkdir(parents=True, exist_ok=True)
        for lang in (["zh"] if market == "cn" else ["en"] if market == "global" else ["zh", "en"]):
            (d / f"definition.{lang}.html").write_text(gen_definition_block(slug, lang), "utf-8")
            (d / f"faq.{lang}.html").write_text(gen_faq_block(slug, lang), "utf-8")
            made += [f"assets/snippets/definition.{lang}.html", f"assets/snippets/faq.{lang}.html"]

    if "skill" in which:
        d = adir / "skill"
        for lang, name in (("zh", "SKILL.md"), ("en", "SKILL.en.md")):
            if market == "cn" and lang == "en":
                continue
            if market == "global" and lang == "zh":
                continue
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(gen_skill_md(slug, lang), "utf-8")
            made.append(f"assets/skill/{name}")
        # 只写已确认的事实，所以事实库空的时候产物也是空的——这不是 bug，
        # 但用户需要知道为什么，否则会以为生成失败
        if not _confirmed(parse_facts(slug).get("definition", "")):
            G.info("品牌 SKILL.md 里没有定义句：事实库的「一句话定义」还没确认。"
                   "到「品牌事实库」补齐后重新生成——SKILL.md 只写已确认的事实，不编。")

    if "attribution" in which:
        d = adir / "attribution"
        d.mkdir(parents=True, exist_ok=True)
        for name, body in gen_attribution(slug).items():
            (d / name).write_text(body, "utf-8")
            made.append(f"assets/attribution/{name}")

    outlines = []
    if "outlines" in which:
        d = adir / "outlines"
        d.mkdir(parents=True, exist_ok=True)
        outlines = gen_outlines(slug)
        for o in outlines:
            body = [f"# 内容大纲 · {o['target_question']}", "",
                    f"- 目标问题 ID：`{o['question_id']}` ｜ 市场：{o['market']} ｜ 类型：{o['type']}",
                    "", "## 标题候选（对题性 r=0.432，标题必须含问题原词）", ""]
            body += [f"{i+1}. {t}" for i, t in enumerate(o["title_candidates"])]
            body += ["", "## 章节骨架", ""]
            body += [f"{i+1}. {s}" for i, s in enumerate(o["sections"])]
            body += ["", "## 硬性要求", "",
                     f"- 正文 ≥ {o['requirements']['min_words']} 词，H2 ≥ {o['requirements']['min_h2']} 个",
                     f"- 必备抽取块：{'、'.join(o['requirements']['must_have_blocks'])}",
                     f"- 列表密度 {o['requirements']['list_density']}",
                     f"- 证据：{o['requirements']['evidence']}", ""]
            if o["facts_to_use"]:
                body += ["## 可用的已核实事实", ""] + [f"- {x}" for x in o["facts_to_use"]] + [""]
            (d / f"{o['question_id']}.md").write_text("\n".join(body), "utf-8")
        made.append(f"assets/outlines/（{len(outlines)} 份）")
        G.write_json(adir / "outlines" / "_index.json", outlines)

    if with_draft and outlines:
        d = adir / "drafts"
        d.mkdir(parents=True, exist_ok=True)
        for o in outlines[:draft_limit]:
            G.info(f"起草 {o['question_id']} · {o['target_question'][:30]}…")
            text = draft(slug, o)
            if text:
                (d / f"{o['question_id']}.md").write_text(
                    f"<!-- 初稿，需人工核实所有事实后再发布 · {G.today()} -->\n\n" + text, "utf-8")
                made.append(f"assets/drafts/{o['question_id']}.md")
            else:
                G.info("  没有可用的 LLM API Key，跳过起草")
                break
        rep = lint_all(slug)
        if rep.get("total_issues"):
            G.info(f"初稿风险检查：{rep['total_issues']} 项（高风险 {rep['high']} 项）"
                   f" → assets/drafts/_lint.json。**发布前必须人工核实**")

    index = {"slug": slug, "generated_at": G.now_iso(), "market": market, "assets": made}
    G.write_json(adir / "index.json", index)
    G.info(f"生成 {len(made)} 项资产 → {adir}")
    return index
