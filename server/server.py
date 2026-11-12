#!/usr/bin/env python3
"""输液加温监控系统 · 样机服务器(仅用 Python 标准库,python server.py 即可运行)

页面:
  /pharmacy            配液端
  /ward                护士站大屏
  /bedside?dev=IW-001  床旁屏(平板浏览器打开)
设备每 2 秒 POST /api/device/telemetry,响应里带回待执行的命令。
样机用途:无登录、无加密,只能在测试网络里用,不能接入真实病人数据。
"""
import json, os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data.json")
LOG = os.path.join(HERE, "audit.jsonl")
PORT = int(os.environ.get("PORT", "8080"))
OFFLINE_S = 10
TEMP_MIN, TEMP_MAX = 33.0, 41.0

# 示例药品加温上限表。0 表示禁止加温。必须由药剂科审核后替换,这里的数值只是演示。
DRUGS = [
    {"kw": "氯化钠", "max": 41.0}, {"kw": "葡萄糖", "max": 41.0}, {"kw": "林格", "max": 41.0},
    {"kw": "头孢", "max": 37.0}, {"kw": "青霉素", "max": 0}, {"kw": "胰岛素", "max": 0},
    {"kw": "脂肪乳", "max": 0}, {"kw": "白蛋白", "max": 37.0}, {"kw": "甘露醇", "max": 37.0},
]

lock = threading.RLock()
S = {"devices": {}, "tasks": {}, "seq": 0}


def load():
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            S.update(json.load(f))
    for d in S["devices"].values():
        d.setdefault("cmds", []); d.setdefault("reqs", [])


def save():
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(S, f, ensure_ascii=False)
    os.replace(tmp, DATA)


def audit(event, **kw):
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **kw}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def nid(prefix):
    S["seq"] += 1
    return f"{prefix}{S['seq']:04d}"


def dev(did):
    d = S["devices"].get(did)
    if d is None:
        d = S["devices"][did] = {"id": did, "bed": "", "last": {}, "seen": 0, "cmds": [], "reqs": [], "task": None}
    return d


def drug_limit(name):
    """返回 (上限, 命中的关键字)。多个命中取最严格的。未命中按 37 ℃。"""
    hit = [d for d in DRUGS if d["kw"] in name]
    if not hit:
        return 37.0, None
    m = min(hit, key=lambda d: d["max"])
    return m["max"], m["kw"]


def active_task(d):
    t = S["tasks"].get(d.get("task") or "")
    return t if t and t["status"] not in ("done", "cancelled") else None


def start_cmd(t):
    return {"c": "start", "task": t["id"], "vol": t["volume_ml"], "rate": t["rate_mlh"],
            "temp": t["temp_c"], "df": t["drip_factor"]}


# ---------- 业务 ----------
def api_create_task(b):
    for k in ("bed", "patient_name", "patient_id", "drug", "volume_ml", "rate_mlh", "bag_code"):
        if not str(b.get(k, "")).strip():
            return 400, {"err": f"缺少 {k}"}
    vol, rate = float(b["volume_ml"]), float(b["rate_mlh"])
    if not (10 <= vol <= 3000) or not (5 <= rate <= 1000):
        return 400, {"err": "容量需在 10–3000 mL,流速需在 5–1000 mL/h"}
    limit, kw = drug_limit(b["drug"])
    want = float(b.get("temp_c") or 0)
    temp = 0.0 if (want == 0 or limit == 0) else max(TEMP_MIN, min(want, limit, TEMP_MAX))
    note = ""
    if want and limit == 0:
        note = f"含“{kw}”,按药品表禁止加温"
    elif want and temp < want:
        note = f"含“{kw or '未登记药品'}”,温度上限 {limit:g} ℃"
    target = next((d for d in S["devices"].values() if d["bed"] == str(b["bed"])), None)
    if target and active_task(target):
        return 409, {"err": f"{b['bed']} 床已有未完成的任务"}
    t = {"id": nid("T"), "bed": str(b["bed"]), "patient_name": b["patient_name"], "patient_id": str(b["patient_id"]),
         "drug": b["drug"], "volume_ml": vol, "rate_mlh": rate, "temp_c": temp, "temp_max": limit,
         "drip_factor": int(b.get("drip_factor") or 20), "bag_code": str(b["bag_code"]),
         "status": "pending", "verified": False, "note": note, "created": time.time(), "by": b.get("by", "")}
    S["tasks"][t["id"]] = t
    if target:
        target["task"] = t["id"]
    audit("task_create", task=t["id"], bed=t["bed"], drug=t["drug"], rate=rate, temp=temp, by=t["by"])
    return 200, {"task": t, "assigned": bool(target)}


