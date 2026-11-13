#!/usr/bin/env python3
"""生成发给加工厂的图纸包:每个零件一张 A3 工程图(PDF)和一份 1:1 的 DXF。尺寸取自 build.py 的当前参数。
依赖: pip install cadquery reportlab ezdxf
运行: python drawings.py
输出: ../drawings/HP-drawings.pdf(8 页)、../drawings/dxf/*.dxf。三维模型在 ../models/。
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
DR = os.path.normpath(os.path.join(HERE, "..", "drawings"))
PDF = os.path.join(DR, "HP-drawings.pdf")
DXF = os.path.join(DR, "dxf")
REV = "v0.1"
PROJECT = "hPIPAC 前端加热系统 样机"

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
    ss_notes = ["材料 316L 不锈钢,数控车削。台架试水阶段可用光固化树脂打印代替。", "未注尺寸以同名 STEP 模型为准,未注公差 ±0.05。",
                "内腔和喷口粗糙度 Ra≤0.8,喷口边缘保持锐边、无毛刺、无倒角。", "超声清洗,无油无屑。"]
    return {
        "01_nozzle_tip_316L": dict(no="HP-01", mat="316L", notes=ss_notes + ["喷口与外圆同轴度 0.03。"],
                                   extra=[f"喷口直径 {fmt(b.NOZ_ORI)}(公差 +0.02/0),直段长 1。毛细管外径 {fmt(b.CAP_OD)},环形气隙面积 {b.GAS_AREA} mm2。",
                                          f"上段 φ{fmt(b.NOZ_D - 2)} 插进喷头杆内孔,激光焊或医用环氧胶封固。下段 φ{fmt(b.NOZ_D)} 与喷头杆外径齐平。",
                                          "内腔从 φ%s 以锥面收缩到喷口。" % fmt(b.NOZ_D - 4)]),
        "02_nozzle_spider_316L": dict(no="HP-02", mat="316L", notes=ss_notes + ["中心孔与外圆同轴度 0.02。"],
                                      holes={round(b.CAP_OD + 0.06, 2): "毛细管定心孔"},
                                      extra=["三条 1 mm 宽的切向槽通气,并让气流旋转。线切割或微铣加工。",
                                             "压进喷嘴头内腔,距喷口端面 5。毛细管穿过中心孔,末端伸出喷口 0.5。"]),
        "03_nozzle_manifold_AL6061": dict(no="HP-03", mat="6061-T6", holes={2.2: "测温孔", 8.6: "进气口,攻 G1/8", 6.0: "进气通道", 4.2: "测压口,攻 M5",
                                                                           5.0: "毛细管压紧接头,攻 M6", round(b.NOZ_D + 0.06, 2): "喷头杆插孔", round(b.NOZ_D - 2, 2): "气室"},
                                          notes=["材料 6061-T6 铝合金,数控加工。只接触气体,不接触药液。", "未注尺寸以同名 STEP 模型为准,未注公差 ±0.1。",
                                                 "喷头杆插孔 H7,插入后 O 形圈加医用环氧胶密封。", "各螺纹口和插孔 100 kPa 气密。",
                                                 "锐边倒钝 C0.3。样机不做表面处理;成品做硬质阳极氧化。"],
                                          extra=["喷头杆从底面插入 20;气从 +X 侧面进气室,沿喷头杆向下;毛细管从顶面中心穿出,用 M6 压紧接头密封。",
                                                 "加热片贴在 -Y 大平面上;两只测温探头插进 +Y 面的测温孔。"]),
        "04_syringe_jacket_half": dict(no="HP-04", mat="PETG", notes=PRINT_NOTES + ["填充 30%。做 2 件,两件相同。"],
                                       holes={3.4: "M3 过孔,两片对扣"},
                                       extra=[f"内径 {fmt(b.SYR_D + 2 * b.SYR_GAP)}:注射筒外径 {fmt(b.SYR_D)},每边留 {fmt(b.SYR_GAP)} 贴硅胶加热片和保温棉。下单前先量注射筒外径。",
                                              "一端顶部的缺口是加热片和测温线的出线口。"]),
        "05_humidifier_plate_AL6061": dict(no="HP-05", mat="6061-T6", holes={3.4: "M3 沉头螺丝孔,上表面锪 90° 沉头 φ6.5", 2.2: "测温孔"},
                                           notes=["材料 6061-T6 铝合金,数控加工。", "未注尺寸以同名 STEP 模型为准,未注公差 ±0.1。",
                                                  "上表面(放加湿罐的面)平面度 0.05,粗糙度 Ra≤1.6。", "锐边倒钝 C0.3。",
                                                  "样机不做表面处理;成品做硬质阳极氧化。"],
                                           extra=[f"直径 {fmt(b.HUM_D)} 按加湿罐底面直径定,下单前先量加湿罐。", "两个测温孔从同一侧的圆周面钻入,孔中心在板厚正中。"]),
        "06_humidifier_base": dict(no="HP-06", mat="PETG 或耐温 ABS", notes=PRINT_NOTES + ["填充 30%。铝盘最高 85 ℃,底座与铝盘之间垫 3 mm 硅胶隔热垫。"],
                                   holes={2.6: "M3 自攻螺丝底孔,固定铝盘", 12.2: "GX12 航空插座"},
                                   extra=["顶部沉台放铝盘,铝盘高出底座 0.5。沉台一侧的缺口走测温线。"]),
        "07_control_box_body": dict(no="HP-07", mat="PETG", notes=PRINT_NOTES + ["填充 30%。开口朝上打印。"],
                                    holes={2.6: "M3 自攻螺丝底孔(四角螺丝柱)", 16.2: "GX16 航空插座:电源、注射筒套、喷头歧管、加湿底座、输气管",
                                           12.2: "GX12 航空插座:循环泵、腹腔探头和压力"}),
        "08_control_box_lid": dict(no="HP-08", mat="PETG", notes=PRINT_NOTES + ["填充 30%。外表面朝下打印。"],
                                   holes={3.4: "M3 过孔", 5.2: "φ5 指示灯(红、黄、绿)", 16.2: "中止键 φ16", 12.2: "消音键 φ12",
                                          12.0: "蜂鸣器出声孔"},
                                   extra=[f"矩形窗口 {fmt(b.SCR_W)}×{fmt(b.SCR_H)} 是 7 英寸触摸屏的可视窗,中心 ({fmt(b.BX / 2)},{fmt(b.lid_screen_y())})。屏的玻璃从盒内用双面胶贴在盖板背面。",
                                          "下排从左到右:红、黄、绿指示灯,中止键,消音键,蜂鸣器。"]),
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
        if span < 2 * math.pi - 0.01:               # 不是整圆(如被开口切开的孔)
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
    _ordinates(sh, xs, lambda v: tx + v * scale, ty, True)
    _ordinates(sh, ys, lambda v: ty + v * scale, tx, False)
    # 右上:轴测图
    rx = lx + Y * scale + 14
    if 400 - rx >= 45 and m["iso"]:
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
    sh.text(12, 289, f"三维模型:3-mechanical/models/{'cnc' if m['how'] == 'CNC' else 'print'}/{m['name']}.step        二维:3-mechanical/drawings/dxf/{m['name']}.dxf", 2.4)


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
