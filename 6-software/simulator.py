#!/usr/bin/env python3
"""hPIPAC 前端加热系统 · 安全主控模拟器。没有硬件时用它代替 ESP32,让触摸屏界面有数据可看、有命令可执行。

用法:
  python simulator.py [服务器地址] [台数] [加速倍数] [--first 起始编号] [--fault 名称@秒[+持续秒],...]
  python simulator.py http://127.0.0.1:8080 1 20
  python simulator.py http://127.0.0.1:8080 1 20 --fault ip_high@600

模拟的内容:接口约定里的阶段机、四路加热和循环泵的开关规则、报警条件和联锁动作,加上一个很粗的热模型。
热模型里的时间常数是随手取的,只为了让曲线看起来像样,不是实测数据,不能拿来估计真机的升温时间。

故障注入(只对第一台模拟设备生效;秒数是模拟器启动后的“设备时间”,受加速倍数影响):
  ip_high        腹腔探头 1 读数升到约 44.2 ℃(默认持续 180 秒)    → IP_HIGH
  overtemp_drug  注射筒加热失控升温                                → OVERTEMP_DRUG
  overtemp_gas   输气管加热失控升温                                → OVERTEMP_GAS
  sensor         注射筒保护传感器读数偏高 2.5 ℃                     → SENSOR
  sensor_open    输气管喷头端传感器断线(上报 null)                 → SENSOR
  press_high     腹腔压力升到约 19.5 mmHg(默认持续 30 秒)          → PRESS_HIGH
  press_low      腹腔压力掉到约 4.5 mmHg(默认持续 30 秒;泵在转才报)→ PRESS_LOW
  noz_block      喷嘴堵塞:泵一转雾化气压就升到 150 kPa 以上(默认持续 60 秒)→ NOZ_BLOCK
  noz_low        喷头接口漏气:雾化气压只有正常的三成(喷雾阶段才报)  → NOZ_LOW
  water_low      加湿罐缺水:底座很热但出口气温上不去(泵在转才报)  → WATER_LOW
压力故障只在气腹已经建立(预热 1 分钟以后到暴露结束)时才看得出来。
"""
import json, math, random, sys, time, urllib.request

AMB = 22.0            # 室温
BODY = 37.0           # 不循环时腹腔温度回落的方向
PHASES = ("IDLE", "PREHEAT", "READY", "NEBULIZE", "EXPOSE", "EVAC", "DONE")
LATCHED = ("OVERTEMP_DRUG", "OVERTEMP_GAS", "SENSOR")           # 只有重新上电才能清除
NEED_ACK = ("IP_HIGH", "PRESS_HIGH", "PRESS_LOW", "WATER_LOW", "NOZ_BLOCK", "EXPOSE_END")   # 条件消失后还要按“确认”
FAULT_DUR = {"ip_high": 180, "press_high": 30, "press_low": 30, "noz_block": 60}
FAULTS = ("ip_high", "overtemp_drug", "overtemp_gas", "sensor", "sensor_open", "press_high", "press_low", "water_low", "noz_block", "noz_low")


def lag(cur, goal, tau, dt):
    """一阶惯性:cur 以时间常数 tau 靠近 goal。"""
    return goal + (cur - goal) * math.exp(-dt / tau)


def parse_faults(spec):
    out = []
    for item in filter(None, spec.split(",")):
        name, _, when = item.partition("@")
        start, _, dur = when.partition("+")
        if name not in FAULTS or not start:
            sys.exit("看不懂的故障写法: %s。可用的名称: %s,写法如 ip_high@600 或 noz_block@300+60" % (item, " ".join(FAULTS)))
        out.append((name, float(start), float(dur) if dur else FAULT_DUR.get(name, float("inf"))))
    return out