def api_telemetry(b):
    d = dev(str(b.get("id", "?")))
    d["last"], d["seen"] = b, time.time()
    if not d.get("task"):   # 设备空闲时领取本床位排队中的任务
        for t in S["tasks"].values():
            if t["status"] == "pending" and t["bed"] == d["bed"] and d["bed"]:
                d["task"] = t["id"]; break
    t = active_task(d)
    st = b.get("st")
    if t:
        if st in ("RUN", "PAUSE") and b.get("task") == t["id"]:
            t["status"] = "running" if st == "RUN" else "paused"
        elif st == "DONE" and b.get("task") == t["id"]:
            t["status"] = "done"; t["ended"] = time.time(); d["task"] = None; d["reqs"] = []
            audit("task_done", task=t["id"], dev=d["id"], alarms=b.get("al"))
        elif st == "IDLE" and t["status"] in ("running", "paused"):
            if b.get("task") != t["id"]:     # 设备重启后丢了任务:不自动恢复,退回待核对
                rem = t.get("last_rem")
                if rem and rem > 0:
                    t["volume_ml"] = round(rem)
                t["status"], t["verified"] = "pending", False
                t["note"] = "设备曾重启,需重新核对后开始;容量已改为重启前的余量"
                audit("device_restart", task=t["id"], dev=d["id"], rem=rem)
        if st in ("RUN", "PAUSE") and isinstance(b.get("rem"), (int, float)):
            t["last_rem"] = b["rem"]
    cmds, d["cmds"] = d["cmds"], []
    brief = None
    if t and t["status"] == "pending":
        brief = {"id": t["id"], "temp": t["temp_c"], "rate": t["rate_mlh"], "vol": t["volume_ml"]}
    return 200, {"cmds": cmds, "task": brief}


def api_bind(b):
    d = dev(str(b["dev"]))
    bed = str(b.get("bed", "")).strip()
    for o in S["devices"].values():
        if o is not d and bed and o["bed"] == bed:
            return 409, {"err": f"{bed} 床已绑定设备 {o['id']}"}
    d["bed"] = bed
    audit("bind", dev=d["id"], bed=bed)
    return 200, {"ok": True}


def api_verify(b):
    d = dev(str(b["dev"])); t = active_task(d)
    if not t:
        return 404, {"err": "该设备没有待执行任务"}
    ok_p = str(b.get("patient_id", "")).strip() == t["patient_id"]
    ok_b = str(b.get("bag_code", "")).strip() == t["bag_code"]
    t["verified"] = ok_p and ok_b
    audit("verify", task=t["id"], dev=d["id"], patient_ok=ok_p, bag_ok=ok_b, by=b.get("by", ""))
    if not t["verified"]:
        return 409, {"err": "核对不一致:" + ("腕带与任务不符 " if not ok_p else "") + ("药袋与任务不符" if not ok_b else ""),
                     "patient_ok": ok_p, "bag_ok": ok_b}
    return 200, {"ok": True}


def api_start(b):
    d = dev(str(b["dev"])); t = active_task(d)
    if not t or t["status"] != "pending":
        return 404, {"err": "没有可开始的任务"}
    if not t["verified"]:
        return 409, {"err": "尚未完成腕带与药袋核对"}
    if time.time() - d["seen"] > OFFLINE_S:
        return 409, {"err": "设备离线"}
    d["cmds"].append(start_cmd(t))
    t["started"] = time.time(); t["nurse"] = b.get("by", "")
    audit("start", task=t["id"], dev=d["id"], by=b.get("by", ""))
    return 200, {"ok": True}


def clamp_value(t, kind, v):
    if kind == "temp":
        if v == 0:
            return 0.0
        return max(TEMP_MIN, min(v, t["temp_max"] or TEMP_MIN, TEMP_MAX)) if t["temp_max"] else 0.0
    return max(5.0, min(v, 1000.0))


