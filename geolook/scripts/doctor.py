"""交付前置自检：把一套部署交给用户之前，先确认它真的能用。

存在的理由：引擎接入是**部署环节**配好的，用户不该被要求自己配 key。
但「运维以为配好了」和「真的配好了」之间有一堆静默失效——.env 带 BOM、
key 拼错、依赖没装、端口被占。这些在用户手上表现为「采样怎么不动」，
极难排查。所以交付前跑一次，把问题挡在交付之前。

用法：python3 scripts/geo.py doctor
退出码 0 = 可交付；1 = 有阻塞项。

客户产品端口 8787（geo.py online）；顾问看板仍是 8765（geo.py ui）。
密钥只在本目录 .env，客户网站不会出现填写框。
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import geolib as G

OK, WARN, FAIL = "ok", "warn", "fail"
MARK = {OK: "  ok  ", WARN: " warn ", FAIL: " FAIL "}


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, level: str, item: str, detail: str = "", fix: str = ""):
        self.rows.append((level, item, detail, fix))

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if r[0] == FAIL)

    @property
    def warned(self) -> int:
        return sum(1 for r in self.rows if r[0] == WARN)


def _check_deps(r: Report):
    for mod, pkg in (("requests", "requests"), ("bs4", "beautifulsoup4"),
                     ("lxml", "lxml")):
        try:
            __import__(mod)
            r.add(OK, f"依赖 {pkg}")
        except ModuleNotFoundError:
            r.add(FAIL, f"依赖 {pkg} 未安装", fix=f"pip3 install {pkg}")


def _check_python(r: Report):
    v = sys.version_info
    if v < (3, 9):
        r.add(FAIL, "Python 版本", f"{v.major}.{v.minor}，要求 3.9+")
    else:
        r.add(OK, "Python 版本", f"{v.major}.{v.minor}.{v.micro}")


def _check_env_file(r: Report):
    """.env 的静默失效是最难查的一类，逐条挑明。"""
    p = G.ROOT / ".env"
    if not p.exists():
        r.add(WARN, ".env 不存在", "没有引擎接入，自动采样会整段跳过",
              fix="复制 .env.example 为 .env 后填入 key（客户不填，部署时配）")
        return
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        # 已能正确读取（load_env 用 utf-8-sig），但仍提示——它说明写入方式有问题，
        # 别的工具读这个文件时未必这么宽容
        r.add(WARN, ".env 带 UTF-8 BOM",
              "Grounded 能读，但其他工具可能不能",
              fix="用不带 BOM 的 UTF-8 重写（PowerShell 的 Set-Content -Encoding UTF8 会加 BOM）")
    else:
        r.add(OK, ".env 编码")

    if os.name != "nt":
        mode = p.stat().st_mode & 0o777
        if mode & 0o077:
            r.add(FAIL, ".env 权限过宽", f"{oct(mode)}，同机其他用户可读",
                  fix="chmod 600 .env")
        else:
            r.add(OK, ".env 权限", oct(mode))
    else:
        r.add(WARN, ".env 权限", "Windows 上 chmod 不生效，密钥不受文件权限保护",
              fix="共用机器时用 NTFS 权限限制该文件")

    # 常见笔误：值带引号残留、key 名写错大小写
    for i, line in enumerate(p.read_text("utf-8-sig").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        if k != k.strip() or k != k.upper():
            r.add(WARN, f".env 第 {i} 行键名可疑", k, fix="环境变量名通常全大写、无空格")
        if v.strip() and v.strip()[0] in "\"'" and v.strip()[-1] not in "\"'":
            r.add(WARN, f".env 第 {i} 行引号不闭合", k)


def _check_engines(r: Report):
    import sample as S

    ready = [c for c in S.PROVIDERS if S.available(c)]
    if not ready:
        r.add(WARN, "引擎接入", "0 个可用——自动采样与 AI 推导会被跳过",
              fix="在 .env 里填入至少一个引擎的 key")
        return
    search = [c for c in ready if S.PROVIDERS[c].get("search")]
    cn = [c for c in ready if S.PROVIDERS[c]["market"] == "cn"]
    gl = [c for c in ready if S.PROVIDERS[c]["market"] == "global"]
    r.add(OK, "引擎接入",
          f"{len(ready)}/{len(S.PROVIDERS)} 可用（国内 {len(cn)} · 海外 {len(gl)}）："
          + "、".join(S.PROVIDERS[c]["name"] for c in ready))
    if not search:
        r.add(WARN, "无原生联网引擎",
              "所有已配引擎都不联网，测的是模型参数化知识里的品牌认知",
              fix="加一个 Perplexity 或豆包（开内容插件）以获得引用级证据")
    if not cn:
        r.add(WARN, "国内市场无可用引擎", fix="双市场项目需要至少一个国内引擎")
    if not gl:
        r.add(WARN, "海外市场无可用引擎", fix="双市场项目需要至少一个海外引擎")


def _check_port(r: Report, port: int, label: str, start_hint: str):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        busy = s.connect_ex(("127.0.0.1", port)) == 0
    if busy:
        r.add(WARN, f"{label}端口 {port} 已被占用",
              "新进程会拒绝启动（不会静默绑上别人的服务）",
              fix=start_hint)
    else:
        r.add(OK, f"{label}端口 {port} 可用")


ONLINE = Path(__file__).resolve().parent.parent.parent / "online"


def _check_online(r: Report):
    """客户自助站与 geolook 同级。只交顾问仓时允许缺，但要说清楚。"""
    if not ONLINE.exists():
        r.add(WARN, "客户网站目录不存在",
              "当前安装按顾问工作台交付；客户自助需要仓库根目录的 online/",
              fix="把 online/ 与 geolook/ 放在一起后再跑 geo.py online")
        return
    app = ONLINE / "app.html"
    if not app.exists():
        r.add(FAIL, "客户网站 app.html 缺失",
              fix="不要只拷 geolook/scripts，把 online/app.html 一并交付")
    else:
        r.add(OK, "客户网站界面", "online/app.html")
    data = ONLINE / "data"
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".doctor-probe"
        probe.write_text("x", "utf-8")
        probe.unlink()
        r.add(OK, "online/data/ 可写")
    except OSError as e:
        r.add(FAIL, "online/data/ 不可写", str(e))


def _check_writable(r: Report):
    for rel in ("work", ".jobs"):
        d = G.ROOT / rel
        try:
            d.mkdir(parents=True, exist_ok=True)
            probe = d / ".doctor-probe"
            probe.write_text("x", "utf-8")
            probe.unlink()
            r.add(OK, f"{rel}/ 可写")
        except OSError as e:
            r.add(FAIL, f"{rel}/ 不可写", str(e))


def _check_projects(r: Report):
    if not G.WORK.exists() or not any(G.WORK.iterdir()):
        r.add(WARN, "还没有任何项目", fix="geo.py init --url <网址>")
        return
    slugs = [d.name for d in sorted(G.WORK.iterdir()) if (d / "geo.json").exists()]
    r.add(OK, "项目", f"{len(slugs)} 个：{'、'.join(slugs)}")
    for s in slugs:
        cfg = G.read_json(G.WORK / s / "geo.json", {})
        qs = cfg.get("questions") or []
        if not qs:
            r.add(WARN, f"项目 {s} 问题库为空",
                  "采样与选题都依赖它",
                  fix=f"geo.py bootstrap --slug {s}（需引擎）；客户站会在检测时自动推导")
        _check_fact_sources(r, s, cfg)


def _check_fact_sources(r: Report, slug: str, cfg: dict):
    """每个目标市场都要有对应语言的事实源，否则那语言的资产是空的。

    英文资产不透传中文事实（翻错的品牌声明等于编造），所以 facts.en.md 缺失时
    llms.txt / SKILL.md / JSON-LD 会静默产出空壳——看起来生成成功了，实际没内容。
    """
    import generate as GEN

    for lang in GEN._langs(cfg.get("market", "cn")):
        src = GEN.FACTS_FILE[lang]
        p = G.WORK / slug / "content" / src
        name = "中文" if lang == "zh" else "英文"
        if not p.exists():
            r.add(WARN, f"项目 {slug} 缺{name}事实卡",
                  f"content/{src} 不存在，{name}资产会是空壳",
                  fix=f"照 references/content-patterns.md 第 1 节写 content/{src}")
        elif not GEN._confirmed(GEN.parse_facts(slug, lang).get("definition", "")):
            r.add(WARN, f"项目 {slug} 的{name}定义句未确认",
                  f"content/{src} 里「一句话定义」还是占位符",
                  fix="补齐后重新生成——未确认的事实不会写进任何资产")
        if lang == "en" and not (cfg.get("brand", {}).get("en") or {}).get("industry"):
            r.add(WARN, f"项目 {slug} 缺 brand.en",
                  "geo.json 里没有英文的行业/目标用户/口径说明，英文资产会省略这几行",
                  fix='在 geo.json 的 brand 下加 "en": {"industry": …, "target_users": …}')


def run() -> int:
    r = Report()
    _check_python(r)
    _check_deps(r)
    _check_writable(r)
    _check_online(r)
    _check_env_file(r)
    _check_engines(r)
    _check_port(r, 8787, "客户网站", "启动时换端口：geo.py online --port 8788")
    _check_port(r, 8765, "顾问看板", "启动时换端口：geo.py ui --port 8766")
    _check_projects(r)

    print(f"\n交付前置自检 · {G.ROOT}\n" + "─" * 68)
    for level, item, detail, fix in r.rows:
        print(f"[{MARK[level]}] {item}" + (f" — {detail}" if detail else ""))
        if fix and level != OK:
            print(f"           修法：{fix}")
    print("─" * 68)
    if r.failed:
        print(f"不可交付：{r.failed} 项阻塞、{r.warned} 项提示")
    elif r.warned:
        print(f"可交付，但有 {r.warned} 项提示——确认它们是有意为之再交付")
    else:
        print("全部通过，可以交付")
    return 1 if r.failed else 0
