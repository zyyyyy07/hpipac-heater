#!/usr/bin/env python3
"""生成发给加工厂的图纸包:每个零件一张 A3 工程图(PDF)和一份 1:1 的 DXF。尺寸取自 build.py 的当前参数。
依赖: pip install cadquery reportlab ezdxf
运行: python drawings.py
输出: drawings/IW-drawings.pdf(8 页)、drawings/dxf/*.dxf。三维模型在 out/*.step。
图纸采用第一角画法,单位 mm。坐标原点是零件外形的最小角(俯视图、主视图的左下角)。
"""
import datetime, math, os
import cadquery as cq
import build as b
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepLib import BRepLib
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

HERE = os.path.dirname(os.path.abspath(__file__))
DR = os.path.join(HERE, "drawings")
PDF = os.path.join(DR, "IW-drawings.pdf")
DXF = os.path.join(DR, "dxf")
REV = "v0.1"
PROJECT = "输液加温监控一体机 样机"

# 视图:名称 -> (朝向观察者的方向, 图上水平方向, 图上竖直方向)
VIEWS = {
    "front": ((0, -1, 0), (1, 0, 0), (0, 0, 1)),     # 主视图:从前面看
    "top": ((0, 0, 1), (1, 0, 0), (0, 1, 0)),        # 俯视图:从上面看
    "left": ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),     # 左视图:从左面看
}
ISO_N = (1 / math.sqrt(3), -1 / math.sqrt(3), 1 / math.sqrt(3))
ISO_X = (1 / math.sqrt(2), 1 / math.sqrt(2), 0)
VIEW_NAME = {"front": "主视图", "top": "俯视图", "left": "左视图"}
AXIS_VIEW = {2: "top", 1: "front", 0: "left"}          # 孔轴方向 -> 标注所在视图
AXIS_LETTER = {2: "A", 1: "B", 0: "C"}
fmt = lambda v: f"{round(v, 2):g}"

PRINT_NOTES = ["材料 PETG,3D 打印(FDM),层高 0.2。", "未注尺寸以同名 STEP 模型为准,未注公差 ±0.3。",
               "外观面无拉丝、无翘曲,支撑清理干净。"]