class Device:
    def __init__(self, did, faults=()):
        self.id, self.faults = did, list(faults)
        self.now = 0.0                                   # 设备时间,秒
        self.ph, self.phSec = "IDLE", 0.0
        self.target, self.exposeMin, self.flowSet, self.circ = 42.0, 30, 10.0, False
        self.nebFlow = 12.0                              # 喷雾阶段的雾化气流量
        self.T = {"syr": AMB, "noz": AMB, "humPlate": AMB, "humOut": AMB, "gasEnd": AMB, "ip1": 36.6, "ip2": 36.3}
        self.ipOff = 0.0                                 # ip_high 故障的程度,0 到 1
        self.press, self.flow, self.nozP = 0.0, 0.0, 0.0   # 气腹还没建立,压力为 0;泵没转,雾化气压为 0
        self.pumpRun = 0.0                               # 循环泵已经连续运转的秒数
        self.al = set()
        self.tm = {}                                     # 各报警条件已经持续的秒数
        self.sensorOff = set()                           # SENSOR 报警关掉的通路
        self.ipSkip = False                              # 操作者已手动跳过腹腔温度条件
        self.lost = 0.0                                  # READY 里条件已经失去的秒数
        self.muteLeft = 0.0
        self.on = dict.fromkeys(("syr", "noz", "hum", "tube", "pump"), False)
        self.duty = dict.fromkeys(self.on, 0)
        self.rd = {}                                     # 本拍的传感器读数(带噪声,可能是 None)

    # ----- 故障 -----
    def fault(self, name):
        return any(n == name and s <= self.now < s + d for n, s, d in self.faults)

    # ----- 阶段 -----
    def go(self, ph):
        if ph == "IDLE":
            self.ipSkip = False
            self.al.discard("EXPOSE_END")
        self.ph, self.phSec, self.lost = ph, 0.0, 0.0
        self.tm.pop("ip_low", None)

    def flow_want(self):
        """泵该按多大流量转:喷雾阶段用雾化气流量,其余阶段用循环流量。"""
        return self.nebFlow if self.ph == "NEBULIZE" else self.flowSet

    def heat_ok(self):
        r, tg = self.rd, self.target
        pair = [r.get(k) for k in ("syr1", "syr2", "noz1", "noz2")]
        return all(x is not None and abs(x - tg) <= 0.5 for x in pair) and r.get("gasEnd") is not None and r["gasEnd"] >= tg - 1.0

    def ip_mean(self):
        v = [x for x in (self.rd.get("ip1"), self.rd.get("ip2")) if x is not None]
        return sum(v) / len(v) if v else None

    def ip_ok(self):
        m = self.ip_mean()
        return m is not None and m >= self.target - 1.0

    def command(self, c):
        """执行服务器转来的命令。返回 None 表示接受,否则返回拒绝原因。"""
        k, v, ph = c.get("kind"), c.get("value"), self.ph
        isnum = isinstance(v, (int, float)) and not isinstance(v, bool)
        if k == "preheat":
            if ph != "IDLE": return "不在待机"
            self.go("PREHEAT")
        elif k == "ready":
            if ph != "PREHEAT": return "不在预热"
            if not self.heat_ok(): return "四路还没到温"
            self.ipSkip = True
            self.go("READY")
        elif k == "nebulize":
            if ph != "READY": return "不在就绪"
            self.go("NEBULIZE")
        elif k == "expose":
            if ph != "NEBULIZE": return "不在喷雾"
            self.go("EXPOSE")
        elif k == "evac":
            if ph != "EXPOSE": return "不在暴露"
            self.go("EVAC")
        elif k == "finish":
            if ph == "EVAC": self.go("DONE")
            elif ph == "DONE": self.go("IDLE")
            else: return "不在排气或结束"
        elif k == "abort":
            # 待机、排气、结束阶段本来就全关,中止不改变阶段
            if ph in ("PREHEAT", "READY", "NEBULIZE", "EXPOSE"): self.go("EVAC")
        elif k == "target":
            if not (isnum and 37.0 <= v <= 43.0): return "目标温度超范围"
            self.target = round(float(v), 1)
        elif k == "flow":
            if not (isnum and 0 <= v <= 15): return "流量超范围"
            self.flowSet = round(float(v), 1)
        elif k == "nebFlow":
            if not (isnum and 5 <= v <= 15): return "雾化气流量超范围"
            self.nebFlow = round(float(v), 1)
        elif k == "exposeMin":
            if not (isnum and 1 <= v <= 60): return "暴露时间超范围"
            self.exposeMin = int(v)
        elif k == "circInExpose":
            if not isinstance(v, bool): return "参数不是 true/false"
            self.circ = v
        elif k == "ack":
            r = self.rd
            if "IP_HIGH" in self.al and all(r.get(x) is None or r[x] < 42.5 for x in ("ip1", "ip2")): self.al.discard("IP_HIGH")
            if self.press < 18.0: self.al.discard("PRESS_HIGH")
            if self.nozP < 150.0: self.al.discard("NOZ_BLOCK")
            self.al.discard("PRESS_LOW"); self.tm.pop("press_low", None)   # 泵停着时不判;恢复后还低会再报
            self.al.discard("WATER_LOW"); self.tm.pop("water", None)
            self.al.discard("EXPOSE_END")
        elif k == "mute":
            self.muteLeft = 120.0
        else:
            return "不认识的命令"
        return None

    # ----- 每一步(dt 秒设备时间) -----
    def held(self, key, cond, dt):
        """条件连续成立的秒数;一不成立就清零。"""
        self.tm[key] = self.tm.get(key, 0.0) + dt if cond else 0.0
        return self.tm[key]

    def outputs(self):
        ph, al = self.ph, self.al
        heat_drug = ph in ("PREHEAT", "READY", "NEBULIZE")
        heat_gas = ph in ("PREHEAT", "READY", "NEBULIZE", "EXPOSE")
        on = {"syr": heat_drug, "noz": heat_drug, "hum": heat_gas, "tube": heat_gas,
              # 预热阶段要等气腹建立(压力到 8 mmHg)泵才转
              # 喷雾阶段泵必须转:这股气就是雾化气
              "pump": (ph == "PREHEAT" and self.press >= 8.0) or ph in ("READY", "NEBULIZE") or (ph == "EXPOSE" and self.circ)}
        if "OVERTEMP_DRUG" in al: on["syr"] = on["noz"] = False
        if "OVERTEMP_GAS" in al: on["hum"] = on["tube"] = on["pump"] = False
        if "IP_HIGH" in al: on = dict.fromkeys(on, False)
        if "PRESS_HIGH" in al or "PRESS_LOW" in al or "NOZ_BLOCK" in al: on["pump"] = False
        if "WATER_LOW" in al: on["hum"] = False
        for ch in self.sensorOff: on[ch] = False
        if self.flow_want() <= 0: on["pump"] = False
        self.on = on

    def physics(self, dt):
        T, on, tg = self.T, self.on, self.target
        T["syr"] = lag(T["syr"], (45.5 if self.fault("overtemp_drug") else tg) if on["syr"] else AMB, 120 if on["syr"] else 900, dt)
        T["noz"] = lag(T["noz"], tg if on["noz"] else AMB, 90 if on["noz"] else 700, dt)
        dry = self.fault("water_low")
        plate = 80.0 if dry else 58.0 + (tg - 37.0)
        if not on["pump"]: plate = min(plate, 55.0)      # 泵不转时底座降到待机温度(上限 60 ℃)
        T["humPlate"] = lag(T["humPlate"], plate if on["hum"] else AMB, 150 if on["hum"] else 600, dt)
        hum_goal = (tg - 5.0 if dry else tg + 1.0) if on["hum"] and T["humPlate"] > 45 else AMB + 4
        T["humOut"] = lag(T["humOut"], hum_goal, 120 if on["hum"] else 500, dt)
        T["gasEnd"] = lag(T["gasEnd"], (46.0 if self.fault("overtemp_gas") else tg) if on["tube"] else AMB + 6, 100 if on["tube"] else 400, dt)
        want = self.flow_want() if on["pump"] else 0.0
        self.flow = lag(self.flow, want, 3, dt)
        if self.flow > 0.5:      # 循环着:腹腔温度慢慢靠近送回来的气体温度
            tau = 900 * 10.0 / max(self.flow, 1.0)
            gas = max(T["gasEnd"], BODY - 0.3)   # 气体还没热起来时不把腹腔算凉
            T["ip1"] = lag(T["ip1"], gas - 0.2, tau, dt)
            T["ip2"] = lag(T["ip2"], gas - 0.6, tau, dt)
        else:                    # 不循环:慢慢回落到体温
            T["ip1"] = lag(T["ip1"], BODY, 3600, dt)
            T["ip2"] = lag(T["ip2"], BODY - 0.2, 3600, dt)
        self.ipOff = lag(self.ipOff, 1.0 if self.fault("ip_high") else 0.0, 25, dt)
        # 气腹:预热开始约 1 分钟后建立(模拟外科医生接好气腹机),进入排气阶段后放掉
        inflated = (self.ph == "PREHEAT" and self.phSec > 60) or self.ph in ("READY", "NEBULIZE", "EXPOSE")
        p = 0.0 if not inflated else 19.5 if self.fault("press_high") else 4.5 if self.fault("press_low") else 12.0
        self.pumpRun = self.pumpRun + dt if on["pump"] else 0.0
        self.press = lag(self.press, p, 8, dt)
        # 雾化气压大致和流量的平方成正比:12 L/min 时约 65 kPa
        np = 0.45 * self.flow ** 2 * (0.3 if self.fault("noz_low") else 1.0)
        if self.fault("noz_block") and on["pump"]: np = 185.0
        self.nozP = lag(self.nozP, np, 1.5, dt)

    def read(self):
        n = lambda: random.gauss(0, 0.03)
        T = self.T
        self.rd = {"syr1": T["syr"] + n(), "syr2": T["syr"] - 0.1 + n() + (2.5 if self.fault("sensor") else 0),
                   "noz1": T["noz"] + n(), "noz2": T["noz"] - 0.1 + n(),
                   "humPlate": T["humPlate"] + n(), "humOut": T["humOut"] + n(),
                   "gasEnd": None if self.fault("sensor_open") else T["gasEnd"] + n(),
                   "ip1": T["ip1"] + self.ipOff * max(0.0, 44.2 - T["ip1"]) + n(), "ip2": T["ip2"] + n()}

    def alarms(self, dt):
        r, al, tg = self.rd, self.al, self.target
        ge = lambda k, lim: r.get(k) is not None and r[k] >= lim
        if any(ge(k, 43.8) for k in ("syr1", "syr2", "noz1", "noz2")): al.add("OVERTEMP_DRUG")
        if ge("gasEnd", 44.5) or ge("humOut", 46.0) or ge("humPlate", 88.0): al.add("OVERTEMP_GAS")
        if ge("ip1", 43.5) or ge("ip2", 43.5): al.add("IP_HIGH")
        # 成对传感器不一致,或者控制用传感器断线:关掉对应的通路
        for ch, a, b in (("syr", "syr1", "syr2"), ("noz", "noz1", "noz2")):
            bad = r[a] is not None and r[b] is not None and abs(r[a] - r[b]) > 1.5
            if self.held("pair_" + ch, bad, dt) >= 10 or r[a] is None or r[b] is None:
                al.add("SENSOR"); self.sensorOff.add(ch)
        if r["humOut"] is None or r["humPlate"] is None: al.add("SENSOR"); self.sensorOff.add("hum")
        if r["gasEnd"] is None: al.add("SENSOR"); self.sensorOff.add("tube")
        if self.held("press_high", self.press >= 18.0, dt) >= 3: al.add("PRESS_HIGH")
        if self.held("press_low", self.on["pump"] and self.press <= 6.0, dt) >= 5: al.add("PRESS_LOW")
        water = self.pumpRun >= 120 and self.on["hum"] and ge("humPlate", 75.0) and r["humOut"] is not None and r["humOut"] < tg - 3.0
        if self.held("water", water, dt) >= 120: al.add("WATER_LOW")
        if self.held("noz_block", self.nozP >= 150.0, dt) >= 3: al.add("NOZ_BLOCK")
        weak = self.ph == "NEBULIZE" and self.pumpRun >= 10 and self.nozP < 30.0
        al.add("NOZ_LOW") if self.held("noz_low", weak, dt) >= 10 else al.discard("NOZ_LOW")
        al.add("PREHEAT_SLOW") if self.ph == "PREHEAT" and self.phSec > 3600 else al.discard("PREHEAT_SLOW")
        m = self.ip_mean()
        low = self.ph == "EXPOSE" and m is not None and m < tg - 2.0
        al.add("IP_LOW") if self.held("ip_low", low, dt) >= 300 else al.discard("IP_LOW")

    def phase_auto(self, dt):
        if self.ph == "PREHEAT":
            if self.heat_ok() and (self.ip_ok() or self.ipSkip): self.go("READY")
        elif self.ph == "READY":
            ok = self.heat_ok() and (self.ip_ok() or self.ipSkip)
            self.lost = 0.0 if ok else self.lost + dt
            if self.lost > 60: self.go("PREHEAT")
        elif self.ph == "EXPOSE":
            if self.phSec >= self.exposeMin * 60:
                self.al.add("EXPOSE_END")
                self.go("EVAC")

    def step(self, dt):
        self.now += dt
        self.phSec += dt
        self.muteLeft = max(0.0, self.muteLeft - dt)
        self.outputs()
        self.physics(dt)
        self.read()
        self.alarms(dt)
        self.phase_auto(dt)
        self.outputs()      # 报警或阶段刚变,输出立刻跟着变
        T, tg, on = self.T, self.target, self.on
        pid = lambda ch, cur, sp, hold: int(max(0, min(100, hold + (sp - cur) * 60))) if on[ch] else 0
        self.duty = {"syr": pid("syr", T["syr"], tg, 30), "noz": pid("noz", T["noz"], tg, 20),
                     "hum": pid("hum", T["humOut"], tg + 1, 55), "tube": pid("tube", T["gasEnd"], tg, 35),
                     "pump": int(round(self.flow_want() / 15.0 * 100)) if on["pump"] else 0}

    def telemetry(self):
        r1 = lambda v: None if v is None else round(v, 1)
        left = max(0, int(self.exposeMin * 60 - self.phSec)) if self.ph == "EXPOSE" else -1
        return {"id": self.id, "ph": self.ph, "target": self.target, "exposeMin": self.exposeMin, "flowSet": self.flowSet, "nebFlow": self.nebFlow,
                "circInExpose": self.circ, "t": {k: r1(v) for k, v in self.rd.items()},
                "press": round(max(0.0, self.press + random.gauss(0, 0.15)), 1),
                "nozP": round(max(0.0, self.nozP + (random.gauss(0, 0.5) if self.nozP > 1 else 0)), 1), "flow": round(max(0.0, self.flow + (random.gauss(0, 0.1) if self.flow > 0.3 else 0)), 1),
                "duty": self.duty, "phSec": int(self.phSec), "exposeLeft": left, "al": sorted(self.al), "muted": self.muteLeft > 0}


