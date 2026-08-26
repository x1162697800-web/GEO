# GEO 线上版 · 交付

客户打开就能看懂三件事：**AI 有没有提到我、接下来先改哪几条、改完有没有变好。**

判据、抓站、采样、验收仍用 `geolook/`。这里只做客户呈现、账号和额度。
密钥只在 `geolook/.env`，客户网站和插件都没有 Key 表单。

顾问工作台（`geo.py ui`，8765）还在，给内部用，不是客户主路径。

## 交付步骤

```
pip install requests beautifulsoup4 lxml
copy geolook\.env.example geolook\.env   # 部署的人填引擎 key，客户不填
py -3.12 geolook\scripts\geo.py doctor   # 退出码 0 才交；提示项要心里有数
py -3.12 geolook\scripts\geo.py online --port 8787
```

Windows 也可：`online\run.ps1`

演示账号（仅本机）：`demo@wagnab.com` / `wagnab`（项目 https://wagnab.com/）

公网绑定 `0.0.0.0` 时**不会**创建演示账号。前面加 HTTPS 反代，并设 `GROUNDED_ONLINE_HTTPS=1` 给登录 Cookie 加 Secure。关掉演示：`GROUNDED_DEMO=0`。

## 主路径

登录 → 总览 → 该做什么 → 效果 → 报告。左侧外加设置。没有插件菜单，没有 Key 表单。

无 API 的引擎用采样插件，地址写成 `http://127.0.0.1:8787`。

## 远程

默认只绑 `127.0.0.1`。SSH 隧道：

```
ssh -N -L 8787:127.0.0.1:8787 user@your-server
```

然后本地打开 http://127.0.0.1:8787

## 测试

```
py -3.12 -m pytest online/tests geolook/tests -q
```