def specs():
    """每个零件的图号、材料、技术要求和孔的说明。写成函数是因为内容随当前参数变化。"""
    half = math.sqrt(b.GROOVE_R ** 2 - (b.GROOVE_R - b.GROOVE_DEPTH) ** 2)
    plate_notes = lambda upper: [
        "材料 6061-T6 铝合金,数控铣削。",
        "未注尺寸以同名 STEP 模型为准,未注公差 ±0.1。",
        "槽面(合模面)平面度 0.05,槽内粗糙度 Ra≤1.6。",
        "槽中心线位置度 0.1,上下板合模后槽须对齐。",
        "锐边倒钝 C0.3,槽口倒角 C0.2 去毛刺。",
        "样机不做表面处理;成品做硬质阳极氧化。",
        "上板与下板为镜像件,不可互换。"]
    groove = lambda upper: [
        f"管槽:R{fmt(b.GROOVE_R)} 球头刀沿中心线铣削,槽深 {fmt(b.GROOVE_DEPTH)}(+0.05/0),槽口宽 {half * 2:.2f},中心线全长 {b.groove_length():.0f}。",
        "中心线:三条直槽 y = " + "、".join(fmt(b.PW - v if upper else v) for v in b.RUN_Y)
        + f";两个半圆弯 R{fmt(b.BEND_R)},圆心 x = {fmt(b.PL - b.TURN_X)} 和 {fmt(b.TURN_X)}。两端直槽通到板边。",
        f"测温孔自 y=0 长边钻入,孔中心距槽面 {fmt(b.PT - b.NTC_Z)}(槽底与背面正中)。"]
    return {
        "01_plate_lower_AL6061": dict(no="IW-01", mat="6061-T6", notes=plate_notes(False), extra=groove(False), plate=False,
                                      holes={2.5: "攻 M3 螺纹", 3.0: "φ3 H7 定位销孔", 2.2: "测温孔"}),
        "02_plate_upper_AL6061": dict(no="IW-02", mat="6061-T6", notes=plate_notes(True), extra=groove(True), plate=True,
                                      holes={3.4: "M3 过孔", 3.0: "φ3 H7 定位销孔", 2.2: "测温孔"}),
        "03_heater_shell_lower": dict(no="IW-03", mat="PETG", notes=PRINT_NOTES + ["填充 30%。腔内放保温垫和下铝板。"],
                                      extra=["壳口两端的缺口是进出管口;长边中部 8×5 开口走加热片和测温线。"]),
        "04_heater_shell_upper": dict(no="IW-04", mat="PETG", notes=PRINT_NOTES + ["填充 30%。腔内放保温垫和上铝板。"],
                                      holes={7.0: "夹紧螺丝操作孔"}, extra=["壳口两端的缺口是进出管口,与下壳缺口对齐。"]),
        "05_drip_sensor_clip": dict(no="IW-05", mat="PETG 黑色", notes=PRINT_NOTES + ["填充 30%。必须用黑色或不透光材料。"],
                                    holes={5.2: "5 mm 红外对管安装孔,发射与接收同轴", 3.4: "M3 安装孔"},
                                    extra=[f"中间 φ{fmt(b.DRIP_D)} 圆孔卡滴斗,前方开口宽 {fmt(b.DRIP_D - 3.5)},滴斗从开口压入。"]),
        "06_loadcell_mount": dict(no="IW-06", mat="PETG", notes=PRINT_NOTES + ["填充 100%(受力件)。也可用 6061 铝加工。"],
                                  holes={5.4: "M5 过孔,固定条形称重传感器", 4.4: "M4 过孔,固定到横臂"},
                                  extra=["凸台高 2:称重传感器固定端垫高,另一端悬空受力。"]),
        "07_control_box_body": dict(no="IW-07", mat="PETG", notes=PRINT_NOTES + ["填充 30%。开口朝上打印。"],
                                    holes={2.6: "M3 自攻螺丝底孔(四角螺丝柱)", 8.2: "DC 电源座", 16.2: "GX16 航空插座(加温线)",
                                           12.2: "GX12 航空插座(滴斗、称重、夹管阀)"}),
        "08_control_box_lid": dict(no="IW-08", mat="PETG", notes=PRINT_NOTES + ["填充 30%。外表面朝下打印。"],
                                   holes={3.4: "M3 过孔", 5.2: "φ5 指示灯(红、黄、绿)", 16.2: "暂停键 φ16", 12.2: "消音键 φ12",
                                          12.0: "蜂鸣器出声孔"},
                                   extra=["矩形窗口 27×15 为 0.96 英寸 OLED 显示窗。"]),
    }


# ---------------- 几何:投影、孔识别 ----------------
def _dot(a, c):
    return a[0] * c[0] + a[1] * c[1] + a[2] * c[2]


def project(shape, n, vx):
    """隐藏线消除投影。返回 (可见线, 隐藏线),每条线是 [(u, v), ...]。"""
    hlr = HLRBRep_Algo()
    hlr.Add(shape.wrapped)
    hlr.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*n), gp_Dir(*vx))))
    hlr.Update(); hlr.Hide()
    hs = HLRBRep_HLRToShape(hlr)

    def edges(comp):
        out = []
        if comp is None or comp.IsNull():
            return out
        BRepLib.BuildCurves3d_s(comp)
        ex = TopExp_Explorer(comp, TopAbs_EDGE)
        while ex.More():
            d = GCPnts_QuasiUniformDeflection(BRepAdaptor_Curve(TopoDS.Edge_s(ex.Current())), 0.02)
            if d.IsDone() and d.NbPoints() > 1:
                out.append([(d.Value(i).X(), d.Value(i).Y()) for i in range(1, d.NbPoints() + 1)])
            ex.Next()
        return out

    vis = edges(hs.VCompound()) + edges(hs.Rg1LineVCompound()) + edges(hs.OutLineVCompound())
    hid = edges(hs.HCompound()) + edges(hs.OutLineHCompound())
    return vis, hid


