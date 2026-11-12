#!/usr/bin/env python3
"""设备模拟器:没有硬件时用它测试服务器和三个页面。
用法: python simulator.py [服务器地址] [设备数] [加速倍数]
例:   python simulator.py http://127.0.0.1:8080 3 20
模拟的是固件的对外行为(状态机、滴空截停、报警),不是真实的热学过程。
"""
import json, math, random, sys, time, urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3
SPEED = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
UA, AMB = 0.96, 22.0


class Dev:
    def __init__(self, i):
        self.id = f"IW-{i:03d}"
        self.st, self.task = "IDLE", None
        self.tp = AMB; self.ts = 0.0; self.fs = 0.0; self.df = 20
        self.vol = self.rem = 0.0; self.roller = 1.0
        self.al = set(); self.bat = random.randint(60, 100); self.nodrop = 0.0

    def flow(self):
        return self.fs * self.roller if self.st == "RUN" and self.rem > 0 else 0.0

    def step(self, dt):
        fl = self.flow()
        if self.st in ("READY", "RUN", "PAUSE") and self.ts:
            mc = fl / 3600 * 4.18
            want = self.ts if mc < 0.005 else min(41.0, max(self.ts, (self.ts - AMB * math.exp(-UA / mc)) / (1 - math.exp(-UA / mc))))
            self.tp += (want - self.tp) * min(1.0, dt / 60)
        else:
            self.tp += (AMB - self.tp) * min(1.0, dt / 300)
        if self.st == "RUN":
            self.rem = max(0.0, self.rem - fl * dt / 3600)
            self.nodrop = self.nodrop + dt if fl < 1 else 0.0
            self.al.discard("LOWVOL")
            if self.rem <= max(10.0, 0.05 * self.vol):
                self.al.add("LOWVOL")
            if self.rem <= 0.5 and self.nodrop >= 20:      # 滴空:无液滴 + 余量低 → 截停
                self.st = "DONE"; self.al = {"EMPTY"}

    def est_out(self):
        fl = self.flow(); mc = fl / 3600 * 4.18
        if not self.ts:
            return AMB
        return self.tp if mc < 0.005 else AMB + (self.tp - AMB) * (1 - math.exp(-UA / mc)) * math.exp(-0.01 / mc)

    def on_cmd(self, c):
        k = c["c"]
        if k == "start" and self.st in ("IDLE", "READY"):
            self.task, self.vol, self.rem = c["task"], c["vol"], c["vol"]
            self.fs, self.ts, self.df = c["rate"], c["temp"], c["df"]
            self.roller = random.uniform(0.93, 1.05); self.st = "RUN"; self.al.clear(); self.nodrop = 0
        elif k == "pause" and self.st == "RUN":
            self.st = "PAUSE"
        elif k == "resume" and self.st == "PAUSE":
            self.st = "RUN"; self.nodrop = 0
        elif k == "rate":
            self.fs = c["v"]
        elif k == "temp":
            self.ts = c["v"]
        elif k == "finish" and self.st == "DONE":
            self.st, self.task = "IDLE", None; self.al.clear(); self.ts = 0
        # mute:只影响蜂鸣器,模拟器忽略

    def telemetry(self):
        fl = self.flow()
        return {"id": self.id, "st": self.st, "task": self.task, "tp": round(self.tp, 2), "to": round(self.est_out(), 2),
                "ts": self.ts, "fl": round(fl, 1), "fs": self.fs, "dpm": round(fl * self.df / 60, 1),
                "w": round(self.rem + 35, 1), "rem": round(self.rem, 1), "eta": round(self.rem / fl * 60, 1) if fl > 1 else -1,
                "al": sorted(self.al), "bat": self.bat, "clamp": 1 if self.st == "RUN" else 0}

    def sync(self):
        req = urllib.request.Request(URL + "/api/device/telemetry", json.dumps(self.telemetry()).encode(),
                                     {"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(req, timeout=3).read())
        for c in r["cmds"]:
            self.on_cmd(c)
        t = r.get("task")
        if t and self.st == "IDLE":
            self.st, self.ts = "READY", t["temp"]      # 收到任务:开始预热
        elif not t and self.st == "READY":
            self.st, self.ts = "IDLE", 0               # 任务被取消


if __name__ == "__main__":
    devs = [Dev(i + 1) for i in range(N)]
    print(f"模拟 {N} 台设备 → {URL},时间加速 {SPEED:g} 倍。Ctrl+C 退出。")
    while True:
        for d in devs:
            d.step(1.0 * SPEED)
            try:
                d.sync()
            except Exception as e:
                print(d.id, "上报失败:", e)
        time.sleep(1.0)
