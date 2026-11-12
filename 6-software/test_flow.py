#!/usr/bin/env python3
"""全流程自测:自动启动服务器和模拟器,走完 下发→核对→开始→远程调速→暂停→恢复→滴空截停→结束。
用法: python test_flow.py     (全部通过时最后一行打印 ALL PASS)
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = "8091"
URL = f"http://127.0.0.1:{PORT}"
fails = []


def post(path, body):
    req = urllib.request.Request(URL + path, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def dev(i=0):
    s = json.loads(urllib.request.urlopen(URL + "/api/state", timeout=5).read())
    return next(d for d in s["devices"] if d["id"] == f"IW-{i + 1:03d}")


def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name, info)
    if not cond:
        fails.append(name)


def wait(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if pred():
                return True
        except (StopIteration, KeyError, TypeError, OSError):
            pass
        time.sleep(0.5)
    return False


for f in ("data.json", "audit.jsonl"):
    p = os.path.join(HERE, f)
    if os.path.exists(p):
        os.rename(p, p + ".bak")
env = dict(os.environ, PORT=PORT)
srv = subprocess.Popen([sys.executable, "server.py"], cwd=HERE, env=env, stdout=subprocess.DEVNULL)
time.sleep(1.5)
sim = subprocess.Popen([sys.executable, "simulator.py", URL, "2", "60"], cwd=HERE, stdout=subprocess.DEVNULL)
try:
    check("设备上线", wait(lambda: dev()["online"]))
    check("绑定床位", post("/api/device/bind", {"dev": "IW-001", "bed": "12"})[0] == 200)
    check("重复绑定被拒", post("/api/device/bind", {"dev": "IW-002", "bed": "12"})[0] == 409)
    task = {"bed": "12", "patient_name": "张三", "patient_id": "P3172", "drug": "0.9% 氯化钠 250 mL + 头孢呋辛 1.5 g",
            "volume_ml": 250, "rate_mlh": 120, "temp_c": 39, "bag_code": "BAG1", "by": "药师A"}
    c, r = post("/api/tasks", task)
    check("下发任务,头孢限温 37", c == 200 and r["task"]["temp_c"] == 37.0, r.get("task", {}).get("note"))
    c, r = post("/api/tasks", dict(task, bed="13", drug="胰岛素 50 U + 氯化钠", bag_code="B2"))
    check("胰岛素禁止加温", c == 200 and r["task"]["temp_c"] == 0)
    check("同床重复任务被拒", post("/api/tasks", task)[0] == 409)
    check("设备收到任务开始预热", wait(lambda: dev()["last"]["st"] == "READY"))
    check("未核对不能开始", post("/api/bedside/start", {"dev": "IW-001", "by": "N1"})[0] == 409)
    check("腕带不符被拒", post("/api/bedside/verify", {"dev": "IW-001", "patient_id": "P9", "bag_code": "BAG1"})[0] == 409)
    check("核对一致", post("/api/bedside/verify", {"dev": "IW-001", "patient_id": "P3172", "bag_code": "BAG1", "by": "N1"})[0] == 200)
    check("确认开始", post("/api/bedside/start", {"dev": "IW-001", "by": "N1"})[0] == 200)
    check("设备进入输液", wait(lambda: dev()["last"]["st"] == "RUN" and dev()["task"]["status"] == "running"))
    c, r = post("/api/cmd", {"dev": "IW-001", "kind": "rate", "value": 80, "src": "ward", "by": "李护士"})
    check("大屏调速只生成请求", c == 200 and r["direct"] is False and dev()["last"]["fs"] == 120)
    time.sleep(2.5)
    check("未确认前设备流速不变", dev()["last"]["fs"] == 120)
    check("床旁确认后执行", post("/api/request/answer", {"dev": "IW-001", "req": r["req"]["id"], "accept": True, "by": "N1"})[0] == 200
          and wait(lambda: dev()["last"]["fs"] == 80))
    c, r = post("/api/cmd", {"dev": "IW-001", "kind": "temp", "value": 40, "src": "bedside", "by": "N1"})
    check("床旁调温被限制在药品上限", c == 200 and r["value"] == 37.0)
    c, r = post("/api/cmd", {"dev": "IW-001", "kind": "pause", "src": "ward", "by": "李护士"})
    check("大屏暂停直接执行", c == 200 and r["direct"] and wait(lambda: dev()["last"]["st"] == "PAUSE"))
    c, r = post("/api/cmd", {"dev": "IW-001", "kind": "resume", "src": "ward", "by": "李护士"})
    time.sleep(2.5)
    check("大屏恢复只生成请求", r["direct"] is False and dev()["last"]["st"] == "PAUSE")
    check("床旁恢复", post("/api/cmd", {"dev": "IW-001", "kind": "resume", "src": "bedside", "by": "N1"})[0] == 200
          and wait(lambda: dev()["last"]["st"] == "RUN"))
    post("/api/cmd", {"dev": "IW-001", "kind": "rate", "value": 600, "src": "bedside", "by": "N1"})
    check("余量不足预警", wait(lambda: "LOWVOL" in dev()["last"]["al"], 120))
    check("滴空后截停并报警", wait(lambda: dev()["last"]["st"] == "DONE" and "EMPTY" in dev()["last"]["al"]
                           and dev()["last"]["clamp"] == 0, 120))
    check("任务标记完成", wait(lambda: dev()["task"] is None))
    check("结束后回到待机", post("/api/cmd", {"dev": "IW-001", "kind": "finish", "src": "bedside", "by": "N1"})[0] == 200
          and wait(lambda: dev()["last"]["st"] == "IDLE"))
    for p in ("/ward", "/pharmacy", "/bedside?dev=IW-001"):
        check("页面 " + p, urllib.request.urlopen(URL + p, timeout=5).status == 200)
    n = len(open(os.path.join(HERE, "audit.jsonl"), encoding="utf-8").readlines())
    check("操作留痕", n >= 12, f"{n} 条")
finally:
    sim.kill(); srv.kill()
    time.sleep(0.5)
    for f in ("data.json", "audit.jsonl"):
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
        if os.path.exists(p + ".bak"):
            os.rename(p + ".bak", p)
print("ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