def find_holes(solid, lo, hi):
    """找出轴线平行于坐标轴的整圆孔。返回 [dict(axis, d, pos, depth, thru)],pos 为相对原点 lo 的坐标。"""
    groups = {}
    for f in solid.Faces():
        if f.geomType() != "CYLINDER":
            continue
        s = BRepAdaptor_Surface(f.wrapped)
        cyl = s.Cylinder(); ax = cyl.Axis(); dv = ax.Direction(); loc = ax.Location()
        d = (dv.X(), dv.Y(), dv.Z())
        k = max(range(3), key=lambda i: abs(d[i]))
        if abs(d[k]) < 0.9999:
            continue
        u = (s.FirstUParameter() + s.LastUParameter()) / 2
        v0, v1 = s.FirstVParameter(), s.LastVParameter()
        p = s.Value(u, (v0 + v1) / 2)
        pt = (p.X(), p.Y(), p.Z()); lc = (loc.X(), loc.Y(), loc.Z())
        nrm = f.normalAt(cq.Vector(*pt)); nrm = (nrm.x, nrm.y, nrm.z)
        t = _dot([pt[i] - lc[i] for i in range(3)], d)
        radial = [pt[i] - lc[i] - d[i] * t for i in range(3)]
        if _dot(nrm, radial) > 0:                    # 外圆柱(凸台、圆角),不是孔
            continue
        a0, a1 = sorted((lc[k] + d[k] * v0, lc[k] + d[k] * v1))
        key = (k, tuple(round(lc[i], 2) for i in range(3) if i != k), round(cyl.Radius(), 3))
        g = groups.setdefault(key, [0.0, []])
        g[0] += s.LastUParameter() - s.FirstUParameter()
        g[1].append((a0, a1))
    holes = []
    for (k, pos, r), (span, ivs) in groups.items():
        if span < 2 * math.pi - 0.01:               # 不是整圆(如被开口切开的滴斗孔)
            continue
        a0, a1 = min(i[0] for i in ivs), max(i[1] for i in ivs)
        others = [i for i in range(3) if i != k]
        def outside(a):                               # 轴线上这一点是否在材料之外
            q = [0.0, 0.0, 0.0]; q[k] = a; q[others[0]], q[others[1]] = pos
            return not solid.isInside(cq.Vector(*q), 1e-4)
        holes.append(dict(axis=k, d=round(2 * r, 2), pos=tuple(pos[j] - lo[others[j]] for j in range(2)),
                          depth=a1 - a0, thru=outside(a0 - 0.05) and outside(a1 + 0.05), a0=a0 - lo[k]))
    holes.sort(key=lambda h: (-h["axis"], h["d"], h["pos"]))
    return holes


def hole_table(holes, remarks):
    """把相同方向、直径、深度的孔合并成一行。返回 [dict(label, n, d, depth, view, coords, remark, items)]。"""
    rows, count = [], {}
    for h in holes:
        key = (h["axis"], h["d"], h["thru"], round(h["depth"], 1))
        row = next((r for r in rows if r["key"] == key), None)
        if row is None:
            count[h["axis"]] = count.get(h["axis"], 0) + 1
            row = dict(key=key, label=f"{AXIS_LETTER[h['axis']]}{count[h['axis']]}", d=h["d"], axis=h["axis"],
                       depth="通孔" if h["thru"] else f"深 {fmt(h['depth'])}", view=VIEW_NAME[AXIS_VIEW[h["axis"]]],
                       remark=remarks.get(h["d"], ""), items=[])
            rows.append(row)
        row["items"].append(h)
    for r in rows:
        r["n"] = len(r["items"])
        r["coords"] = " ".join(f"({fmt(h['pos'][0])},{fmt(h['pos'][1])})" for h in r["items"])
    return rows


def model(name):
    """一个零件出图所需的全部数据。"""
    fn, how, title = b.BUILDERS[name]
    solid = fn().val()
    bb = solid.BoundingBox()
    lo, hi = (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax)
    sp = specs()[name]
    views = {}
    for v, (n, vx, vy) in VIEWS.items():
        vis, hid = project(solid, n, vx)
        corners = [(_dot(c, vx), _dot(c, vy)) for c in ((x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2]))]
        u0, v0 = min(c[0] for c in corners), min(c[1] for c in corners)
        w, h = max(c[0] for c in corners) - u0, max(c[1] for c in corners) - v0
        views[v] = dict(vis=vis, hid=hid, u0=u0, v0=v0, w=w, h=h)
    iso_vis, _ = project(solid, ISO_N, ISO_X)
    holes = find_holes(solid, lo, hi)
    return dict(name=name, title=title, how=how, sp=sp, size=[hi[i] - lo[i] for i in range(3)], lo=lo, hi=hi,
                views=views, iso=iso_vis, holes=holes, rows=hole_table(holes, sp.get("holes", {})))