def api_cmd(b):
    """src=ward 远程:pause/mute 直接执行,其余变成待床旁确认的请求。src=bedside:直接执行。"""
    d = dev(str(b["dev"])); t = active_task(d)
    kind, src, by = b.get("kind"), b.get("src", "ward"), b.get("by", "")
    if kind not in ("pause", "resume", "mute", "rate", "temp", "finish", "cancel"):
        return 400, {"err": "未知操作"}
    if kind == "cancel":
        if t and t["status"] == "pending":
            t["status"] = "cancelled"; d["task"] = None
            audit("cancel", task=t["id"], by=by)
            return 200, {"ok": True}
        return 409, {"err": "只有未开始的任务可以取消"}
    v = float(b.get("value") or 0)
    if kind in ("rate", "temp"):
        if not t:
            return 404, {"err": "没有进行中的任务"}
        v = clamp_value(t, kind, v)
    direct = src == "bedside" or kind in ("pause", "mute")
    if direct:
        c = {"c": kind}
        if kind in ("rate", "temp"):
            c["v"] = v
            t["rate_mlh" if kind == "rate" else "temp_c"] = v
        d["cmds"].append(c)
        if kind == "pause":
            d["reqs"] = []
        audit("cmd", dev=d["id"], kind=kind, value=v, src=src, by=by)
        return 200, {"ok": True, "direct": True, "value": v}
    r = {"id": nid("R"), "kind": kind, "value": v, "by": by, "ts": time.time()}
    d["reqs"] = [x for x in d["reqs"] if x["kind"] != kind] + [r]
    audit("request", dev=d["id"], kind=kind, value=v, by=by, req=r["id"])
    return 200, {"ok": True, "direct": False, "req": r}


def api_answer(b):
    d = dev(str(b["dev"])); t = active_task(d)
    r = next((x for x in d["reqs"] if x["id"] == b.get("req")), None)
    if not r:
        return 404, {"err": "请求不存在或已处理"}
    d["reqs"].remove(r)
    if b.get("accept"):
        c = {"c": r["kind"]}
        if r["kind"] in ("rate", "temp"):
            c["v"] = r["value"]
            if t:
                t["rate_mlh" if r["kind"] == "rate" else "temp_c"] = r["value"]
        d["cmds"].append(c)
    audit("answer", dev=d["id"], req=r["id"], kind=r["kind"], value=r["value"], accept=bool(b.get("accept")), by=b.get("by", ""))
    return 200, {"ok": True}


def api_state():
    now = time.time()
    devs = []
    for d in sorted(S["devices"].values(), key=lambda x: (x["bed"] == "", x["bed"].zfill(4), x["id"])):
        devs.append({"id": d["id"], "bed": d["bed"], "online": now - d["seen"] <= OFFLINE_S, "last": d["last"],
                     "reqs": d["reqs"], "task": active_task(d)})
    recent = sorted(S["tasks"].values(), key=lambda t: -t["created"])[:40]
    return 200, {"now": now, "devices": devs, "tasks": recent, "drugs": DRUGS}


POST = {"/api/tasks": api_create_task, "/api/device/telemetry": api_telemetry, "/api/device/bind": api_bind,
        "/api/bedside/verify": api_verify, "/api/bedside/start": api_start, "/api/cmd": api_cmd,
        "/api/request/answer": api_answer}
PAGES = {"/": "ward.html", "/ward": "ward.html", "/pharmacy": "pharmacy.html", "/bedside": "bedside.html"}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path).path
        if p in PAGES:
            with open(os.path.join(HERE, "static", PAGES[p]), "rb") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if p == "/api/state":
            with lock:
                return self.send(*api_state())
        if p == "/api/log":
            lines = []
            if os.path.exists(LOG):
                with open(LOG, encoding="utf-8") as f:
                    lines = [json.loads(x) for x in f.readlines()[-200:]]
            return self.send(200, lines)
        self.send(404, {"err": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        fn = POST.get(p)
        if not fn:
            return self.send(404, {"err": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            with lock:
                code, out = fn(body)
                if p != "/api/device/telemetry":
                    save()
        except (ValueError, KeyError, TypeError) as e:
            code, out = 400, {"err": f"请求格式错误: {e}"}
        self.send(code, out)


def autosave():
    while True:
        time.sleep(15)
        with lock:
            save()


if __name__ == "__main__":
    load()
    threading.Thread(target=autosave, daemon=True).start()
    print(f"服务器已启动: http://<本机IP>:{PORT}/ward  /pharmacy  /bedside?dev=IW-001", flush=True)
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
    except KeyboardInterrupt:
        with lock:
            save()
        sys.exit(0)
