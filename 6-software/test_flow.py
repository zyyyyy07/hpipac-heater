#!/usr/bin/env python3
"""全流程自测:自己在 8091 端口起服务器和模拟器,数据放临时目录,用接口走完一次手术。
python test_flow.py     最后一行是 ALL PASS 才算通过;有失败时退出码非 0。
只检查服务器和模拟器的行为,不检查页面画出来的样子。
"""
import csv, io, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("TEST_PORT", "8091"))
BASE = "http://127.0.0.1:%d" % PORT
SPEED = "120"                      # 模拟器加速倍数:设备上的 1 分钟 = 这里的 0.5 秒
BY = "测试员"
EVIL = "<script>alert(1)</script>"
fails, count = [], 0
procs = []


def check(name, cond, detail=""):
    global count
    count += 1
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "   ← " + str(detail)), flush=True)
    if not cond:
        fails.append(name)
    return cond


def http(method, path, body=None):
    """返回 (状态码, 响应头, 正文字节)。4xx/5xx 不抛异常。"""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def get(path):
    code, _, raw = http("GET", path)
    return code, raw.decode("utf-8")


def post(path, body):
    code, _, raw = http("POST", path, body)
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, {}


def cmd(dev, kind, value=None, by=BY):
    b = {"dev": dev, "kind": kind}
    if value is not None:
        b["value"] = value
    if by is not None:
        b["by"] = by
    return post("/api/cmd", b)


def dev(did):
    code, raw = get("/api/state")
    for d in json.loads(raw)["devices"]:
        if d["id"] == did:
            return d
    return None


def last(did):
    d = dev(did)
    return d["last"] if d else {}