def hole_uv(m, h, view):
    """孔中心在所属视图里的图上坐标(相对视图左下角,毫米,未乘比例)。"""
    k = h["axis"]; others = [i for i in range(3) if i != k]
    p = [0.0, 0.0, 0.0]
    p[others[0]] = h["pos"][0] + m["lo"][others[0]]; p[others[1]] = h["pos"][1] + m["lo"][others[1]]
    _, vx, vy = VIEWS[view]
    return _dot(p, vx) - m["views"][view]["u0"], _dot(p, vy) - m["views"][view]["v0"]


# ---------------- PDF ----------------
def _font():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    if "CJK" in pdfmetrics.getRegisteredFontNames():
        return "CJK"
    cands = [(r"C:\Windows\Fonts\simhei.ttf", None), (r"C:\Windows\Fonts\msyh.ttc", 0), ("/System/Library/Fonts/PingFang.ttc", 0),
             ("/System/Library/Fonts/STHeiti Medium.ttc", 0), ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
             ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0)]
    for path, idx in cands:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("CJK", path) if idx is None else TTFont("CJK", path, subfontIndex=idx))
                return "CJK"
            except Exception:
                continue
    raise RuntimeError("找不到中文字体(黑体或微软雅黑),无法生成 PDF 图纸")


class Sheet:
    """一张 A3 横向图纸。坐标单位 mm,原点在左下角。"""
    W, H = 420.0, 297.0

    def __init__(self, c, font):
        self.c, self.f = c, font

    def line(self, x1, y1, x2, y2, w=0.18, dash=None):
        c = self.c; c.setLineWidth(w); c.setDash(dash or [])
        c.line(x1, y1, x2, y2)

    def poly(self, pts, w, dash=None):
        c = self.c; c.setLineWidth(w); c.setDash(dash or [])
        p = c.beginPath(); p.moveTo(*pts[0])
        for q in pts[1:]:
            p.lineTo(*q)
        c.drawPath(p, stroke=1, fill=0)

    def text(self, x, y, s, size=2.8, anchor="l", rot=0):
        c = self.c; c.saveState(); c.translate(x, y); c.rotate(rot); c.setFont(self.f, size)
        {"l": c.drawString, "m": c.drawCentredString, "r": c.drawRightString}[anchor](0, 0, s); c.restoreState()

    def width(self, s, size=2.8):
        return self.c.stringWidth(s, self.f, size)

    def arrow(self, x, y, ang):
        c = self.c; c.saveState(); c.translate(x, y); c.rotate(ang); c.setDash([])
        p = c.beginPath(); p.moveTo(0, 0); p.lineTo(-2.2, 0.4); p.lineTo(-2.2, -0.4); p.close()
        c.drawPath(p, stroke=0, fill=1); c.restoreState()

    def hdim(self, x1, x2, y, off, s):
        yy = y + off; sg = 1 if off > 0 else -1
        self.line(x1, y + sg, x1, yy + sg * 1.5); self.line(x2, y + sg, x2, yy + sg * 1.5); self.line(x1, yy, x2, yy)
        self.arrow(x1, yy, 180); self.arrow(x2, yy, 0); self.text((x1 + x2) / 2, yy + 0.8, s, 2.8, "m")

    def vdim(self, y1, y2, x, off, s):
        xx = x + off; sg = 1 if off > 0 else -1
        self.line(x + sg, y1, xx + sg * 1.5, y1); self.line(x + sg, y2, xx + sg * 1.5, y2); self.line(xx, y1, xx, y2)
        self.arrow(xx, y1, 270); self.arrow(xx, y2, 90); self.text(xx - 0.8, (y1 + y2) / 2, s, 2.8, "m", 90)

    def view(self, v, x0, y0, s, hidden=True):
        if hidden:
            for pl in v["hid"]:
                self.poly([(x0 + (u - v["u0"]) * s, y0 + (w - v["v0"]) * s) for u, w in pl], 0.13, [1.2, 0.8])
        for pl in v["vis"]:
            self.poly([(x0 + (u - v["u0"]) * s, y0 + (w - v["v0"]) * s) for u, w in pl], 0.35)


