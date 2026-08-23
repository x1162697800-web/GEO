"""确认看板实际发出的内容，排除「用户看的是缓存页」。"""

import re
import urllib.request

for port in (8766, 8767):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            h = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"{port}: 无响应（{type(e).__name__}）")
        continue

    def g(pat, default="—"):
        m = re.search(pat, h)
        return m.group(1) if m else default

    logo = re.search(r'letter-spacing:-\.01em">([^<]*)<span[^>]*>([^<]*)</span>', h)
    print(f"=== 端口 {port} ===")
    print(f"  title      : {g(r'<title>([^<]+)</title>')}")
    print(f"  html lang  : {g(r'<html lang=.([^\"\']+).')}")
    print(f"  侧栏 logo  : {(logo.group(1) + logo.group(2)) if logo else '未匹配'}")
    ulang = re.search(r"const ULANG\s*=\s*'([^']+)'", h)
    print(f"  ULANG      : {ulang.group(1) if ulang else '未匹配（可能还是旧版）'}")
    print(f"  有 setLang : {'是（不该有）' if 'setLang(' in h else '否'}")
    print(f"  有 GeoLook : {'是（不该有）' if re.search(r'Geo<span|GeoLook', h) else '否'}")
    print(f"  大小       : {len(h)/1024:.0f} KB")