def wait(what, fn, timeout=30.0):
    """轮询到 fn() 为真。超时返回 False。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if fn():
                return True
        except (OSError, KeyError, TypeError, ValueError):
            pass
        time.sleep(0.1)
    print("      (等待超时: %s)" % what, flush=True)
    return False


def spawn(args, env, log):
    p = subprocess.Popen([sys.executable] + args, cwd=HERE, env=env, stdout=open(log, "wb"), stderr=subprocess.STDOUT)
    procs.append(p)
    return p


def stop(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    if p in procs:
        procs.remove(p)


def cjk(s):
    return bool(re.search(r"[一-鿿]", s or ""))


def main(tmp):
    env = dict(os.environ, PORT=str(PORT), HP_DATA_DIR=tmp, PYTHONIOENCODING="utf-8")
    srv = spawn(["server.py"], env, os.path.join(tmp, "server.log"))
    if not check("服务器启动", wait("服务器", lambda: get("/api/state")[0] == 200, 15)):
        return

    # ---- 页面和静态文件 ----
    for path, word in (("/", "手术控制台"), ("/console", "手术控制台"), ("/panel", "主机面板模拟"), ("/local?dev=HP-001", "腹腔温度"), ("/common.js", "ALARMS"), ("/cases", "手术记录")):
        code, txt = get(path)
        check("GET %s 返回 200 且内容对" % path, code == 200 and word in txt, code)
    check("不存在的地址返回 404", get("/nope")[0] == 404)
    check("开始时没有设备", json.loads(get("/api/state")[1])["devices"] == [])
    check("给不存在的设备发命令 → 404", cmd("HP-999", "preheat")[0] == 404)
    code, j = post("/api/device/telemetry", {"id": "<b>x</b>", "ph": "IDLE"})
    check("设备编号含特殊字符的遥测 → 400", code == 400)
    code, j = post("/api/device/telemetry", {"id": "HP-777", "ph": "<img>"})
    check("阶段名不合约定的遥测 → 400", code == 400 and dev("HP-777") is None)

    # ---- 模拟器上线 ----
    sim = spawn(["simulator.py", BASE, "2", SPEED], env, os.path.join(tmp, "sim.log"))
    check("两台模拟设备上线", wait("上线", lambda: dev("HP-001")["online"] and dev("HP-002")["online"], 15))
    L = last("HP-001")
    need = {"ph", "target", "exposeMin", "flowSet", "circInExpose", "t", "press", "flow", "duty", "phSec", "exposeLeft", "al", "muted"}
    check("遥测字段齐全", need <= set(L) and set(L["t"]) == {"syr1", "syr2", "line1", "line2", "lineOut", "humPlate", "humOut", "gasEnd", "ip1", "ip2"}, sorted(L))
    check("初始为待机,输出全关", L["ph"] == "IDLE" and not any(L["duty"].values()) and L["exposeLeft"] == -1, L)
    check("气腹没建立时压力接近 0,泵不转", L["press"] < 1.0 and L["flow"] == 0, L)

    # ---- 被拒绝的命令 ----
    code, j = cmd("HP-001", "preheat", by=None)
    check("没填操作人 → 400,中文提示", code == 400 and cjk(j.get("err")), (code, j))
    check("操作人只有空格 → 400", cmd("HP-001", "preheat", by="   ")[0] == 400)
    code, j = cmd("HP-001", "selfdestruct")
    check("不认识的命令 → 400,中文提示", code == 400 and cjk(j.get("err")), (code, j))
    code, j = cmd("HP-001", "target", 43.1)
    check("目标温度 43.1 → 400,中文提示", code == 400 and cjk(j.get("err")), (code, j))
    check("目标温度 36.9 → 400", cmd("HP-001", "target", 36.9)[0] == 400)
    check("目标温度不是数字 → 400", cmd("HP-001", "target", "abc")[0] == 400)
    check("目标温度缺参数 → 400", cmd("HP-001", "target")[0] == 400)
    check("流量 15.5 → 400", cmd("HP-001", "flow", 15.5)[0] == 400)
    check("流量 -1 → 400", cmd("HP-001", "flow", -1)[0] == 400)
    check("暴露时间 0 → 400", cmd("HP-001", "exposeMin", 0)[0] == 400)
    check("暴露时间 61 → 400", cmd("HP-001", "exposeMin", 61)[0] == 400)
    check("暴露时间 2.5 → 400", cmd("HP-001", "exposeMin", 2.5)[0] == 400)
    check("暴露阶段循环填字符串 → 400", cmd("HP-001", "circInExpose", "yes")[0] == 400)
    code, j = cmd("HP-001", "nebulize")
    check("待机时开始喷雾 → 409,中文提示", code == 409 and cjk(j.get("err")), (code, j))
    check("待机时开始暴露计时 → 409", cmd("HP-001", "expose")[0] == 409)
    check("待机时结束手术 → 409", cmd("HP-001", "finish")[0] == 409)
    code, _, _ = http("POST", "/api/cmd", None)
    check("空请求体 → 400", code == 400, code)
    check("被拒绝后设备仍在待机", last("HP-001")["ph"] == "IDLE")

    # ---- 开始记录(手术编号里故意放一段脚本) ----
    check("开始记录没填编号 → 400", post("/api/case/start", {"dev": "HP-001", "label": "", "by": BY})[0] == 400)
    check("开始记录没填操作人 → 400", post("/api/case/start", {"dev": "HP-001", "label": "T-1"})[0] == 400)
    code, j = post("/api/case/start", {"dev": "HP-001", "label": EVIL, "by": BY})
    case = (j.get("case") or {}).get("id", "")
    check("开始记录", code == 200 and case.startswith("HP-001-"), (code, j))
    check("同一台设备重复开始记录 → 409", post("/api/case/start", {"dev": "HP-001", "label": "T-2", "by": BY})[0] == 409)
    check("状态里带着当前记录", (dev("HP-001")["case"] or {}).get("id") == case)

    # ---- 设置 ----
    ok = cmd("HP-001", "target", 41.0)[0] == 200 and cmd("HP-001", "flow", 12)[0] == 200 and cmd("HP-001", "exposeMin", 2)[0] == 200
    check("改目标温度、流量、暴露时间被接受", ok)
    check("设备执行了新设置", wait("设置", lambda: (lambda x: x["target"] == 41.0 and x["flowSet"] == 12.0 and x["exposeMin"] == 2)(last("HP-001")), 5), last("HP-001"))
    cmd("HP-001", "circInExpose", True)
    check("暴露阶段循环可以打开", wait("circ", lambda: last("HP-001")["circInExpose"] is True, 5))
    cmd("HP-001", "circInExpose", False)
    check("暴露阶段循环可以关上", wait("circ", lambda: last("HP-001")["circInExpose"] is False, 5))

    # ---- 预热 → 自动就绪 ----
    check("开始预热被接受", cmd("HP-001", "preheat")[0] == 200)
    check("进入预热,四路加热在输出", wait("PREHEAT", lambda: (lambda x: x["ph"] == "PREHEAT" and all(x["duty"][k] > 0 for k in ("syr", "line", "hum", "tube")))(last("HP-001")), 5), last("HP-001"))
    check("压力到 8 mmHg 以后循环泵才转", wait("泵", lambda: (lambda x: x["duty"]["pump"] > 0 and x["press"] >= 7.5)(last("HP-001")), 10) and not any(float(r["duty_pump"]) > 0 and float(r["press"]) < 7.0 for r in csv.DictReader(io.StringIO(http("GET", "/api/case/log?dev=HP-001")[2].decode("utf-8-sig")))), last("HP-001"))
    check("预热中再点开始预热 → 409", cmd("HP-001", "preheat")[0] == 409)
    code, j = cmd("HP-001", "ready")
    check("四路没到温时手动确认就绪 → 409", code == 409 and cjk(j.get("err")), (code, j))
    check("预热后自动转入就绪", wait("READY", lambda: last("HP-001")["ph"] == "READY", 60), last("HP-001"))
    L = last("HP-001")
    t = L["t"]
    check("就绪时药液两路在目标 ±0.5 ℃ 内", all(abs(t[k] - 41.0) <= 0.6 for k in ("syr1", "syr2", "line1", "line2")), t)
    check("就绪时腹腔平均温度到目标减 1 ℃", (t["ip1"] + t["ip2"]) / 2 >= 39.9, t)
    check("任何加热面都没超过 43 ℃", max(t["syr1"], t["syr2"], t["line1"], t["line2"]) <= 43.0, t)
    check("就绪时压力在 12 mmHg 附近", 10.5 < L["press"] < 13.5, L["press"])
    check("就绪时不能直接开始暴露计时 → 409", cmd("HP-001", "expose")[0] == 409)

    # ---- 喷雾 → 暴露 → 自动排气 → 结束 ----
    cmd("HP-001", "nebulize")
    check("喷雾阶段:循环泵停,药液加热保持", wait("NEBULIZE", lambda: (lambda x: x["ph"] == "NEBULIZE" and x["duty"]["pump"] == 0 and x["duty"]["syr"] > 0 and x["flow"] < 1.0)(last("HP-001")), 5), last("HP-001"))
    cmd("HP-001", "expose")
    check("暴露阶段:药液加热关,气体加热保持,开始倒计时", wait("EXPOSE", lambda: (lambda x: x["ph"] == "EXPOSE" and x["duty"]["syr"] == 0 and x["duty"]["line"] == 0 and x["duty"]["hum"] > 0 and x["duty"]["tube"] > 0 and 0 < x["exposeLeft"] <= 120)(last("HP-001")), 5), last("HP-001"))
    check("计时到自动转入排气,报“暴露计时到”,输出全关", wait("EVAC", lambda: (lambda x: x["ph"] == "EVAC" and "EXPOSE_END" in x["al"] and not any(x["duty"].values()) and x["exposeLeft"] == -1)(last("HP-001")), 15), last("HP-001"))
    cmd("HP-001", "mute")
    check("消音", wait("mute", lambda: last("HP-001")["muted"] is True, 5))
    cmd("HP-001", "ack")
    check("确认后“暴露计时到”清除", wait("ack", lambda: "EXPOSE_END" not in last("HP-001")["al"], 5))
    cmd("HP-001", "finish")
    check("结束手术 → 结束阶段", wait("DONE", lambda: last("HP-001")["ph"] == "DONE", 5))
    cmd("HP-001", "finish")
    check("再确认 → 回到待机", wait("IDLE", lambda: last("HP-001")["ph"] == "IDLE", 5))

    # ---- 结束记录、CSV ----
    code, j = post("/api/case/end", {"dev": "HP-001", "by": BY})
    check("结束记录", code == 200 and j["case"]["end"] and j["case"]["rows"] > 20, (code, j))
    check("重复结束记录 → 409", post("/api/case/end", {"dev": "HP-001", "by": BY})[0] == 409)
    code, hdr, raw = http("GET", "/api/case/log?dev=HP-001&case=" + case)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    check("下载 CSV:200,类型和文件名正确", code == 200 and "text/csv" in hdr.get("Content-Type", "") and case + ".csv" in hdr.get("Content-Disposition", ""), dict(hdr))
    cols = {"time", "case", "label", "ph", "phSec", "exposeLeft", "target", "syr1", "syr2", "line1", "line2", "lineOut", "humPlate", "humOut", "gasEnd", "ip1", "ip2", "press", "flow", "duty_syr", "duty_line", "duty_hum", "duty_tube", "duty_pump", "alarms", "muted"}
    check("CSV 每次遥测一行,列齐全", len(rows) == j["case"]["rows"] and cols <= set(rows[0]), (len(rows), sorted(rows[0]) if rows else None))
    seen = [r["ph"] for r in rows]
    order = [p for i, p in enumerate(seen) if i == 0 or seen[i - 1] != p]
    check("CSV 里的阶段顺序完整", order == ["IDLE", "PREHEAT", "READY", "NEBULIZE", "EXPOSE", "EVAC", "DONE", "IDLE"], order)
    check("CSV 里记下了报警和数值", any("EXPOSE_END" in r["alarms"] for r in rows) and all(float(r["target"]) == 41.0 for r in rows if r["ph"] != "IDLE") and all(r["case"] == case and r["label"] == EVIL for r in rows))
    check("CSV 文件落在数据目录的 cases/ 下", os.path.exists(os.path.join(tmp, "cases", case + ".csv")))
    check("不带 case 参数时返回最近一次记录", http("GET", "/api/case/log?dev=HP-001")[2] == raw)
    check("别的设备取不到这次记录 → 404", get("/api/case/log?dev=HP-002&case=" + case)[0] == 404)
    check("乱写的记录编号 → 404", get("/api/case/log?dev=HP-001&case=../../data")[0] == 404)

    # ---- 转义 ----
    code, page = get("/cases")
    check("记录列表页把手术编号转义了", code == 200 and EVIL not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page)
    check("状态接口把编号当作 JSON 字符串原样带回", dev("HP-001")["lastCase"]["label"] == EVIL)
    pages = "".join(open(os.path.join(HERE, "static", f), encoding="utf-8").read() for f in ("console.html", "local.html", "panel.html"))
    check("页面脚本没有把人填的文字拼进 innerHTML", len(re.findall(r"innerHTML", pages)) == 1 and "svg.innerHTML = g" in pages)

    # ---- 曲线数据 ----
    code, raw = get("/api/history?dev=HP-001&sec=7200")
    h = json.loads(raw)
    p = h["pts"][-1] if h.get("pts") else {}
    check("曲线数据:有点、不超过 900 个、字段齐全", code == 200 and 10 < len(h["pts"]) <= 900 and {"ts", "ph", "target", "syr", "line", "gasEnd", "ipMean", "ip1", "ip2", "press", "flow"} <= set(p), (code, len(h.get("pts", [])), p))
    check("曲线数据按时间递增,并且看得到升温", all(a["ts"] <= b["ts"] for a, b in zip(h["pts"], h["pts"][1:])) and max(x["ipMean"] for x in h["pts"]) - h["pts"][0]["ipMean"] > 2)
    h2 = json.loads(get("/api/history?dev=HP-001&sec=2")[1])
    check("sec 参数起作用", 0 < len(h2["pts"]) < 60 and all(h2["now"] - x["ts"] <= 2.01 for x in h2["pts"]), len(h2["pts"]))
    check("曲线数据:不存在的设备 → 404,sec 乱写 → 400", get("/api/history?dev=NOPE")[0] == 404 and get("/api/history?dev=HP-001&sec=abc")[0] == 400)

    # ---- 第二台:手动确认就绪、中止、提前结束 ----
    cmd("HP-002", "preheat")
    wait("HP-002 预热", lambda: last("HP-002")["ph"] == "PREHEAT", 5)
    check("四路到温后可以手动确认就绪", wait("ready 被接受", lambda: cmd("HP-002", "ready")[0] == 200, 20))
    wait("HP-002 就绪", lambda: last("HP-002")["ph"] == "READY", 5)
    L = last("HP-002")
    check("手动确认时腹腔温度其实还没到", L["ph"] == "READY" and (L["t"]["ip1"] + L["t"]["ip2"]) / 2 < L["target"] - 1.0, L)
    time.sleep(1.5)   # 设备时间 3 分钟
    check("手动确认后不会因为腹腔温度掉回预热", last("HP-002")["ph"] == "READY")
    check("中止被接受", cmd("HP-002", "abort")[0] == 200)
    check("中止后进入排气,加热和泵全关", wait("abort", lambda: (lambda x: x["ph"] == "EVAC" and not any(x["duty"].values()))(last("HP-002")), 5), last("HP-002"))
    cmd("HP-002", "finish"); wait("DONE", lambda: last("HP-002")["ph"] == "DONE", 5)
    cmd("HP-002", "finish"); wait("IDLE", lambda: last("HP-002")["ph"] == "IDLE", 5)
    cmd("HP-002", "preheat"); wait("PREHEAT", lambda: last("HP-002")["ph"] == "PREHEAT", 5)
    wait("ready", lambda: cmd("HP-002", "ready")[0] == 200, 20); wait("READY", lambda: last("HP-002")["ph"] == "READY", 5)
    cmd("HP-002", "nebulize"); wait("NEBULIZE", lambda: last("HP-002")["ph"] == "NEBULIZE", 5)
    cmd("HP-002", "expose"); wait("EXPOSE", lambda: last("HP-002")["ph"] == "EXPOSE", 5)
    check("第二轮走到暴露阶段,剩余时间按默认 30 分钟算", (lambda x: x["ph"] == "EXPOSE" and 1500 < x["exposeLeft"] <= 1800)(last("HP-002")), last("HP-002"))
    cmd("HP-002", "evac")
    check("提前结束 → 排气,没有“暴露计时到”报警", wait("evac", lambda: (lambda x: x["ph"] == "EVAC" and "EXPOSE_END" not in x["al"])(last("HP-002")), 5), last("HP-002"))

    # ---- 故障注入:腹腔温度过高 ----
    sim3 = spawn(["simulator.py", BASE, "1", SPEED, "--first", "3", "--fault", "ip_high@240+240"], env, os.path.join(tmp, "sim3.log"))
    wait("HP-003 上线", lambda: dev("HP-003")["online"], 15)
    cmd("HP-003", "preheat")
    check("故障注入:报“腹腔温度过高”,四路和泵全关", wait("IP_HIGH", lambda: (lambda x: "IP_HIGH" in x["al"] and not any(x["duty"].values()))(last("HP-003")), 20), last("HP-003"))
    cmd("HP-003", "ack")
    time.sleep(0.5)
    L = last("HP-003")
    check("温度还高时确认不掉报警", "IP_HIGH" in L["al"] or max(L["t"]["ip1"], L["t"]["ip2"]) < 42.5, L)
    wait("温度回落", lambda: max(last("HP-003")["t"]["ip1"], last("HP-003")["t"]["ip2"]) < 42.4, 20)
    check("回落后没确认前报警保持,加热不恢复", (lambda x: "IP_HIGH" in x["al"] and not any(x["duty"].values()))(last("HP-003")), last("HP-003"))
    cmd("HP-003", "ack")
    check("回落并确认后报警清除,加热恢复", wait("ack", lambda: (lambda x: "IP_HIGH" not in x["al"] and x["duty"]["syr"] > 0)(last("HP-003")), 5), last("HP-003"))

    # ---- 操作日志 ----
    with open(os.path.join(tmp, "audit.jsonl"), encoding="utf-8") as f:
        log = [json.loads(x) for x in f]
    cmds = [r for r in log if r["event"] == "cmd"]
    check("操作日志每条命令都有操作人、时间、结果", len(cmds) > 30 and all(r.get("t") and "by" in r and r.get("result") for r in cmds), len(cmds))
    check("日志里有中止的排队和送达", any(r["kind"] == "abort" and r["by"] == BY and r["result"] == "已排队" for r in cmds) and any(r["kind"] == "abort" and r["result"] == "已送达设备" for r in cmds))
    check("被拒绝的命令也记了日志", any(r["result"].startswith("拒绝") and r.get("kind") == "selfdestruct" for r in cmds))
    check("日志里有开始和结束记录", any(r["event"] == "case_start" and r["case"] == case for r in log) and any(r["event"] == "case_end" and r["case"] == case for r in log))

    # ---- 离线 ----
    stop(sim); stop(sim3)
    check("模拟器停掉后 5 秒多判为离线", wait("离线", lambda: not dev("HP-001")["online"] and not dev("HP-003")["online"], 9))
    code, j = cmd("HP-001", "abort")
    check("离线时发命令 → 409,中文提示", code == 409 and cjk(j.get("err")), (code, j))
    check("离线后仍保留最后一次数据", last("HP-001").get("ph") == "IDLE")

    # ---- 重启服务器后数据还在 ----
    stop(srv)
    srv = spawn(["server.py"], env, os.path.join(tmp, "server2.log"))
    wait("服务器重启", lambda: get("/api/state")[0] == 200, 15)
    d = dev("HP-001")
    check("重启后设备和上一次记录还在", d is not None and not d["online"] and (d.get("lastCase") or {}).get("id") == case, d)
    check("重启后还能下载 CSV", http("GET", "/api/case/log?dev=HP-001&case=" + case)[0] == 200)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    tmp = tempfile.mkdtemp(prefix="hp-test-")
    t0 = time.time()
    try:
        main(tmp)
    except Exception as e:   # 测试脚本自己出错也算失败,并且要把子进程收掉
        import traceback
        traceback.print_exc()
        fails.append("测试脚本异常: %r" % e)
    finally:
        for p in list(procs):
            stop(p)
        if fails:
            for name in ("server.log", "sim.log", "sim3.log"):
                path = os.path.join(tmp, name)
                if os.path.exists(path):
                    print("---- %s 的最后几行 ----" % name)
                    print(open(path, encoding="utf-8", errors="replace").read()[-1500:])
        shutil.rmtree(tmp, ignore_errors=True)
    print("共 %d 项,用时 %.0f 秒" % (count, time.time() - t0))
    if fails:
        print("FAILED %d 项: %s" % (len(fails), ";".join(fails)))
        sys.exit(1)
    print("ALL PASS")