def _ordinates(sh, vals, at, base, horizontal):
    """坐标式尺寸:沿视图一条边标出各特征到原点的距离。相邻太近的错开成两层。"""
    last = [-1e9, -1e9]
    for val in sorted(set(round(v, 2) for v in vals)):
        p = at(val)
        lvl = 0 if p - last[0] >= 6.5 else 1
        if lvl == 1 and p - last[1] < 6.5:
            continue                                   # 两层都放不下,这个值只在孔表里给出
        last[lvl] = p
        d = 4 + lvl * 4.5
        if horizontal:
            sh.line(p, base - 1, p, base - d); sh.text(p, base - d - 3, fmt(val), 2.5, "m")
        else:
            sh.line(base - 1, p, base - d, p); sh.text(base - d - 0.8, p - 0.9, fmt(val), 2.5, "r")


def draw_sheet(sh, m, page, pages):
    c = sh.c; sp = m["sp"]; X, Y, Z = m["size"]
    c.setStrokeColorRGB(0, 0, 0); c.setFillColorRGB(0, 0, 0)
    c.setLineWidth(0.5); c.setDash([]); c.rect(10, 10, 400, 277)
    # 比例
    scale = next(s for s in (5, 2, 1, 0.5, 0.25, 0.2, 0.1) if s * (X + Y) <= 340 and s * (Z + Y) <= 125)
    gap, x0, ytop = 26.0, 36.0, 267.0
    fx, fy = x0, ytop - Z * scale                      # 主视图左下角
    tx, ty = x0, fy - gap - Y * scale                  # 俯视图
    lx, ly = x0 + X * scale + gap, fy                  # 左视图
    pos = {"front": (fx, fy), "top": (tx, ty), "left": (lx, ly)}
    for v in ("front", "top", "left"):
        sh.view(m["views"][v], *pos[v], scale)
    sh.text(fx, ytop + 12.5, "主视图", 3.2); sh.text(lx, ytop + 12.5, "左视图", 3.2); sh.text(tx, ty - 18, "俯视图", 3.2)
    # 总体尺寸
    sh.hdim(fx, fx + X * scale, ytop, 7, fmt(X)); sh.vdim(fy, ytop, fx, -7, fmt(Z))
    sh.hdim(lx, lx + Y * scale, ytop, 7, fmt(Y)); sh.vdim(ty, ty + Y * scale, tx + X * scale, 8, fmt(Y))
    # 孔:中心线、标记
    for r in m["rows"]:
        view = AXIS_VIEW[r["axis"]]; vx0, vy0 = pos[view]
        for h in r["items"]:
            u, w = hole_uv(m, h, view); px, py = vx0 + u * scale, vy0 + w * scale; rr = h["d"] / 2 * scale + 1.2
            sh.line(px - rr, py, px + rr, py, 0.13, [3, 0.8, 0.6, 0.8]); sh.line(px, py - rr, px, py + rr, 0.13, [3, 0.8, 0.6, 0.8])
            sh.text(px + rr * 0.72 + 0.3, py + rr * 0.72, r["label"], 2.3)
    # 俯视图坐标式尺寸
    zh = [h for h in m["holes"] if h["axis"] == 2]
    xs = [0, X] + [h["pos"][0] for h in zh] + sp.get("ord_x", [])
    ys = [0, Y] + [h["pos"][1] for h in zh] + sp.get("ord_y", [])
    if "plate" in sp:
        xs += [b.TURN_X, b.PL - b.TURN_X] + list(b.NTC_X if not sp["plate"] else b.NTC_X[:1])
        ys += [(b.PW - v) if sp["plate"] else v for v in b.RUN_Y]
    _ordinates(sh, xs, lambda v: tx + v * scale, ty, True)
    _ordinates(sh, ys, lambda v: ty + v * scale, tx, False)
    # 右上:铝板画槽截面详图,其余画轴测图
    rx = lx + Y * scale + 14
    if "plate" in sp and 400 - rx >= 60:
        _groove_detail(sh, rx, 205)
    elif 400 - rx >= 45 and m["iso"]:
        us = [p[0] for pl in m["iso"] for p in pl]; vs = [p[1] for pl in m["iso"] for p in pl]
        s2 = min((400 - rx) / (max(us) - min(us)), 95 / (max(vs) - min(vs)), scale)
        oy = 272 - (max(vs) - min(vs)) * s2
        for pl in m["iso"]:
            sh.poly([(rx + (u - min(us)) * s2, oy + (w - min(vs)) * s2) for u, w in pl], 0.2)
        sh.text(rx, oy - 5, "轴测图(示意,不按比例)", 2.5)
    # 下方:孔表
    c.setLineWidth(0.5); c.setDash([]); c.line(10, 96, 410, 96); c.line(272, 10, 272, 96)
    cols = [(12, "标记"), (24, "数量"), (36, "直径"), (52, "深度"), (68, "标注视图"), (88, "中心坐标(横,竖)"), (176, "用途")]
    y = 90
    sh.text(12, y, "孔表", 3.2); sh.text(30, y, "坐标原点:零件外形最小角,即俯视图和主视图的左下角。B 类孔坐标为 (x,z),C 类孔为 (y,z)。", 2.5)
    y -= 5.5
    for xx, t in cols:
        sh.text(xx, y, t, 2.6)
    sh.line(12, y - 1.3, 270, y - 1.3, 0.18)
    for r in m["rows"]:
        coords = r["coords"]; lines = []
        while sh.width(coords, 2.5) > 86 and " " in coords:           # 坐标太长时换行
            cut = coords.rfind(" ", 0, max(1, int(len(coords) * 86 / sh.width(coords, 2.5))))
            if cut <= 0:
                break
            lines.append(coords[:cut]); coords = coords[cut + 1:]
        lines.append(coords)
        y -= 4.6
        for xx, t in zip([q[0] for q in cols], [r["label"], str(r["n"]), "φ" + fmt(r["d"]), r["depth"], r["view"], lines[0], r["remark"]]):
            sh.text(xx, y, t, 2.5)
        for extra in lines[1:]:
            y -= 4.0; sh.text(88, y, extra, 2.5)
    if not m["rows"]:
        y -= 4.6; sh.text(12, y, "本零件没有整圆孔,开口和缺口以 STEP 模型为准。", 2.5)
    y -= 2.5
    for t in sp.get("extra", []):
        y -= 4.4; sh.text(12, y, t, 2.5)
    # 右下:技术要求、标题栏
    y = 90; sh.text(275, y, "技术要求", 3.2)
    for i, t in enumerate(sp["notes"]):
        y -= 4.5; sh.text(275, y, f"{i + 1}. {t}", 2.5)
    c.setLineWidth(0.5); c.line(272, 50, 410, 50)
    c.setLineWidth(0.25)
    for yy in (40, 30, 20):
        c.line(272, yy, 410, yy)
    for xx, ya, yb in ((341, 10, 40), (300, 10, 20), (369, 10, 20)):
        c.line(xx, ya, xx, yb)
    sh.text(275, 43, m["title"], 4.2); sh.text(407, 43, sp["no"], 4.2, "r")
    sh.text(275, 33, f"材料  {sp['mat']}", 2.8); sh.text(344, 33, f"数量  1      比例  {'%g:1' % scale if scale >= 1 else '1:%g' % (1 / scale)}", 2.8)
    sh.text(275, 23, f"外形  {fmt(X)} × {fmt(Y)} × {fmt(Z)}", 2.8); sh.text(344, 23, "单位 mm    第一角画法", 2.8)
    sh.text(275, 13, f"版本 {REV}", 2.6); sh.text(303, 13, datetime.date.today().isoformat(), 2.6)
    sh.text(344, 13, f"第 {page}/{pages} 张", 2.6); sh.text(372, 13, PROJECT, 2.3)
    sh.text(12, 289, f"三维模型:out/{m['name']}.step        二维:drawings/dxf/{m['name']}.dxf", 2.4)


