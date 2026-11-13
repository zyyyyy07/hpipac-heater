#!/usr/bin/env python3
"""全流程自测:自己在 8091 端口起盒内服务程序和主控模拟器,数据放临时目录,用触摸屏会调的接口走完一次手术。
python test_flow.py     最后一行是 ALL PASS 才算通过;有失败时退出码非 0。
只检查服务器和模拟器的行为,不检查页面画出来的样子。
"""
import csv, io, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("TEST_PORT", "8091"))
BASE = "http://127.0.0.1:%d" % PORT
SPEED = "120"                      # 模拟器加速倍数:设备上的 1 分钟 = 这里的 0.5 秒
TOUCH = "触摸屏"          # 命令不带来源时,日志里记成这个
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


def cmd(dev, kind, value=None, by=None):
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


def go_ready(did):
    """预热中反复发“手动确认就绪”直到设备真的进入就绪。服务器按上一次遥测预判,设备自己还会再判一次,临界时可能要发第二次。"""
    def step():
        ph = last(did)["ph"]
        if ph == "PREHEAT":
            cmd(did, "ready")
        return ph == "READY"
    return wait(did + " 就绪", step, 25)


def cjk(s):
    return bool(re.search(r"[一-鿿]", s or ""))


def main(tmp):
    env = dict(os.environ, PORT=str(PORT), HP_DATA_DIR=tmp, PYTHONIOENCODING="utf-8")
    srv = spawn(["server.py"], env, os.path.join(tmp, "server.log"))
    if not check("服务器启动", wait("服务器", lambda: get("/api/state")[0] == 200, 15)):
        return

    # ---- 页面和静态文件 ----
    for path, word in (("/", "本机界面"), ("/local?dev=HP-001", "本机界面"), ("/panel", "主机面板模拟"), ("/common.js", "ALARMS")):
        code, txt = get(path)
        check("GET %s 返回 200 且内容对" % path, code == 200 and word in txt, code)
    check("/ 和 /local 是同一个触摸屏页面", get("/")[1] == get("/local")[1])
    check("不存在的地址返回 404", get("/nope")[0] == 404)
    check("远程页面和手工记录接口都已经去掉(/console、/cases、/api/case/start、/api/case/end)",
          get("/console")[0] == 404 and get("/cases")[0] == 404 and post("/api/case/start", {"dev": "HP-001"})[0] == 404 and post("/api/case/end", {"dev": "HP-001"})[0] == 404)
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
    need = {"ph", "target", "exposeMin", "flowSet", "nebFlow", "circInExpose", "t", "press", "nozP", "flow", "duty", "phSec", "exposeLeft", "al", "muted"}
    check("遥测字段齐全", need <= set(L) and set(L["t"]) == {"syr1", "syr2", "noz1", "noz2", "humPlate", "humOut", "gasEnd", "ip1", "ip2"} and set(L["duty"]) == {"syr", "noz", "hum", "tube", "pump"}, L)
    check("初始为待机,输出全关", L["ph"] == "IDLE" and not any(L["duty"].values()) and L["exposeLeft"] == -1, L)
    check("气腹没建立时压力接近 0,泵不转,雾化气压为 0", L["press"] < 1.0 and L["flow"] == 0 and L["nozP"] == 0, L)
    check("雾化气流量默认 12 L/min", L["nebFlow"] == 12.0, L)

    # ---- 被拒绝的命令 ----
    code, j = cmd("HP-001", "selfdestruct")
    check("不认识的命令 → 400,中文提示", code == 400 and cjk(j.get("err")), (code, j))
    code, j = cmd("HP-001", "target", 43.1)
    check("目标温度 43.1 → 400,中文提示", code == 400 and cjk(j.get("err")), (code, j))
    check("目标温度 36.9 → 400", cmd("HP-001", "target", 36.9)[0] == 400)
    check("目标温度不是数字 → 400", cmd("HP-001", "target", "abc")[0] == 400)
    check("目标温度缺参数 → 400", cmd("HP-001", "target")[0] == 400)
    check("流量 15.5 → 400", cmd("HP-001", "flow", 15.5)[0] == 400)
    check("流量 -1 → 400", cmd("HP-001", "flow", -1)[0] == 400)
    code, j = cmd("HP-001", "nebFlow", 4.9)
    check("雾化气流量 4.9 → 400,中文提示", code == 400 and cjk(j.get("err")), (code, j))
    check("雾化气流量 15.1 → 400", cmd("HP-001", "nebFlow", 15.1)[0] == 400)
    check("雾化气流量填 true → 400", cmd("HP-001", "nebFlow", True)[0] == 400)
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

    check("待机时不开记录", dev("HP-001")["case"] is None and dev("HP-001")["lastCase"] is None)

    # ---- 设置 ----
    code, j = cmd("HP-001", "target", 41.0)
    check("命令不需要带来源,也会被接受", code == 200, (code, j))
    ok = code == 200 and cmd("HP-001", "flow", 9)[0] == 200 and cmd("HP-001", "nebFlow", 13)[0] == 200 and cmd("HP-001", "exposeMin", 2)[0] == 200
    check("改目标温度、循环流量、雾化气流量、暴露时间被接受", ok)
    check("设备执行了新设置", wait("设置", lambda: (lambda x: x["target"] == 41.0 and x["flowSet"] == 9.0 and x["nebFlow"] == 13.0 and x["exposeMin"] == 2)(last("HP-001")), 5), last("HP-001"))
    cmd("HP-001", "circInExpose", True)
    check("暴露阶段循环可以打开", wait("circ", lambda: last("HP-001")["circInExpose"] is True, 5))
    cmd("HP-001", "circInExpose", False)
    check("暴露阶段循环可以关上", wait("circ", lambda: last("HP-001")["circInExpose"] is False, 5))

    # ---- 预热 → 自动就绪 ----
    check("开始预热被接受", cmd("HP-001", "preheat")[0] == 200)
    check("进入预热后自动开始记录", wait("自动记录", lambda: (dev("HP-001")["case"] or {}).get("id", "").startswith("HP-001-"), 5), dev("HP-001"))
    case = dev("HP-001")["case"]["id"]
    check("进入预热,四路加热在输出", wait("PREHEAT", lambda: (lambda x: x["ph"] == "PREHEAT" and all(x["duty"][k] > 0 for k in ("syr", "noz", "hum", "tube")))(last("HP-001")), 5), last("HP-001"))
    check("压力到 8 mmHg 以后循环泵才转", wait("泵", lambda: (lambda x: x["duty"]["pump"] > 0 and x["press"] >= 7.5)(last("HP-001")), 10) and not any(float(r["duty_pump"]) > 0 and float(r["press"]) < 7.0 for r in csv.DictReader(io.StringIO(http("GET", "/api/case/log?dev=HP-001")[2].decode("utf-8-sig")))), last("HP-001"))
    check("预热中再点开始预热 → 409", cmd("HP-001", "preheat")[0] == 409)
    code, j = cmd("HP-001", "ready")
    check("四路没到温时手动确认就绪 → 409", code == 409 and cjk(j.get("err")), (code, j))
    check("预热后自动转入就绪", wait("READY", lambda: last("HP-001")["ph"] == "READY", 60), last("HP-001"))
    L = last("HP-001")
    t = L["t"]
    check("就绪时注射筒和喷头歧管在目标 ±0.5 ℃ 内", all(abs(t[k] - 41.0) <= 0.6 for k in ("syr1", "syr2", "noz1", "noz2")), t)
    check("就绪时腹腔平均温度到目标减 1 ℃", (t["ip1"] + t["ip2"]) / 2 >= 39.9, t)
    check("任何加热面都没超过 43 ℃", max(t["syr1"], t["syr2"], t["noz1"], t["noz2"]) <= 43.0, t)
    check("就绪时压力在 12 mmHg 附近,泵按循环流量 9 L/min 转", 10.5 < L["press"] < 13.5 and 8.5 < L["flow"] < 9.5 and 25 < L["nozP"] < 48, L)
    check("就绪时不能直接开始暴露计时 → 409", cmd("HP-001", "expose")[0] == 409)

    # ---- 喷雾 → 暴露 → 自动排气 → 结束 ----
    cmd("HP-001", "nebulize")
    check("喷雾阶段:循环泵按雾化气流量 13 L/min 转,四路加热保持", wait("NEBULIZE", lambda: (lambda x: x["ph"] == "NEBULIZE" and x["duty"]["pump"] > 0 and 12.5 < x["flow"] < 13.5 and all(x["duty"][k] > 0 for k in ("syr", "noz", "hum", "tube")))(last("HP-001")), 5), last("HP-001"))
    check("喷雾阶段雾化气压在 60–90 kPa,没有雾化气压报警", (lambda x: 60 < x["nozP"] < 90 and "NOZ_LOW" not in x["al"] and "NOZ_BLOCK" not in x["al"])(last("HP-001")), last("HP-001"))
    ipn = (lambda t: (t["ip1"] + t["ip2"]) / 2)(last("HP-001")["t"])
    time.sleep(1.0)
    cmd("HP-001", "expose")
    check("暴露阶段:注射筒和喷头歧管加热关,气体加热保持,泵默认停,开始倒计时", wait("EXPOSE", lambda: (lambda x: x["ph"] == "EXPOSE" and x["duty"]["syr"] == 0 and x["duty"]["noz"] == 0 and x["duty"]["pump"] == 0 and x["nozP"] < 5 and x["duty"]["hum"] > 0 and x["duty"]["tube"] > 0 and 0 < x["exposeLeft"] <= 120)(last("HP-001")), 5), last("HP-001"))
    check("计时到自动转入排气,报“暴露计时到”,输出全关", wait("EVAC", lambda: (lambda x: x["ph"] == "EVAC" and "EXPOSE_END" in x["al"] and not any(x["duty"].values()) and x["exposeLeft"] == -1)(last("HP-001")), 15), last("HP-001"))
    cmd("HP-001", "mute")
    check("消音", wait("mute", lambda: last("HP-001")["muted"] is True, 5))
    cmd("HP-001", "ack")
    check("确认后“暴露计时到”清除", wait("ack", lambda: "EXPOSE_END" not in last("HP-001")["al"], 5))
    cmd("HP-001", "finish")
    check("结束手术 → 结束阶段", wait("DONE", lambda: last("HP-001")["ph"] == "DONE", 5))
    check("结束阶段记录还开着,行数在涨(触摸屏据此显示“本次记录已保存”)", (lambda d: d["case"] and d["case"]["id"] == case and d["case"]["rows"] > 20)(dev("HP-001")), dev("HP-001")["case"])
    cmd("HP-001", "finish")
    check("再确认 → 回到待机", wait("IDLE", lambda: last("HP-001")["ph"] == "IDLE", 5))

    # ---- 自动结束记录、CSV ----
    d1 = dev("HP-001")
    check("回到待机后记录自动关上", d1["case"] is None and d1["lastCase"]["id"] == case and d1["lastCase"]["end"] and d1["lastCase"]["rows"] > 20, d1)
    j = {"case": d1["lastCase"]}
    code, hdr, raw = http("GET", "/api/case/log?dev=HP-001&case=" + case)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    check("下载 CSV:200,类型和文件名正确", code == 200 and "text/csv" in hdr.get("Content-Type", "") and case + ".csv" in hdr.get("Content-Disposition", ""), dict(hdr))
    cols = {"time", "case", "ph", "phSec", "exposeLeft", "target", "flowSet", "nebFlow", "syr1", "syr2", "noz1", "noz2", "humPlate", "humOut", "gasEnd", "ip1", "ip2", "press", "nozP", "flow", "duty_syr", "duty_noz", "duty_hum", "duty_tube", "duty_pump", "alarms", "muted"}
    check("CSV 每次遥测一行,列齐全", len(rows) == j["case"]["rows"] and cols <= set(rows[0]), (len(rows), sorted(rows[0]) if rows else None))
    seen = [r["ph"] for r in rows]
    order = [p for i, p in enumerate(seen) if i == 0 or seen[i - 1] != p]
    check("CSV 从预热开始,到回待机的那一行结束", order == ["PREHEAT", "READY", "NEBULIZE", "EXPOSE", "EVAC", "DONE", "IDLE"] and seen.count("IDLE") == 1 and seen[-1] == "IDLE", order)
    check("CSV 里记下了报警和数值", any("EXPOSE_END" in r["alarms"] for r in rows) and all(float(r["target"]) == 41.0 for r in rows) and all(r["case"] == case for r in rows) and "label" not in rows[0])
    neb = [r for r in rows if r["ph"] == "NEBULIZE"]
    check("CSV 里喷雾阶段泵一直在转,旧字段已经没有", len(neb) > 3 and all(float(r["duty_pump"]) > 0 for r in neb) and not any(c.startswith(("li", "duty_li")) for c in rows[0]), len(neb))
    check("喷雾阶段腹腔温度没有回落(循环没有停)", float(neb[-1]["ip1"]) + float(neb[-1]["ip2"]) >= float(neb[0]["ip1"]) + float(neb[0]["ip2"]) - 0.15, (neb[0]["ip1"], neb[-1]["ip1"]))
    check("CSV 文件落在数据目录的 cases/ 下", os.path.exists(os.path.join(tmp, "cases", case + ".csv")))
    check("不带 case 参数时返回最近一次记录", http("GET", "/api/case/log?dev=HP-001")[2] == raw)
    check("别的设备取不到这次记录 → 404", get("/api/case/log?dev=HP-002&case=" + case)[0] == 404)
    check("乱写的记录编号 → 404", get("/api/case/log?dev=HP-001&case=../../data")[0] == 404)

    # ---- 服务程序重启后第一次收到正在运行的设备:马上接着记 ----
    post("/api/device/telemetry", {"id": "HP-009", "ph": "EXPOSE", "target": 42.0, "exposeLeft": 900})
    d9 = dev("HP-009")
    check("第一次收到就在运行的设备,也自动开记录", d9["case"] is not None and d9["case"]["rows"] == 1, d9)
    post("/api/device/telemetry", {"id": "HP-009", "ph": "IDLE"})
    d9 = dev("HP-009")
    check("它回到待机时记录关上,共 2 行", d9["case"] is None and d9["lastCase"]["rows"] == 2, d9)

    # ---- 页面 ----
    local = open(os.path.join(HERE, "static", "local.html"), encoding="utf-8").read()
    pages = local + open(os.path.join(HERE, "static", "panel.html"), encoding="utf-8").read()
    check("页面脚本只在画曲线时用 innerHTML", len(re.findall(r"innerHTML", pages)) == 1 and "svg.innerHTML = g" in pages)
    check("触摸屏页面有全部操作:阶段按钮、中止再确认、确认报警、消音、五项设置、曲线页",
          all(w in local for w in ('id="bMain"', 'id="bAbort"', "确认中止", 'id="bAck"', 'id="bMute"', 'data-tab="pChart"', 'data-tab="pSet"'))
          and all('data-k="%s"' % k in local for k in ("target", "flow", "nebFlow", "exposeMin", "circInExpose")))
    common = open(os.path.join(HERE, "static", "common.js"), encoding="utf-8").read()
    check("触摸屏页面有“主控无响应”整屏状态;结束阶段写“本次记录已保存”", "主控无响应" in local and "本次记录已保存" in common and "c.id + '.csv" in local)
    check("各阶段按钮文字按 touchscreen-ui.md:排气完成、回到待机、喷雾结束、不等腹腔直接就绪",
          all(w in common for w in ("label: '排气完成'", "label: '回到待机'", "label: '喷雾结束'", "label: '不等腹腔,直接就绪'", "label: '提前结束暴露'")))
    check("页面不再指向已经去掉的页面", "/console" not in pages and "/cases" not in pages)

    # ---- 曲线数据 ----
    code, raw = get("/api/history?dev=HP-001&sec=7200")
    h = json.loads(raw)
    p = h["pts"][-1] if h.get("pts") else {}
    check("曲线数据:有点、不超过 900 个、字段齐全", code == 200 and 10 < len(h["pts"]) <= 900 and {"ts", "ph", "target", "syr", "noz", "gasEnd", "ipMean", "ip1", "ip2", "press", "nozP", "flow"} <= set(p) and not any(k.startswith("li") for k in p), (code, len(h.get("pts", [])), p))
    check("曲线数据按时间递增,并且看得到升温", all(a["ts"] <= b["ts"] for a, b in zip(h["pts"], h["pts"][1:])) and max(x["ipMean"] for x in h["pts"]) - h["pts"][0]["ipMean"] > 2)
    h2 = json.loads(get("/api/history?dev=HP-001&sec=2")[1])
    check("sec 参数起作用", 0 < len(h2["pts"]) < 60 and all(h2["now"] - x["ts"] <= 2.01 for x in h2["pts"]), len(h2["pts"]))
    check("曲线数据:不存在的设备 → 404,sec 乱写 → 400", get("/api/history?dev=NOPE")[0] == 404 and get("/api/history?dev=HP-001&sec=abc")[0] == 400)

    # ---- 第二台:手动确认就绪、中止、提前结束 ----
    cmd("HP-002", "preheat")
    wait("HP-002 预热", lambda: last("HP-002")["ph"] == "PREHEAT", 5)
    check("四路到温后可以手动确认就绪", go_ready("HP-002"))
    L = last("HP-002")
    check("手动确认时腹腔温度其实还没到", L["ph"] == "READY" and (L["t"]["ip1"] + L["t"]["ip2"]) / 2 < L["target"] - 1.0, L)
    time.sleep(1.5)   # 设备时间 3 分钟
    check("手动确认后不会因为腹腔温度掉回预热", last("HP-002")["ph"] == "READY")
    case2 = (dev("HP-002")["case"] or {}).get("id")
    check("中止被接受", cmd("HP-002", "abort")[0] == 200)
    check("中止后进入排气,加热和泵全关", wait("abort", lambda: (lambda x: x["ph"] == "EVAC" and not any(x["duty"].values()))(last("HP-002")), 5), last("HP-002"))
    cmd("HP-002", "finish"); wait("DONE", lambda: last("HP-002")["ph"] == "DONE", 5)
    cmd("HP-002", "finish"); wait("IDLE", lambda: last("HP-002")["ph"] == "IDLE", 5)
    check("中止后走完结束,第一台的第一次记录关上", (dev("HP-002")["lastCase"] or {}).get("id") == case2 and dev("HP-002")["case"] is None, dev("HP-002"))
    cmd("HP-002", "preheat"); wait("PREHEAT", lambda: last("HP-002")["ph"] == "PREHEAT", 5)
    case3 = (dev("HP-002")["case"] or {}).get("id")
    check("再次预热开了一份新的记录", case3 and case3 != case2, (case2, case3))
    go_ready("HP-002")
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

    # ---- 故障注入:喷头堵塞 ----
    sim4 = spawn(["simulator.py", BASE, "1", SPEED, "--first", "4", "--fault", "noz_block@0+720,noz_block@2640+100000"], env, os.path.join(tmp, "sim4.log"))
    wait("HP-004 上线", lambda: dev("HP-004")["online"], 15)
    cmd("HP-004", "preheat")
    check("故障注入:报“喷头堵塞”,循环泵关,加热不受影响", wait("NOZ_BLOCK", lambda: (lambda x: "NOZ_BLOCK" in x["al"] and x["duty"]["pump"] == 0 and x["duty"]["syr"] > 0 and x["duty"]["tube"] > 0)(last("HP-004")), 20), last("HP-004"))
    time.sleep(7)     # 等故障结束(设备时间 720 秒)
    check("没确认前“喷头堵塞”保持,泵不恢复", (lambda x: "NOZ_BLOCK" in x["al"] and x["duty"]["pump"] == 0)(last("HP-004")), last("HP-004"))
    cmd("HP-004", "ack")
    check("堵塞排除并确认后报警清除,泵恢复", wait("ack", lambda: (lambda x: "NOZ_BLOCK" not in x["al"] and x["duty"]["pump"] > 0 and x["nozP"] < 150)(last("HP-004")), 5), last("HP-004"))

    # ---- 喷雾阶段雾化气停了:页面要据此显示“立即停止注射泵” ----
    go_ready("HP-004")
    cmd("HP-004", "nebulize")
    check("HP-004 进入喷雾,泵在转,没有停泵类报警", wait("NEBULIZE", lambda: (lambda x: x["ph"] == "NEBULIZE" and x["duty"]["pump"] > 0 and not x["al"])(last("HP-004")), 5), last("HP-004"))
    check("喷雾中喷头堵塞:接口给出 阶段=喷雾、泵输出=0、报警=NOZ_BLOCK", wait("喷雾中堵塞", lambda: (lambda x: x["ph"] == "NEBULIZE" and x["duty"]["pump"] == 0 and "NOZ_BLOCK" in x["al"])(last("HP-004")), 25), last("HP-004"))
    L4 = last("HP-004")
    check("喷雾中停泵后四路加热仍保持,阶段不自动改变", L4["ph"] == "NEBULIZE" and L4["duty"]["syr"] > 0 and L4["duty"]["noz"] > 0, L4)
    node = shutil.which("node")
    if node:
        js = ("const c=require(process.argv[1]);const L=JSON.parse(process.argv[2]);const ok={ph:'NEBULIZE',duty:{pump:80},al:[]};"
              "console.log(JSON.stringify([c.nebStopped(L),c.nebStopped(ok),c.nebStopped({ph:'NEBULIZE',duty:{pump:80},al:['PRESS_HIGH']}),"
              "c.nebStopped({ph:'NEBULIZE',duty:{pump:0},al:[]}),c.nebStopped({ph:'NEBULIZE',duty:{pump:80},al:['NOZ_LOW','WATER_LOW']}),"
              "c.nebStopped({ph:'EXPOSE',duty:{pump:0},al:['NOZ_BLOCK']}),c.nebStopped({ph:'READY',duty:{pump:0},al:['IP_HIGH']}),"
              "c.PUMP_STOP_ALARMS.slice().sort().join(),c.nebStopWhy(L),c.ledState(L,200).red,c.ledState(L,200).buzz]))")
        out = subprocess.run([node, "-e", js, os.path.join(HERE, "static", "common.js"), json.dumps(L4)], capture_output=True, text=True, encoding="utf-8")
        try:
            got = json.loads(out.stdout)
        except ValueError:
            got = out.stderr
        check("common.js 的 nebStopped():真实遥测判为要停注射泵,其余情形判断正确",
              got[:7] == [True, False, True, True, False, False, False] and got[7] == "IP_HIGH,NOZ_BLOCK,OVERTEMP_GAS,PRESS_HIGH,PRESS_LOW,SENSOR" and "喷头堵塞" in got[8] and got[9] is True, got)
    else:
        print("SKIP  没有找到 node,跳过 common.js 里 nebStopped() 的检查", flush=True)
    check("触摸屏页面有“立即停止注射泵”,并且用的是 nebStopped()", "立即停止注射泵" in local and "雾化气已停,药液会不成雾直接滴入" in local and "nebStopped(L)" in local)

    # ---- 故障注入:雾化气压不足 ----
    sim5 = spawn(["simulator.py", BASE, "1", SPEED, "--first", "5", "--fault", "noz_low@0"], env, os.path.join(tmp, "sim5.log"))
    wait("HP-005 上线", lambda: dev("HP-005")["online"], 15)
    cmd("HP-005", "preheat"); wait("PREHEAT", lambda: last("HP-005")["ph"] == "PREHEAT", 5)
    go_ready("HP-005")
    check("就绪阶段气压低不报“雾化气压不足”", "NOZ_LOW" not in last("HP-005")["al"], last("HP-005"))
    cmd("HP-005", "nebulize")
    check("故障注入:喷雾阶段报“雾化气压不足”,只提示,泵照常转", wait("NOZ_LOW", lambda: (lambda x: x["ph"] == "NEBULIZE" and "NOZ_LOW" in x["al"] and x["duty"]["pump"] > 0 and x["nozP"] < 30)(last("HP-005")), 10), last("HP-005"))
    cmd("HP-005", "expose")
    check("离开喷雾阶段后“雾化气压不足”自动消失", wait("NOZ_LOW 消失", lambda: (lambda x: x["ph"] == "EXPOSE" and "NOZ_LOW" not in x["al"])(last("HP-005")), 5), last("HP-005"))

    # ---- 操作日志 ----
    with open(os.path.join(tmp, "audit.jsonl"), encoding="utf-8") as f:
        log = [json.loads(x) for x in f]
    cmds = [r for r in log if r["event"] == "cmd"]
    check("操作日志每条命令都有来源、时间、结果", len(cmds) > 30 and all(r.get("t") and r.get("by") and r.get("result") for r in cmds), len(cmds))
    check("不带来源的命令记成“触摸屏”;日志里有中止的排队和送达", any(r["kind"] == "abort" and r["by"] == TOUCH and r["result"] == "已排队" for r in cmds) and any(r["kind"] == "abort" and r["result"] == "已送达设备" for r in cmds))
    check("被拒绝的命令也记了日志", any(r["result"].startswith("拒绝") and r.get("kind") == "selfdestruct" for r in cmds))
    check("日志里有自动开始和结束记录", any(r["event"] == "case_start" and r["case"] == case and r["by"] == "自动" for r in log) and any(r["event"] == "case_end" and r["case"] == case for r in log))

    # ---- 离线 ----
    stop(sim); stop(sim3); stop(sim4); stop(sim5)
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
    check("重启后没结束的记录还挂在设备上,会接着写", (dev("HP-002")["case"] or {}).get("id") == case3, dev("HP-002")["case"])


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
            for name in ("server.log", "sim.log", "sim3.log", "sim4.log", "sim5.log"):
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