def post(server, body):
    req = urllib.request.Request(server + "/api/device/telemetry", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main():
    args, first, faults = [], 1, []
    it = iter(sys.argv[1:])
    for a in it:
        if a == "--fault": faults = parse_faults(next(it, ""))
        elif a == "--first": first = int(next(it, "1"))
        elif a in ("-h", "--help"): print(__doc__); return
        else: args.append(a)
    server = (args[0] if args else "http://127.0.0.1:8080").rstrip("/")
    n = int(args[1]) if len(args) > 1 else 1
    speed = float(args[2]) if len(args) > 2 else 1.0
    devs = [Device("HP-%03d" % (first + i), faults if i == 0 else ()) for i in range(n)]
    period = max(0.1, 2.0 / speed)        # 真实时间里多久上报一次
    dt = period * speed                   # 每次上报之间过去的设备时间
    print("模拟 %d 台设备(%s 起),加速 %g 倍,服务器 %s。按 Ctrl+C 停止。" % (n, devs[0].id, speed, server), flush=True)
    down = False
    while True:
        t0 = time.time()
        for d in devs:
            left = dt
            while left > 1e-9:            # 热模型每步不超过 1 秒
                h = min(1.0, left)
                d.step(h)
                left -= h
            try:
                resp = post(server, d.telemetry())
                if down: print("服务器恢复", flush=True)
                down = False
            except OSError as e:
                if not down: print("连不上服务器: %s,继续重试" % e, flush=True)
                down = True
                continue
            for c in resp.get("cmds", []):
                why = d.command(c)
                print("%s 命令 %s → %s" % (d.id, json.dumps(c, ensure_ascii=False), "拒绝:" + why if why else "执行,阶段 " + d.ph), flush=True)
        time.sleep(max(0.0, period - (time.time() - t0)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