def _groove_detail(sh, x, y):
    """铝板槽截面详图 5:1。(x, y) 为截面左下角。"""
    k, w = 5.0, 12.0
    half = math.sqrt(b.GROOVE_R ** 2 - (b.GROOVE_R - b.GROOVE_DEPTH) ** 2)
    top, cx = y + b.PT * k, x + w * k / 2
    cz = top + (b.GROOVE_R - b.GROOVE_DEPTH) * k
    a0, a1 = math.atan2(top - cz, -half * k), math.atan2(top - cz, half * k)
    arc = [(cx + b.GROOVE_R * k * math.cos(a0 + i * (a1 - a0) / 40), cz + b.GROOVE_R * k * math.sin(a0 + i * (a1 - a0) / 40)) for i in range(41)]
    sh.poly([(x, top)] + arc + [(x + w * k, top), (x + w * k, y), (x, y), (x, top)], 0.35)
    ny = y + b.NTC_Z * k
    c = sh.c; c.setLineWidth(0.18); c.setDash([1.2, 0.8]); c.circle(cx, ny, 1.1 * k, stroke=1, fill=0); c.setDash([])
    sh.vdim(y, top, x, -6, fmt(b.PT))
    sh.vdim(top - b.GROOVE_DEPTH * k, top, x + w * k, 6, fmt(b.GROOVE_DEPTH))
    sh.hdim(cx - half * k, cx + half * k, top, 6, f"{half * 2:.2f}")
    sh.text(x, top + 16, "槽截面详图 5:1", 3.2)
    sh.text(x, y - 6, f"R{fmt(b.GROOVE_R)} 球头刀,槽深 {fmt(b.GROOVE_DEPTH)} (+0.05/0)", 2.5)
    sh.text(x, y - 10.5, f"虚线圆:测温孔 φ2.2,中心距背面 {fmt(b.NTC_Z)}", 2.5)


