"""P0 高风险改动的实测验证：跨进程锁互斥、reap_orphans 不误杀、stop 收进程树。

单元测试用 mock 覆盖不到这三件事——它们只有真的起进程才能验。
用法：py -3.12 verify_p0.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "geolook" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import geolib as G  # noqa: E402
import jobs as J  # noqa: E402

OK, BAD = "  [PASS]", "  [FAIL]"
failures = []


def check(cond: bool, msg: str):
    print((OK if cond else BAD) + " " + msg)
    if not cond:
        failures.append(msg)


# ---------------------------------------------------------------- 1. 跨进程锁

LOCK_CHILD = r'''
import sys, time, json
sys.path.insert(0, r"{scripts}")
import geolib as G
G.WORK = __import__("pathlib").Path(r"{work}")
t0 = time.time()
with G.project_lock("locktest"):
    got = time.time()
    time.sleep(1.2)
    rel = time.time()
print(json.dumps({{"waited": got - t0, "got": got, "rel": rel}}))
'''


def test_lock_mutex():
    print("\n[1] 跨进程锁互斥（两个进程同时抢同一项目的锁）")
    with tempfile.TemporaryDirectory() as td:
        src = LOCK_CHILD.format(scripts=SCRIPTS, work=td)
        procs = [subprocess.Popen([sys.executable, "-c", src],
                                  stdout=subprocess.PIPE, text=True) for _ in range(2)]
        outs = [p.communicate()[0].strip() for p in procs]
        try:
            a, b = (json.loads(o.splitlines()[-1]) for o in outs)
        except Exception as e:  # noqa: BLE001
            check(False, f"子进程输出无法解析：{e} / {outs}")
            return
        first, second = sorted([a, b], key=lambda x: x["got"])
        overlap = first["rel"] - second["got"]
        check(overlap <= 0.05,
              f"持锁区间不重叠（重叠 {overlap:.3f}s，应 <= 0）")
        check(second["waited"] >= 1.0,
              f"后到的进程真的等了（等了 {second['waited']:.2f}s，应 >= 1.0）")


# ---------------------------------------------------------------- 2. reap 不误杀


def test_reap_does_not_kill():
    print("\n[2] reap_orphans 不误杀正在运行的任务  ← os.kill(pid,0) 那个 bug 的回归测试")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with tempfile.TemporaryDirectory() as td:
            orig = J.JOBS_DIR
            J.JOBS_DIR = Path(td) / ".jobs"
            J.JOBS_DIR.mkdir(parents=True)
            (J.JOBS_DIR / "livejob123456.json").write_text(json.dumps({
                "id": "livejob123456", "slug": "x", "action": "audit", "label": "体检",
                "status": "running", "started_at": "2026-08-23T00:00:00",
                "finished_at": None, "exit_code": None, "pid": child.pid,
            }), "utf-8")
            try:
                reaped = J.reap_orphans()
                time.sleep(0.4)
                check(child.poll() is None, "被探活的子进程仍然存活（没被 TerminateProcess 杀掉）")
                check(reaped == 0, f"没有误回收（reaped={reaped}，应为 0）")
                st = json.loads((J.JOBS_DIR / "livejob123456.json").read_text("utf-8"))
                check(st["status"] == "running", f"job 状态仍是 running（实际 {st['status']}）")
            finally:
                J.JOBS_DIR = orig

        # 反面：pid 已死的 job 应该被回收
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        with tempfile.TemporaryDirectory() as td:
            orig = J.JOBS_DIR
            J.JOBS_DIR = Path(td) / ".jobs"
            J.JOBS_DIR.mkdir(parents=True)
            (J.JOBS_DIR / "deadjob123456.json").write_text(json.dumps({
                "id": "deadjob123456", "slug": "x", "action": "audit", "label": "体检",
                "status": "running", "started_at": "2026-08-23T00:00:00",
                "finished_at": None, "exit_code": None, "pid": dead.pid,
            }), "utf-8")
            try:
                check(J.reap_orphans() == 1, "已死进程的 job 被正确回收")
                st = json.loads((J.JOBS_DIR / "deadjob123456.json").read_text("utf-8"))
                check(st["status"] == "interrupted", f"状态改为 interrupted（实际 {st['status']}）")
            finally:
                J.JOBS_DIR = orig
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


# ---------------------------------------------------------------- 3. stop 收树

TREE_PARENT = r'''
import subprocess, sys, time
kid = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(kid.pid, flush=True)
time.sleep(60)
'''


def test_kill_tree():
    print("\n[3] _kill_tree 收掉整棵进程树（父 + 它派生的子）")
    parent = subprocess.Popen([sys.executable, "-c", TREE_PARENT],
                              stdout=subprocess.PIPE, text=True,
                              **J._spawn_kwargs())
    try:
        kid_pid = int(parent.stdout.readline().strip())
        time.sleep(0.3)
        check(J._alive(parent.pid) and J._alive(kid_pid), "起好了：父子都活着")
        ok = J._kill_tree(parent.pid)
        check(ok, "_kill_tree 返回成功")
        time.sleep(1.0)
        check(not J._alive(parent.pid), "父进程已终止")
        check(not J._alive(kid_pid), "孙进程也被收掉（没留孤儿）")
    finally:
        for p in (parent,):
            if p.poll() is None:
                p.kill()
                p.wait()


if __name__ == "__main__":
    print(f"平台：{os.name}  ·  Python {sys.version.split()[0]}")
    print(f"锁后端：{'fcntl' if G.fcntl is not None else 'msvcrt'}")
    test_lock_mutex()
    test_reap_does_not_kill()
    test_kill_tree()
    print("\n" + ("全部通过" if not failures else f"{len(failures)} 项失败："))
    for f in failures:
        print("  - " + f)
    sys.exit(1 if failures else 0)
