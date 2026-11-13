#!/usr/bin/env python3
"""hPIPAC 前端加热系统 · 盒内服务程序(只用 Python 标准库,python server.py 即可运行)

运行在主控盒里的树莓派上。树莓派开一个只供盒内使用的 Wi-Fi 热点,安全主控 ESP32 连这个热点,
每 2 秒 POST /api/device/telemetry,响应里带回触摸屏上排队的命令。不接医院网络。

页面:
  /  或 /local?dev=HP-001   触摸屏本机界面(800×480),全部操作都在这一页
  /panel                    主机面板模拟,开发和演示用
接口见 1-design/interface-spec.md 第 7 节。

手术记录是自动的:设备从待机进入预热时开一个 CSV,回到待机时关上,文件在数据目录的 cases/ 下。
环境变量:PORT 端口(默认 8080);HOST 监听地址(默认 0.0.0.0);HP_DATA_DIR 数据目录(默认本文件所在目录)。
样机软件,没有登录和加密:只能接在盒内热点上,不要接到任何别的网络。
"""
import csv, json, math, os, re, sys, threading, time
from collections import deque
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("HP_DATA_DIR") or HERE
DATA = os.path.join(DATA_DIR, "data.json")
LOG = os.path.join(DATA_DIR, "audit.jsonl")
CASES = os.path.join(DATA_DIR, "cases")
PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "0.0.0.0")

OFFLINE_S = 5          # 设备多少秒没有上报算离线
CMD_TTL_S = 30         # 命令排队超过这么久没被取走就作废,免得设备很久以后才执行
HIST_KEEP_S = 7200     # 曲线数据保留 2 小时
HIST_MAX_PTS = 900     # /api/history 一次最多返回的点数,多了就均匀抽稀

PHASES = ("IDLE", "PREHEAT", "READY", "NEBULIZE", "EXPOSE", "EVAC", "DONE")
SENSORS = ("syr1", "syr2", "noz1", "noz2", "humPlate", "humOut", "gasEnd", "ip1", "ip2")
DUTIES = ("syr", "noz", "hum", "tube", "pump")
# 每种命令允许在哪些阶段下发。None 表示任何阶段都可以。设备固件还会再检查一遍。
CMD_PHASE = {
    "preheat": ("IDLE",), "ready": ("PREHEAT",), "nebulize": ("READY",), "expose": ("NEBULIZE",),
    "evac": ("EXPOSE",), "finish": ("EVAC", "DONE"), "abort": None,
    "target": None, "flow": None, "nebFlow": None, "exposeMin": None, "circInExpose": None, "ack": None, "mute": None,
}
CMD_CN = {"preheat": "开始预热", "ready": "手动确认就绪", "nebulize": "开始喷雾", "expose": "开始暴露计时",
          "evac": "提前结束暴露", "finish": "结束手术", "abort": "中止", "target": "改目标温度", "flow": "改循环流量", "nebFlow": "改雾化气流量",
          "exposeMin": "改暴露时间", "circInExpose": "改暴露阶段循环", "ack": "确认报警", "mute": "消音"}
PH_CN = {"IDLE": "待机", "PREHEAT": "预热", "READY": "就绪", "NEBULIZE": "喷雾", "EXPOSE": "暴露", "EVAC": "排气", "DONE": "结束"}
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
ALARM_RE = re.compile(r"^[A-Z_]{1,24}$")
CSV_HEAD = (["time", "epoch", "case", "ph", "phSec", "exposeLeft", "target", "exposeMin", "flowSet", "nebFlow", "circInExpose"]
            + list(SENSORS) + ["press", "nozP", "flow"] + ["duty_" + k for k in DUTIES] + ["alarms", "muted"])

lock = threading.RLock()
S = {"devices": {}, "cases": {}}   # 会写进 data.json 的部分
HIST = {}                          # 设备编号 -> deque,曲线数据只放内存
CMDS = {}                          # 设备编号 -> 待下发命令列表,只放内存


# ---------- 存盘和日志 ----------

def load():
    os.makedirs(CASES, exist_ok=True)
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            S.update(json.load(f))


def save():
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(S, f, ensure_ascii=False)
    os.replace(tmp, DATA)


def audit(event, **kw):
    """只追加、不修改的操作日志。每条命令无论成败都记一行。"""
    rec = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **kw}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- 输入清洗 ----------

