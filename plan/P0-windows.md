# P0 · Windows 支持

**优先级**：最高（阻塞项）
**风险等级**：**高风险技术改造**（动文件锁 + 进程管理）— 见 `RULES.md` R6
**成本**：2 个模块约 60–80 行净改动 + 测试守卫 + 3 份 README
**依赖**：无
**前置阅读**：`RULES.md` R6、R8

---

## 1. 为什么这是第一优先

**这不是加功能，是把已经能用的东西解锁。**

`scripts/geolib.py:8` 的 `import fcntl` 让 geolook 在 Windows 上**一行代码都跑不了**——
`geolib` 是所有模块的公共依赖，导入即失败。

实测（2026-08-22）：在 `sys.modules` 里塞一个 no-op `fcntl` 替身后，
`crawl` / `audit` / `score_page` / `geolib` 全部正常工作，**87 个测试全过**。
说明核心代码本来就是可移植的，只差一个锁的抽象。

两个动因：

1. **在阻塞你本人开发**——本轮所有实测都得靠外部注入 stub 才能跑
2. **在砍掉一批目标用户**——国内代理商和中小品牌桌面以 Windows 为主，
   README 现在写「Windows via WSL」，这是在漏斗第 0 步就流失

> **本阶段与 Nile 无关。** 它来自在 Windows 上实跑 geolook 撞到的缺陷，
> 不是竞品分析的产物。即使 Nile 明天消失，第 2.2 节那个会杀掉正在运行任务的
> bug 依然存在且依然紧急。来源归属见 `README.md` 第 2.4 节。

---

## 2. 改动面（已逐一定位验证）

### 2.1 `scripts/geolib.py` — 文件锁

**现状**：第 8 行 `import fcntl`；`project_lock()` 用 `fcntl.flock(fd, LOCK_EX/LOCK_UN)`，
锁文件以 `"w"` 模式打开。

**改法**：条件导入 + 两个平台辅助函数。

- POSIX：`fcntl.flock`，语义不变
- Windows：`msvcrt.locking` 字节区间锁

三个必须注意的细节：

1. **锁文件开法从 `"w"` 改 `"a+"`**。Windows 上另一进程持锁时截断文件会失败，
   而锁文件本来就不需要写内容。`"a+"` 创建但不截断，两平台都安全。
2. **`msvcrt` 没有无限阻塞模式**。`LK_LOCK` 只重试 10 次（约 10 秒）就抛 `OSError`，
   所以要用 `LK_NBLCK` 自己轮询。要与 `flock` 语义对齐——**不设超时**
   （进程退出时内核释放锁，崩溃不会留死锁），但等待超过约 10 秒时打一条
   `info()` 告诉用户在等谁，避免无声挂死。
3. **锁定区间要跨进程一致**。`msvcrt.locking` 从**当前文件位置**开始锁 N 字节，
   所以加锁前显式 `seek(0)`，固定锁第 0 字节（允许锁到 EOF 之外）。

### 2.2 `scripts/jobs.py` — 进程管理（三处）

| 行 | 现状 | Windows 问题 | 改法 |
|---|---|---|---|
| ~156 | `Popen(..., start_new_session=True)` | POSIX `setsid` 语义，Windows 静默忽略 | `creationflags=CREATE_NEW_PROCESS_GROUP` |
| ~192, ~202 | `os.killpg(os.getpgid(pid), SIGTERM)` | 两个函数在 Windows 上都不存在 | `taskkill /F /T /PID` 收进程树 |
| ~230 | `os.kill(pid, 0)` | **会杀掉进程** ⚠️ | `OpenProcess` + `GetExitCodeProcess` |

#### ⚠️ 第 230 行是会造成实际损坏的那处

`os.kill(pid, 0)` 在 POSIX 是探活惯用法（信号 0 不投递，只做权限和存在性检查）。
但 Python 文档对 Windows 明确写着：只有 `CTRL_C_EVENT` / `CTRL_BREAK_EVENT`
按信号处理，**其他任何值都会调用 `TerminateProcess` 无条件杀掉目标进程**。

所以 `reap_orphans()`（启动时回收孤儿 job）在 Windows 上会把**正在运行的任务全杀掉**，
然后因为进程真的死了而判定「不是孤儿」——症状表现为「任务莫名中断」，极难排查。

正确做法：`kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION=0x1000, False, pid)`，
拿到句柄后 `GetExitCodeProcess` 判是否为 `STILL_ACTIVE`(259)，最后 `CloseHandle`。
查不到状态时保守当作存活——宁可漏回收一个孤儿，不可误杀一个在跑的任务。

用 `ctypes` 即可，不引入依赖（符合 `RULES.md` R7）。

#### 为什么用进程组/进程树而不是只 kill 父进程

`jobs.py` 起的是 `python geo.py <action>`，管线里的命令会再派生子进程。
只杀父进程会留下孤儿继续写 `work/<slug>/`，而并发保护已经放开——
两个进程同时写一份 `audit.json`，这正是 `project_lock` 要防的事。
所以 Windows 侧必须用 `taskkill /T`（递归整棵树），不能用 `proc.terminate()`。

### 2.3 `tests/test_model_config.py:112` — 权限断言

```python
self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
```

Windows 的 `os.chmod` 只能表达只读位，`0o600` 落地会变成 `0o666`。
加平台守卫跳过或改断言（Windows 上只验证文件存在且内容正确）。

> 注：本轮 87 测试全过说明这个断言当时没被触发到（可能路径未命中）。
> 修 Windows 支持时要主动确认它在 Windows 上的真实行为，不能假设它会继续过。