# ---------------- DXF ----------------
def write_dxf(m, path):
    import ezdxf
    doc = ezdxf.new("R2010", setup=True); doc.units = 4          # 毫米
    doc.layers.add("VISIBLE", color=7); doc.layers.add("HIDDEN", color=8, linetype="DASHED"); doc.layers.add("TEXT", color=3)
    msp = doc.modelspace(); X, Y, Z = m["size"]; gap = 30
    pos = {"front": (0, Y + gap), "top": (0, 0), "left": (X + gap, Y + gap)}
    for v, (ox, oy) in pos.items():
        vw = m["views"][v]
        for layer, key in (("VISIBLE", "vis"), ("HIDDEN", "hid")):
            for pl in vw[key]:
                msp.add_lwpolyline([(ox + u - vw["u0"], oy + w - vw["v0"]) for u, w in pl], dxfattribs={"layer": layer})
        msp.add_text({"front": "FRONT", "top": "TOP", "left": "LEFT"}[v], height=3, dxfattribs={"layer": "TEXT"}).set_placement((ox, oy - 6))
    msp.add_text(f"{m['sp']['no']} {m['name']}  1:1  mm  first-angle  {REV}", height=3, dxfattribs={"layer": "TEXT"}).set_placement((0, -16))
    doc.saveas(path)


def write_all(log=print):
    """按当前参数重新生成整套图纸。返回 PDF 路径。"""
    from reportlab.pdfgen import canvas
    os.makedirs(DXF, exist_ok=True)
    font = _font()
    c = canvas.Canvas(PDF, pagesize=(Sheet.W * 72 / 25.4, Sheet.H * 72 / 25.4))
    c.setTitle(f"{PROJECT} 零件图纸 {REV}"); c.setAuthor(""); c.setCreator("drawings.py")
    names = list(b.BUILDERS)
    for i, name in enumerate(names):
        m = model(name)
        c.saveState(); c.scale(72 / 25.4, 72 / 25.4)
        draw_sheet(Sheet(c, font), m, i + 1, len(names))
        c.restoreState(); c.showPage()
        write_dxf(m, os.path.join(DXF, name + ".dxf"))
        log(f"{m['sp']['no']} {m['title']}: {len(m['holes'])} 个孔,已出图")
    c.save()
    return PDF


if __name__ == "__main__":
    print("图纸已生成:", write_all())