def num(v):
    """转成有限的浮点数;不是数字(含 true/false)返回 None。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def text(v, limit):
    """命令来源这类文字:去掉控制字符和首尾空白,限制长度。"""
    if not isinstance(v, str):
        return ""
    return "".join(ch for ch in v if ch.isprintable()).strip()[:limit]


def clean_telemetry(b):
    """只留下约定里的字段,并且强制成数字或 null,页面拿到的就一定是干净的数据。"""
    t = b.get("t") if isinstance(b.get("t"), dict) else {}
    duty = b.get("duty") if isinstance(b.get("duty"), dict) else {}
    al = b.get("al") if isinstance(b.get("al"), list) else []
    return {
        "ph": b["ph"], "target": num(b.get("target")), "exposeMin": num(b.get("exposeMin")),
        "flowSet": num(b.get("flowSet")), "nebFlow": num(b.get("nebFlow")), "circInExpose": b.get("circInExpose") is True,
        "t": {k: num(t.get(k)) for k in SENSORS},
        "press": num(b.get("press")), "nozP": num(b.get("nozP")), "flow": num(b.get("flow")),
        "duty": {k: num(duty.get(k)) or 0 for k in DUTIES},
        "phSec": num(b.get("phSec")) or 0, "exposeLeft": num(b.get("exposeLeft")) if num(b.get("exposeLeft")) is not None else -1,
        "al": [a for a in al if isinstance(a, str) and ALARM_RE.match(a)][:16], "muted": b.get("muted") is True,
    }


def ip_mean(t):
    v = [x for x in (t.get("ip1"), t.get("ip2")) if x is not None]
    return sum(v) / len(v) if v else None


def heaters_ready(L):
    """注射筒和喷头歧管都在目标 ±0.5 ℃ 内、喷头端气温到目标 −1 ℃:手动确认就绪的前提。"""
    t, tg = L.get("t") or {}, L.get("target")
    if tg is None:
        return False
    pair = [t.get(k) for k in ("syr1", "syr2", "noz1", "noz2")]
    return all(x is not None and abs(x - tg) <= 0.5 for x in pair) and t.get("gasEnd") is not None and t["gasEnd"] >= tg - 1.0


# ---------- 设备和手术记录 ----------

def online(d, now=None):
    return (now or time.time()) - d["seen"] <= OFFLINE_S


def case_view(cid):
    c = S["cases"].get(cid) if cid else None
    return None if c is None else {k: c.get(k) for k in ("id", "dev", "start", "end", "rows")}


def csv_path(cid):
    return os.path.join(CASES, cid + ".csv")


def csv_row(c, L, now):
    t, duty = L["t"], L["duty"]
    f = lambda v: "" if v is None else v
    return ([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), round(now, 2), c["id"],
             L["ph"], f(L["phSec"]), f(L["exposeLeft"]), f(L["target"]), f(L["exposeMin"]), f(L["flowSet"]), f(L["nebFlow"]), int(L["circInExpose"])]
            + [f(t[k]) for k in SENSORS] + [f(L["press"]), f(L["nozP"]), f(L["flow"])] + [f(duty[k]) for k in DUTIES]
            + ["|".join(L["al"]), int(L["muted"])])


def case_open(d, ph, now):
    """开始一次手术记录。正常是从待机进入预热时;服务程序重启后第一次收到正在运行的设备,也马上接着记。"""
    did = d["id"]
    cid = base = "%s-%s" % (did, time.strftime("%Y%m%d-%H%M%S", time.localtime(now)))
    n = 1
    while cid in S["cases"]:
        n += 1
        cid = "%s-%d" % (base, n)
    S["cases"][cid] = {"id": cid, "dev": did, "start": now, "end": None, "rows": 0}
    with open(csv_path(cid), "w", encoding="utf-8-sig", newline="") as f:   # 带 BOM,表格软件才能认出中文
        csv.writer(f).writerow(CSV_HEAD)
    d["case"] = cid
    audit("case_start", dev=did, case=cid, by="自动", reason="进入预热" if ph == "PREHEAT" else "收到运行中的设备(阶段 %s)" % ph)
    save()


def case_close(d, now):
    c = S["cases"][d["case"]]
    c["end"] = now
    d["lastCase"], d["case"] = c["id"], None
    audit("case_end", dev=d["id"], case=c["id"], by="自动", rows=c["rows"])
    save()


def api_telemetry(b):
    did = b.get("id")
    if not isinstance(did, str) or not ID_RE.match(did):
        return 400, {"err": "设备编号只能用字母、数字、横线和下划线,最长 32 个字符"}
    if b.get("ph") not in PHASES:
        return 400, {"err": "阶段名不在约定之内"}
    now = time.time()
    L = clean_telemetry(b)
    d = S["devices"].get(did)
    if d is None:
        d = S["devices"][did] = {"id": did, "last": {}, "seen": 0, "case": None, "lastCase": None}
        audit("device_new", dev=did)
    d["last"], d["seen"] = L, now
    t = L["t"]
    h = HIST.setdefault(did, deque(maxlen=120000))
    h.append({"ts": round(now, 2), "ph": L["ph"], "target": L["target"], "syr": t["syr1"], "noz": t["noz1"],
              "humOut": t["humOut"], "gasEnd": t["gasEnd"], "ip1": t["ip1"], "ip2": t["ip2"],
              "ipMean": None if ip_mean(t) is None else round(ip_mean(t), 2), "press": L["press"], "nozP": L["nozP"], "flow": L["flow"]})
    while h and now - h[0]["ts"] > HIST_KEEP_S:
        h.popleft()
    # 自动记录:离开待机就开始,回到待机时写完这一行再关上
    if not d.get("case") and L["ph"] != "IDLE":
        case_open(d, L["ph"], now)
    c = S["cases"].get(d["case"]) if d.get("case") else None
    if c:
        with open(csv_path(c["id"]), "a", encoding="utf-8", newline="") as f:
            csv.writer(f).writerow(csv_row(c, L, now))
        c["rows"] += 1
        if L["ph"] == "IDLE":
            case_close(d, now)
    out = []
    for q in CMDS.pop(did, []):
        if now - q["ts"] > CMD_TTL_S:
            audit("cmd", dev=did, kind=q["kind"], value=q.get("value"), by=q["by"], result="作废:排队超过 %d 秒没有送达" % CMD_TTL_S)
            continue
        audit("cmd", dev=did, kind=q["kind"], value=q.get("value"), by=q["by"], result="已送达设备")
        out.append({"kind": q["kind"], "value": q["value"]} if "value" in q else {"kind": q["kind"]})
    return 200, {"cmds": out}


def check_value(kind, v):
    """返回 (规范化后的值, 错误信息)。没有参数的命令返回 (None, None)。"""
    if kind == "target":
        x = num(v)
        if x is None or not 37.0 <= x <= 43.0:
            return None, "目标温度必须是 37.0 到 43.0 ℃ 之间的数"
        return round(x, 1), None
    if kind == "flow":
        x = num(v)
        if x is None or not 0 <= x <= 15:
            return None, "循环流量必须是 0 到 15 L/min 之间的数"
        return round(x, 1), None
    if kind == "nebFlow":
        x = num(v)
        if x is None or not 5 <= x <= 15:
            return None, "雾化气流量必须是 5 到 15 L/min 之间的数"
        return round(x, 1), None
    if kind == "exposeMin":
        x = num(v)
        if x is None or x != int(x) or not 1 <= x <= 60:
            return None, "暴露时间必须是 1 到 60 分钟之间的整数"
        return int(x), None
    if kind == "circInExpose":
        if not isinstance(v, bool):
            return None, "暴露阶段是否循环只能是 true 或 false"
        return v, None
    return None, None


def api_cmd(b):
    # 只有触摸屏会发命令(面板模拟页的按键也走这里),来源只用来记日志,不是身份认证
    did, kind, by = b.get("dev"), b.get("kind"), text(b.get("by"), 32) or "触摸屏"
    rec = {"dev": did if isinstance(did, str) else None, "kind": kind if isinstance(kind, str) else None, "value": b.get("value"), "by": by}

    def reject(code, err):
        audit("cmd", **rec, result="拒绝:" + err)
        return code, {"err": err}

    if kind not in CMD_PHASE:
        return reject(400, "没有这种命令")
    val, err = check_value(kind, b.get("value"))
    if err:
        return reject(400, err)
    d = S["devices"].get(did) if isinstance(did, str) else None
    if d is None:
        return reject(404, "没有这台设备")
    if not online(d):
        return reject(409, "主控无响应,命令送不到。要中止请按主机上的红色中止键")
    ph = d["last"].get("ph")
    if CMD_PHASE[kind] is not None and ph not in CMD_PHASE[kind]:
        return reject(409, "现在是“%s”阶段,不能“%s”" % (PH_CN.get(ph, ph), CMD_CN[kind]))
    if kind == "ready" and not heaters_ready(d["last"]):
        return reject(409, "注射筒、喷头歧管、输气管还没有全部到温,不能手动确认就绪")
    q = {"kind": kind, "by": by, "ts": time.time()}
    if val is not None:
        q["value"] = rec["value"] = val
    CMDS.setdefault(did, []).append(q)
    audit("cmd", **rec, result="已排队")
    return 200, {"ok": True, "kind": kind, "value": val}


def api_state():
    now = time.time()
    devs = [{"id": d["id"], "online": online(d, now), "seen": d["seen"], "last": d["last"],
             "case": case_view(d["case"]), "lastCase": case_view(d.get("lastCase"))}
            for d in sorted(S["devices"].values(), key=lambda x: x["id"])]
    return 200, {"now": now, "devices": devs}


def api_history(q):
    did = q.get("dev", [""])[0]
    if did not in S["devices"]:
        return 404, {"err": "没有这台设备"}
    try:
        sec = float(q.get("sec", ["1800"])[0])
    except ValueError:
        return 400, {"err": "sec 必须是数字"}
    if not (math.isfinite(sec) and sec > 0):
        return 400, {"err": "sec 必须大于 0"}
    now = time.time()
    pts = [p for p in HIST.get(did, ()) if now - p["ts"] <= min(sec, HIST_KEEP_S)]
    if len(pts) > HIST_MAX_PTS:   # 均匀抽稀,保留最后一个点
        step = len(pts) / HIST_MAX_PTS
        pts = [pts[min(len(pts) - 1, int(i * step))] for i in range(HIST_MAX_PTS - 1)] + [pts[-1]]
    return 200, {"dev": did, "now": now, "pts": pts}


def case_log(q):
    """返回 (状态码, 正文, 类型, 附加响应头)。"""
    did, cid = q.get("dev", [""])[0], q.get("case", [""])[0]
    d = S["devices"].get(did)
    if d is None:
        return 404, {"err": "没有这台设备"}, None, {}
    cid = cid or d["case"] or d.get("lastCase") or ""
    c = S["cases"].get(cid)
    if c is None or c["dev"] != did or not os.path.exists(csv_path(cid)):
        return 404, {"err": "没有这次手术的记录"}, None, {}
    with open(csv_path(cid), "rb") as f:
        return 200, f.read(), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="%s.csv"' % cid}


POST = {"/api/device/telemetry": api_telemetry, "/api/cmd": api_cmd}
PAGES = {"/": ("local.html", "text/html"), "/panel": ("panel.html", "text/html"),
         "/local": ("local.html", "text/html"), "/common.js": ("common.js", "application/javascript")}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        if p in PAGES:
            name, ctype = PAGES[p]
            with open(os.path.join(HERE, "static", name), "rb") as f:
                return self.send(200, f.read(), ctype + "; charset=utf-8")
        if p == "/api/state":
            with lock:
                return self.send(*api_state())
        if p == "/api/history":
            with lock:
                return self.send(*api_history(q))
        if p == "/api/case/log":
            with lock:
                code, body, ctype, extra = case_log(q)
            return self.send(code, body, ctype or "application/json; charset=utf-8", extra)
        self.send(404, {"err": "没有这个地址"})

    def do_POST(self):
        p = urlparse(self.path).path
        fn = POST.get(p)
        if not fn:
            return self.send(404, {"err": "没有这个地址"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                return self.send(413, {"err": "请求太大"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("正文必须是 JSON 对象")
            with lock:
                code, out = fn(body)
                if p != "/api/device/telemetry":
                    save()
        except (ValueError, KeyError, TypeError) as e:
            code, out = 400, {"err": "请求格式错误:%s" % e}
        self.send(code, out)


def autosave():
    while True:
        time.sleep(15)
        with lock:
            save()


if __name__ == "__main__":
    load()
    threading.Thread(target=autosave, daemon=True).start()
    print("盒内服务程序已启动,监听 %s:%d。触摸屏: /local?dev=设备编号   面板模拟: /panel" % (HOST, PORT), flush=True)
    print("样机软件,没有登录和加密,只能接在盒内热点上。", flush=True)
    try:
        ThreadingHTTPServer((HOST, PORT), H).serve_forever()
    except KeyboardInterrupt:
        with lock:
            save()
        sys.exit(0)
