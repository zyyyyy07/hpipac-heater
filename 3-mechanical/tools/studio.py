#!/usr/bin/env python3
"""三维查看器:在浏览器里旋转查看每个零件,改尺寸后立即重新生成,满意后保存并导出 STEP/STL。
依赖: pip install cadquery reportlab ezdxf       运行: python studio.py       然后打开 http://127.0.0.1:8095
"""
import json, os, sys, threading, traceback
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import cadquery as cq
import build as b

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8095"))
lock = threading.Lock()          # CadQuery 不是线程安全的,一次只算一个


def mesh(name, params):
    b.apply(params)
    fn, how, title = {**b.BUILDERS, **b.VIEW_ONLY}[name]
    res = fn()
    items = res if isinstance(res, list) else [(title, "AL" if how == "CNC" else "PRINT" if how == "PRINT" else "AL", res)]
    parts, lo, hi, vol, valid = [], [1e9] * 3, [-1e9] * 3, 0.0, True
    for pname, kind, wp in items:
        shape = wp.val()
        verts, tris = shape.tessellate(0.06 if len(items) == 1 else 0.12, 0.25)
        bb = shape.BoundingBox()
        lo = [min(lo[0], bb.xmin), min(lo[1], bb.ymin), min(lo[2], bb.zmin)]
        hi = [max(hi[0], bb.xmax), max(hi[1], bb.ymax), max(hi[2], bb.zmax)]
        vol += shape.Volume(); valid = valid and shape.isValid()
        parts.append({"name": pname, "kind": kind, "v": [round(c, 3) for v in verts for c in (v.x, v.y, v.z)], "t": [i for t in tris for i in t]})
    info = {"gas_area": b.GAS_AREA}
    return {"parts": parts, "size": [round(h - l, 1) for l, h in zip(lo, hi)], "center": [(l + h) / 2 for l, h in zip(lo, hi)],
            "volume": round(vol / 1000, 1), "valid": valid, "how": how, "title": title, "multi": len(items) > 1, "info": info}


def save(params):
    p = b.apply(params)
    with open(b.PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)
    lines = []
    b.export_all(lines.append)
    try:
        import drawings
        drawings.write_all(lambda s: None)
        lines.append("图纸包已更新: ../drawings/HP-drawings.pdf 和 ../drawings/dxf/")
    except Exception as e:                      # 图纸生成失败不影响模型导出
        lines.append(f"加工图未更新: {e}")
    return {"ok": True, "log": lines, "out": "3-mechanical/models 和 3-mechanical/drawings"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/":
            return self.send(200, open(os.path.join(HERE, "studio.html"), "rb").read(), "text/html; charset=utf-8")
        if p.startswith("/vendor/") and p.endswith(".js") and "/" not in p[8:] and ".." not in p:
            return self.send(200, open(os.path.join(HERE, "vendor", p[8:]), "rb").read(), "application/javascript")
        if p == "/api/meta":
            parts = [{"id": k, "title": v[2], "how": v[1]} for k, v in {**b.BUILDERS, **b.VIEW_ONLY}.items()]
            params = [{"key": k, "label": lab, "def": d, "min": lo, "max": hi, "step": st, "group": g} for k, lab, d, lo, hi, st, g in b.PARAMS]
            return self.send(200, {"parts": parts, "params": params, "values": {**b.DEFAULTS, **b.load_params()}})
        self.send(404, {"err": "not found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            with lock:
                if self.path == "/api/mesh":
                    return self.send(200, mesh(body["part"], body.get("params")))
                if self.path == "/api/save":
                    return self.send(200, save(body.get("params")))
            self.send(404, {"err": "not found"})
        except ValueError as e:
            self.send(400, {"err": str(e)})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"err": f"这组尺寸生成失败: {type(e).__name__}: {e}"})


if __name__ == "__main__":
    print(f"三维查看器已启动: http://127.0.0.1:{PORT}", flush=True)
    try:
        ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
