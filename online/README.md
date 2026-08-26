# GEO 线上版 · 第一期

客户打开就能看懂三件事：**AI 有没有提到我、接下来先改哪几条、改完有没有变好。**

判据、抓站、采样、验收仍用 `geolook/`。这里只做客户呈现、账号和额度。
顾问工作台（`geo.py ui`）还在，不再是客户主路径。

## 启动

```
py -3.12 online/server.py --port 8787 --no-open
```

或：`py -3.12 geolook/scripts/geo.py online --port 8787`

演示账号：`demo@wagnab.com` / `wagnab`（项目 https://wagnab.com/）

## 主路径

登录 → 总览 → 该做什么 → 效果 → 报告。左侧外加设置。没有插件菜单，没有 Key 表单。

## 测试

```
py -3.12 -m pytest online/tests geolook/tests -q
```