### 2.4 `scripts/dashboard.py:220` — 安全声明与实现不一致

```python
path.chmod(0o600)  # 密钥文件不给同机其他用户读
```

在 Windows 上这行不报错，但**基本是空操作**。
按 `RULES.md` R8，必须在文档里写明：**Windows 上「密钥文件不给同机其他用户读」
这条安全保证不成立**，需要用户自己用 NTFS ACL 处理，或建议 Windows 用户
把 `.env` 放在受限目录。

不要偷偷放过——这正是 Nile 那种「声明与实现不一致」的反面教材。

### 2.5 三份 README

| 文件 | 位置 | 现状 |
|---|---|---|
| `README.md` | 第 11 行徽章 / 第 86 行 | `platform-macOS \| Linux` / "macOS or Linux (Windows via WSL — the code uses `fcntl` file locks)" |
| `README.zh-CN.md` | 第 11 行 / 第 110 行 | 同上 / 「macOS 或 Linux（Windows 请用 WSL；代码用了 `fcntl` 文件锁）」 |
| `README.ja.md` | 第 11 行 / 第 84 行 | 同上 / 同义 |

三份都要改徽章和依赖行，并补一段 Windows 说明：哪些能用、
哪些是 POSIX 专属（见第 3 节）、`.env` 权限的差异（2.4）。

---

## 3. 明确不做（保持 POSIX 专属并写进文档）

| 文件 | 为什么不移植 |
|---|---|
| `scripts/service.sh` | macOS launchd 常驻服务，便利功能，不阻塞主流程。Windows 用户可用计划任务自行处理 |
| `extension/sandbox.sh` | bash 启动一次性干净浏览器沙箱。**注意这条有实质影响**——Windows 用户拿不到 A 级采样环境的一键方案，只能手动开无痕窗口。文档要讲清楚 |
| `scripts/generate.py:438` | 那段 `#!/bin/sh` 是**生成给客户服务器**跑 access.log 统计的产物，不是 geolook 自己的运行时，与本地平台无关 |

`sandbox.sh` 这条值得单独记一笔：按 `references/method.md` 第 4 节的采样纪律，
`sandbox` / `incognito` 是 A 级证据，`personal` 自动降级 D 级。Windows 用户少了
一键沙箱，会更容易落到 `personal` 模式。这是 P0 之后可以补的（Windows 批处理
或 PowerShell 版 sandbox），但不在 P0 范围。

---

## 4. 验收标准

按 `RULES.md` R6 的高风险纪律，**两个平台都要实测**，不能只验一边。

### 4.1 Windows

- [ ] `py -3.12 -c "import geolib"` 成功（不需要任何外部 stub）
- [ ] `python scripts/geo.py --help` 正常
- [ ] `python scripts/geo.py crawl --slug <测试项目>` 跑通
- [ ] `python scripts/geo.py audit --slug <测试项目>` 跑通，`audit.json` 正常落盘
- [ ] `python scripts/geo.py ui` 起得来，浏览器能打开看板
- [ ] 在看板里触发一个 job（如「抓取站点」），日志实时刷新
- [ ] **触发一个 slow job 后点停止，确认整棵进程树都收掉**（查任务管理器无残留 python）
- [ ] **起一个 job，不等它结束就重启 dashboard，确认 `reap_orphans` 没有杀掉它**
      ← 这条是 2.2 那个 bug 的直接回归测试，必须验
- [ ] 并发保护有效：同一项目同时触发两个 job，第二个被挡
- [ ] 全量测试通过

### 4.2 macOS / Linux（回归）

- [ ] 全量测试通过（当前基线 87 passed）
- [ ] `project_lock` 跨进程互斥仍然有效（两个进程同时写同一项目，验证串行化）
- [ ] `stop()` 仍能收掉整个进程组
- [ ] `reap_orphans()` 行为不变

### 4.3 文档

- [ ] 3 份 README 的徽章与依赖行已更新
- [ ] Windows 限制已写明：`service.sh` / `sandbox.sh` 不可用、`.env` 权限保证不成立
- [ ] 没有任何「支持 Windows」的表述超出实际验证范围（R8）

---

## 5. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 锁实现有 bug 导致并发写坏 `work/` 数据 | 改动前 `git commit` 打基线；4.1/4.2 的互斥测试必须过；`work/` 本身有备份纪律（`.geo.bak`） |
| Windows 轮询锁在高并发下饥饿 | 单机工具，并发度极低（同项目只允许一个 job）；等待超 10 秒会打日志暴露问题 |
| `taskkill` 不可用或权限不足 | 失败时回落 `proc.terminate()`，并记录日志而非静默 |
| POSIX 侧被改坏 | 4.2 回归清单；`fcntl` 分支代码路径不变，只是被包进条件分支 |

**回滚**：改动集中在 2 个文件，`git revert` 即可。改前必须有干净的 commit 基线。

---

## 6. 建议实施顺序

`jobs.py` 那三处**必须一起改**——只改 `killpg` 不改 `os.kill(pid, 0)`，
会得到「任务能停但会被随机杀掉」的更差状态。

1. `git commit` 打基线
2. `geolib.py` 锁抽象 + 在 Windows 上跑全量测试（此时 `jobs.py` 还没改，
   但测试不覆盖进程管理，应该能过）
3. `jobs.py` 三处一起改
4. 测试守卫（2.3）
5. Windows 侧走完 4.1 清单
6. POSIX 侧走完 4.2 清单
7. 文档（2.5 + 4.3）
