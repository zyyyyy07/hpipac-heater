#!/usr/bin/env python3
"""把装配视图导出成网页演示用的网格数据,并给 GitHub 导出可直接预览的 STL。
运行: python export_web.py
输出: ../../demo/models.js(演示页用)、../models/view/*.stl(GitHub 点开就能转动查看)
"""
import base64, json, os, struct
import cadquery as cq
import build as b

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.normpath(os.path.join(HERE, "..", "..", "demo"))
VIEW = os.path.normpath(os.path.join(HERE, "..", "models", "view"))

SCENES = [
    ("nozzle", "气助雾化喷头", b.nozzle_parts, 0.02, True),
    ("room", "手术室整体布置", b.full_assembly, 0.25, False),
    ("hum", "加湿加热底座", b.humidifier_parts, 0.08, False),
    ("syr", "注射筒加热套", lambda: b.syringe_jacket_parts(0), 0.08, False),
]


def mesh(shape, tol):
    verts, tris = shape.tessellate(tol, 0.3)
    v = [c for p in verts for c in (p.x, p.y, p.z)]
    t = [i for tr in tris for i in tr]
    return v, t


def pack(v, t):
    vb = base64.b64encode(struct.pack(f"<{len(v)}f", *v)).decode()
    fmt = "H" if len(v) // 3 < 65536 else "I"
    tb = base64.b64encode(struct.pack(f"<{len(t)}{fmt}", *t)).decode()
    return vb, tb, fmt == "I"


def main():
    os.makedirs(DEMO, exist_ok=True)
    os.makedirs(VIEW, exist_ok=True)
    out = {}
    for key, title, fn, tol, _ in SCENES:
        parts = []
        lo, hi = [1e9] * 3, [-1e9] * 3
        for name, kind, wp in fn():
            s = wp.val()
            bb = s.BoundingBox()
            lo = [min(lo[0], bb.xmin), min(lo[1], bb.ymin), min(lo[2], bb.zmin)]
            hi = [max(hi[0], bb.xmax), max(hi[1], bb.ymax), max(hi[2], bb.zmax)]
            v, t = mesh(s, tol)
            vb, tb, big = pack(v, t)
            parts.append({"n": name, "k": kind, "v": vb, "t": tb, "u32": big})
        out[key] = {"title": title, "lo": lo, "hi": hi, "parts": parts}
        # 给 GitHub 的 STL:把整组零件合成一个文件
        comp = cq.Compound.makeCompound([wp.val() for _, _, wp in fn()])
        cq.exporters.export(cq.Workplane().add(comp), os.path.join(VIEW, f"{key}_assembly.stl"), tolerance=max(tol, 0.05), angularTolerance=0.3)
        print(key, len(parts), "parts")
    js = "window.HP_MODELS=" + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n"
    with open(os.path.join(DEMO, "models.js"), "w", encoding="utf-8") as f:
        f.write(js)
    print("models.js", len(js) // 1024, "KB")


if __name__ == "__main__":
    main()
