#!/usr/bin/env python3
"""hPIPAC 前端加热系统样机全部结构件的参数化三维模型(STEP 给 CNC/改图用,STL 给 3D 打印用)。
依赖: pip install cadquery
  python build.py      按 params.json(没有则用默认值)导出全部零件到 ../models/cnc 和 ../models/print
  python studio.py     打开三维查看器,在浏览器里旋转查看、改尺寸、保存
所有尺寸单位 mm。
"""
import json, os
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.normpath(os.path.join(HERE, "..", "models"))
OUT_DIR = {"CNC": os.path.join(MODELS, "cnc"), "PRINT": os.path.join(MODELS, "print")}
PARAMS_FILE = os.path.join(HERE, "params.json")

# (键, 名称, 默认值, 最小, 最大, 步长, 分组)
PARAMS = [
    ("PL", "铝板长", 200.0, 120, 300, 1, "高压管保温板"),
    ("PW", "铝板宽", 76.0, 50, 120, 1, "高压管保温板"),
    ("PT", "铝板厚", 6.0, 5, 10, 0.5, "高压管保温板"),
    ("GROOVE_R", "槽半径(= 高压管外径的一半)", 2.0, 1.5, 3.5, 0.05, "高压管保温板"),
    ("GROOVE_DEPTH", "单片槽深", 1.95, 1.2, 3.5, 0.05, "高压管保温板"),
    ("BEND_R", "高压管转弯半径", 15.0, 8, 25, 0.5, "高压管保温板"),
    ("S_WALL", "壁厚", 2.5, 1.6, 4, 0.1, "保温板外壳"),
    ("S_FLOOR", "底厚", 2.0, 1.2, 4, 0.1, "保温板外壳"),
    ("S_GAP", "铝板四周间隙", 1.5, 0.3, 4, 0.1, "保温板外壳"),
    ("S_INSUL", "保温层厚", 3.0, 1, 10, 0.5, "保温板外壳"),
    ("SYR_D", "注射筒外径", 50.0, 30, 75, 0.5, "注射筒加热套"),
    ("SYR_L", "加热段长度", 120.0, 60, 200, 1, "注射筒加热套"),
    ("HUM_D", "加湿罐底面直径", 110.0, 80, 150, 0.5, "加湿加热底座"),
    ("BX", "盒长", 205.0, 120, 280, 1, "主控盒"),
    ("BY", "盒宽", 145.0, 80, 220, 1, "主控盒"),
    ("BZ", "盒高", 65.0, 35, 100, 1, "主控盒"),
    ("SCR_W", "触摸屏可视区宽", 155.0, 60, 230, 0.5, "主控盒"),
    ("SCR_H", "触摸屏可视区高", 87.0, 40, 150, 0.5, "主控盒"),
    ("BW", "盒壁厚", 2.5, 1.6, 4, 0.1, "主控盒"),
]
DEFAULTS = {p[0]: float(p[2]) for p in PARAMS}
# 触摸屏玻璃比可视区每边多出的黑边。默认按树莓派官方 7 英寸触摸屏:玻璃 193 x 111,可视区 154 x 86
SCR_BEZEL_X, SCR_BEZEL_Y = 19.5, 12.5


def apply(params=None):
    """把参数写进模块全局变量,并算出由它们决定的孔位。尺寸不合理时抛 ValueError。"""
    p = dict(DEFAULTS)
    p.update({k: float(v) for k, v in (params or {}).items() if k in DEFAULTS})
    if p["GROOVE_DEPTH"] > p["GROOVE_R"]:
        raise ValueError("单片槽深不能大于槽半径")
    if p["PW"] < 4 * p["BEND_R"] + 2 * p["GROOVE_R"] + 8:
        raise ValueError(f"铝板太窄:三折槽在转弯半径 {p['BEND_R']:g} 下至少需要宽 {4 * p['BEND_R'] + 2 * p['GROOVE_R'] + 8:g}")
    if p["PT"] - p["GROOVE_DEPTH"] < 3.2:
        raise ValueError("铝板太薄:槽底下方放不下 Ø2.2 测温孔")
    if p["PL"] < 2 * (p["BEND_R"] + 6) + 60:
        raise ValueError("铝板太短")
    if p["BX"] < p["SCR_W"] + 2 * SCR_BEZEL_X + 2 * p["BW"] + 5:
        raise ValueError(f"主控盒太短:放下这块触摸屏至少需要盒长 {p['SCR_W'] + 2 * SCR_BEZEL_X + 2 * p['BW'] + 5:g}")
    if p["BY"] < p["SCR_H"] + 2 * SCR_BEZEL_Y + p["BW"] + 26.5:
        raise ValueError(f"主控盒太窄:屏幕下方还要放一排指示灯和按键,至少需要盒宽 {p['SCR_H'] + 2 * SCR_BEZEL_Y + p['BW'] + 26.5:g}")
    g = globals()
    g.update(p)
    g["P"] = p
    g["RUN_Y"] = (p["PW"] / 2 + 2 * p["BEND_R"], p["PW"] / 2, p["PW"] / 2 - 2 * p["BEND_R"])   # 三条直槽中心
    g["TURN_X"] = p["BEND_R"] + 6.0                                                             # 弯道圆心距板端
    g["SCREWS"] = [(round(p["PL"] * 0.3), p["PW"] / 2 - p["BEND_R"]), (round(p["PL"] * 0.7), p["PW"] / 2 - p["BEND_R"]),
                   (round(p["PL"] * 0.3), p["PW"] / 2 + p["BEND_R"]), (round(p["PL"] * 0.7), p["PW"] / 2 + p["BEND_R"])]  # 4 x M3
    g["DOWELS"] = [(p["PL"] - 8, p["PW"] - 4), (8, 4)]                                           # 2 x Ø3
    g["NTC_X"] = (p["PL"] / 2 - 3, p["PL"] / 2 + 7)                                              # 测温孔 Ø2.2 深 20
    g["NTC_Z"] = round((p["PT"] - p["GROOVE_DEPTH"]) / 2, 2)                                     # 测温孔中心高度(槽底与背面正中)
    g["S_DEPTH"] = p["S_INSUL"] + p["PT"]                                                       # 腔深;铝板面高出壳口一个加热片厚度
    return p


def load_params():
    if os.path.exists(PARAMS_FILE):
        with open(PARAMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


apply(load_params())


def groove_length():
    return (PL - TURN_X) * 2 + (PL - 2 * TURN_X) + 2 * 3.14159265 * BEND_R


def groove_path(mirror):
    """槽中心线。mirror=True 为上板(关于 y=PW/2 镜像),合模后与下板的槽对齐。"""
    y = [PW - v for v in RUN_Y] if mirror else list(RUN_Y)
    z = PT + (GROOVE_R - GROOVE_DEPTH)
    xr, xl = PL - TURN_X, TURN_X
    s = 1 if y[0] > y[1] else -1
    return (cq.Workplane("XY").workplane(offset=z)
            .moveTo(-1, y[0]).lineTo(xr, y[0])
            .threePointArc((xr + BEND_R, y[0] - s * BEND_R), (xr, y[1]))
            .lineTo(xl, y[1])
            .threePointArc((xl - BEND_R, y[1] - s * BEND_R), (xl, y[2]))
            .lineTo(PL + 1, y[2]))


def plate(upper):
    p = cq.Workplane("XY").box(PL, PW, PT, centered=False)
    y0 = (PW - RUN_Y[0]) if upper else RUN_Y[0]
    z = PT + (GROOVE_R - GROOVE_DEPTH)
    profile = cq.Workplane("YZ").workplane(offset=-1).center(y0, z).circle(GROOVE_R)
    p = p.cut(profile.sweep(groove_path(upper), transition="round"))
    mir = (lambda pt: (pt[0], PW - pt[1])) if upper else (lambda pt: pt)
    d = 3.4 if upper else 2.5          # 上板通孔,下板 M3 底孔(攻丝)
    for pt in SCREWS:
        x, yy = mir(pt)
        p = p.cut(cq.Workplane("XY").center(x, yy).circle(d / 2).extrude(PT))
    for pt in DOWELS:
        x, yy = mir(pt)
        p = p.cut(cq.Workplane("XY").center(x, yy).circle(1.5).extrude(PT))
    for x in (NTC_X if not upper else NTC_X[:1]):          # 测温孔从 y=0 长边钻入
        p = p.cut(cq.Workplane("XZ").center(x, NTC_Z).circle(1.1).extrude(-20))
    return p


# ---------------- 高压管保温板外壳(3D 打印,上下各一) ----------------
EAR_OUT = 9.0     # 绑带耳伸出壳体的长度
def heater_shell(upper):
    ox, oy = PL + 2 * (S_GAP + S_WALL), PW + 2 * (S_GAP + S_WALL)
    s = (cq.Workplane("XY").box(ox, oy, S_FLOOR + S_DEPTH, centered=False)
         .edges("|Z").fillet(6).faces("<Z").edges().fillet(min(1.5, S_FLOOR * 0.7)))
    cav = cq.Workplane("XY").workplane(offset=S_FLOOR).center(S_WALL, S_WALL).rect(PL + 2 * S_GAP, PW + 2 * S_GAP, centered=False).extrude(S_DEPTH)
    s = s.cut(cav)
    off = S_GAP + S_WALL
    ys = [PW - v for v in RUN_Y] if upper else list(RUN_Y)
    top = S_FLOOR + S_DEPTH
    for x, yy in ((-1, ys[0]), (ox - S_WALL - S_GAP - 1, ys[2])):   # 进出管缺口
        s = s.cut(cq.Workplane("XY").workplane(offset=top - 2.2).center(x, yy + off - 2.6).rect(S_WALL + S_GAP + 2, 5.2, centered=False).extrude(3))
    if not upper:                                                    # 下壳:长边中部 8 x 5 线缆出口
        s = s.cut(cq.Workplane("XY").workplane(offset=S_FLOOR + 1).center(ox / 2 - 4, -1).rect(8, S_WALL + 2, centered=False).extrude(5))
        for x in (ox * 0.25, ox * 0.75):                             # 另一条长边:两个绑带耳,穿 15 mm 绑带固定在手术台边
            ear = cq.Workplane("XY").center(x, oy + EAR_OUT / 2 - 0.5).rect(24, EAR_OUT + 1).extrude(4).edges("|Z").fillet(2)
            s = s.union(ear).cut(cq.Workplane("XY").center(x, oy + EAR_OUT / 2 + 0.5).rect(17, 3.5).extrude(4))
    else:                                                            # 上壳:4 个螺丝过孔,拧 M3 夹紧螺丝用
        for pt in SCREWS:
            s = s.cut(cq.Workplane("XY").center(pt[0] + off, PW - pt[1] + off).circle(3.5).extrude(S_FLOOR))
    return s


# ---------------- 注射筒加热套(3D 打印,两个相同的半壳) ----------------
SYR_GAP = 4.5     # 注射筒与半壳之间留给硅胶加热片和保温棉的厚度


def syringe_jacket_half():
    """半圆筒,轴线沿 X。两片对扣包住高压注射器的针筒,内衬硅胶加热片。"""
    ri = SYR_D / 2 + SYR_GAP
    ro = ri + 2.5
    h = cq.Workplane("YZ").circle(ro).circle(ri).extrude(SYR_L)
    h = h.cut(cq.Workplane("XY").box(SYR_L + 2, 2 * ro + 2, ro + 1, centered=(False, True, False)).translate((-1, 0, -ro - 1)))
    for sy in (1, -1):                                   # 两侧法兰,各 2 个 M3 孔,两片用螺丝或绑带对扣
        y0 = sy * (ro - 1) if sy > 0 else sy * (ro + 10)
        f = cq.Workplane("XY").center(0, y0).rect(SYR_L, 11, centered=False).extrude(4)
        for x in (SYR_L * 0.2, SYR_L * 0.8):
            f = f.cut(cq.Workplane("XY").center(x, sy * (ro + 5)).circle(1.7).extrude(4))
        h = h.union(f)
    h = h.cut(cq.Workplane("XY").workplane(offset=ri - 1).center(SYR_L - 10, -4).rect(11, 8, centered=False).extrude(5))   # 出线口
    return h


# ---------------- 加湿加热底座:铝盘(CNC)+ 底座(3D 打印) ----------------
def hum_plate():
    """铝盘,上面放一次性加湿罐,下面贴硅胶加热片。"""
    p = cq.Workplane("XY").circle(HUM_D / 2).extrude(6)
    for a in (90, 210, 330):                             # 3 x M3 沉头螺丝固定到底座
        p = p.cut(cq.Workplane("XY").polarArray((HUM_D - 10) / 2, a, 360, 1).circle(1.7).extrude(6))
    for y in (0, 10):                                    # 2 个测温孔从 +X 侧边钻入
        p = p.cut(cq.Workplane("YZ").workplane(offset=HUM_D / 2 + 1).center(y, 3).circle(1.1).extrude(-23))
    return p


def hum_base():
    ro, h = HUM_D / 2 + 5, 45.0
    b = cq.Workplane("XY").circle(ro).extrude(h).faces("<Z").edges().fillet(1.5)
    b = b.cut(cq.Workplane("XY").workplane(offset=h - 5.5).circle(HUM_D / 2 + 0.3).extrude(6))          # 铝盘沉台,铝盘高出 0.5
    b = b.cut(cq.Workplane("XY").workplane(offset=3).circle(HUM_D / 2 - 10).extrude(h))                # 内腔:加热片、保温、接线
    b = b.cut(cq.Workplane("XY").workplane(offset=3).circle(HUM_D / 2 - 2).extrude(h - 22))             # 台阶以下掏空,壁厚 7
    for a in (90, 210, 330):                                                                           # 台阶上 3 个 M3 自攻底孔
        b = b.cut(cq.Workplane("XY").workplane(offset=h - 17).polarArray((HUM_D - 10) / 2, a, 360, 1).circle(1.3).extrude(12))
    b = b.cut(cq.Workplane("YZ").workplane(offset=ro + 1).center(0, 18).circle(6.1).extrude(-20))      # 侧面 GX12 航空插座孔
    b = b.cut(cq.Workplane("XY").workplane(offset=h - 9).center(HUM_D / 2 - 11, -5).rect(20, 20, centered=False).extrude(10))   # 测温线出口
    return b


# ---------------- 主控盒(3D 打印) ----------------
def box_body():
    b = cq.Workplane("XY").box(BX, BY, BZ, centered=False).edges("|Z").fillet(8).faces("<Z").edges().fillet(min(2, BW * 0.7))
    b = b.cut(cq.Workplane("XY").workplane(offset=BW).center(BW, BW).rect(BX - 2 * BW, BY - 2 * BW, centered=False).extrude(BZ))
    for x, y in ((9, 9), (BX - 9, 9), (9, BY - 9), (BX - 9, BY - 9)):       # 四角螺丝柱,M3 自攻
        b = b.union(cq.Workplane("XY").workplane(offset=BW).center(x, y).circle(4.5).circle(1.3).extrude(BZ - BW))
    side = lambda x, d: cq.Workplane("XZ").center(x, BZ * 0.4).circle(d / 2).extrude(-BW - 1)   # y=0 侧面开孔
    step = (BX - 44) / 6
    for i, d in enumerate((16.2, 16.2, 16.2, 16.2, 16.2, 12.2, 12.2)):   # GX16:电源、注射筒套、保温板、加湿底座、输气管;GX12:循环泵、腹腔探头和压力
        b = b.cut(side(22 + i * step, d))
    return b


def lid_screen_y():
    """触摸屏可视窗中心在盖板上的高度:玻璃上边缘贴着盖板内圈。"""
    return BY - BW - 2.5 - SCR_BEZEL_Y - SCR_H / 2


def box_lid():
    l = cq.Workplane("XY").box(BX, BY, 3, centered=False).edges("|Z").fillet(8)
    l = l.union(cq.Workplane("XY").workplane(offset=-2).center(BW + 0.3, BW + 0.3)
                .rect(BX - 2 * BW - 0.6, BY - 2 * BW - 0.6, centered=False).extrude(2)
                .cut(cq.Workplane("XY").workplane(offset=-2).center(BW + 2.3, BW + 2.3)
                     .rect(BX - 2 * BW - 4.6, BY - 2 * BW - 4.6, centered=False).extrude(2)))
    cut = lambda sk: l.cut(sk.extrude(10, both=True))
    for x, y in ((9, 9), (BX - 9, 9), (9, BY - 9), (BX - 9, BY - 9)):
        l = cut(cq.Workplane("XY").center(x, y).circle(1.7))
    cx, wy, ry = BX / 2, lid_screen_y(), 14.0
    l = cut(cq.Workplane("XY").center(cx, wy).rect(SCR_W, SCR_H))            # 触摸屏可视窗;屏从盒内贴在盖板背面
    for x in (cx - 72, cx - 57, cx - 42):                                     # 红 黄 绿 LED Ø5
        l = cut(cq.Workplane("XY").center(x, ry).circle(2.6))
    l = cut(cq.Workplane("XY").center(cx - 8, ry).circle(8.1))                # 暂停键 Ø16
    l = cut(cq.Workplane("XY").center(cx + 28, ry).circle(6.1))               # 消音键 Ø12
    l = cut(cq.Workplane("XY").center(cx + 62, ry).circle(6.0))               # 蜂鸣器出声孔
    return l


def heater_assembly():
    """仅供查看:下板 + 翻过来的上板,检查槽和孔是否对齐(不导出加工)。"""
    lower = plate(False)
    upper = plate(True).rotate((0, 0, 0), (1, 0, 0), 180).translate((0, PW, 2 * PT + 12))
    return lower.union(upper)


def _flip(shape, w, h):
    """绕 X 轴翻 180 度后放回原位:上板、上壳扣到下半部上。"""
    return shape.rotate((0, 0, 0), (1, 0, 0), 180).translate((0, w, h))


def heater_module_parts(lift=0.0):
    """高压管保温板四件按装配位置摆放。lift 为上半部抬起的距离。返回 [(名称, 类别, 实体)]。"""
    off = S_GAP + S_WALL
    oy = PW + 2 * off
    zp = S_FLOOR + S_INSUL                      # 下板底面高度
    top = S_FLOOR + S_DEPTH                     # 合模面高度
    return [
        ("保温板 下壳", "PRINT", heater_shell(False)),
        ("保温铝板 下板", "AL", plate(False).translate((off, off, zp))),
        ("保温铝板 上板", "AL", _flip(plate(True), PW, 0).translate((off, off, top + PT + lift))),
        ("保温板 上壳", "PRINT", _flip(heater_shell(True), oy, 2 * top + lift)),
    ]


def syringe_jacket_parts(lift=0.0):
    """两片加热套包住注射筒。轴线沿 X。"""
    ro = SYR_D / 2 + SYR_GAP + 2.5
    upper = syringe_jacket_half().translate((0, 0, lift))
    lower = syringe_jacket_half().rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, -lift))
    syr = cq.Workplane("YZ").workplane(offset=-25).circle(SYR_D / 2).extrude(SYR_L + 45)
    tip = cq.Workplane("YZ").workplane(offset=SYR_L + 20).circle(4).extrude(25)
    return [("注射筒加热套 半壳", "PRINT", upper), ("注射筒加热套 半壳", "PRINT", lower),
            ("高压注射器针筒(示意)", "SOFT", syr), ("高压注射器针筒(示意)", "SOFT", tip)]


def humidifier_parts():
    h = 45.0
    return [("加湿底座", "PRINT", hum_base()), ("加湿铝盘", "AL", hum_plate().translate((0, 0, h - 5.5))),
            ("一次性加湿罐(示意)", "SOFT", cq.Workplane("XY").workplane(offset=h + 0.5).circle(HUM_D / 2 - 3).extrude(85).edges(">Z").fillet(12))]


def _tube(pts, t0=(0, 0, -1), t1=None, d=4.1):
    """沿曲线扫出一段软管。pts 为三维点,t0、t1 为起点和终点的走向。"""
    path = cq.Workplane("XY").spline(pts, tangents=[t0, t1 or tuple(c - a for a, c in zip(pts[-2], pts[-1]))])
    return cq.Workplane(cq.Plane(origin=pts[0], xDir=(t0[1], t0[2], t0[0]) if abs(t0[2]) < 0.9 else (1, 0, 0), normal=t0)).circle(d / 2).sweep(path)


def full_assembly():
    """仅供查看:手术室里的摆放。灰色和半透明的是外购设备、病人和管路的示意,尺寸为大致比例。"""
    off = S_GAP + S_WALL
    ox = PL + 2 * off
    top = S_FLOOR + S_DEPTH
    parts = []
    add = lambda n, k, s: parts.append((n, k, s))
    box = lambda x0, x1, y0, y1, z0, z1: cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))
    cyl = lambda x, y, z0, z1, d: cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(d / 2).extrude(z1 - z0)
    ZT = 860.0                                                         # 手术台面高度
    add("手术台(示意)", "BUY", box(0, 900, -280, 280, ZT - 60, ZT))
    add("病人腹部(示意)", "SOFT", cq.Workplane("XY").workplane(offset=ZT).center(450, 0).ellipse(270, 175).extrude(120).edges(">Z").fillet(55))
    ZS = ZT + 120                                                      # 腹壁最高处
    tro = {"in": (350, -50), "neb": (450, 45), "out": (550, -50)}
    for k, (x, y) in tro.items():
        add("穿刺器(示意)", "BUY", cyl(x, y, ZS - 30, ZS + 80, 13))
    add("雾化喷头(示意)", "BUY", cyl(*tro["neb"], ZS + 80, ZS + 135, 9))
    # 腹腔温度探头:经穿刺器旁的细线
    add("腹腔温度探头(示意)", "BUY", cyl(420, -90, ZS - 20, ZS + 40, 3))
    add("腹腔温度探头(示意)", "BUY", cyl(520, 80, ZS - 20, ZS + 40, 3))

    # 高压注射器在病人一侧,针筒指向手术台
    add("高压注射器(示意)", "BUY", cyl(450, -620, 0, 1010, 34))
    add("高压注射器(示意)", "BUY", box(385, 515, -690, -560, 1010, 1130))
    zs, ys = 1070.0, -560.0
    for n, k, s in syringe_jacket_parts():
        add(n, k, s.rotate((0, 0, 0), (0, 0, 1), 90).translate((450, ys + 25, zs)))
    tipy = ys + 25 + SYR_L + 45
    # 高压管保温板放在手术台边,靠近喷头,绑带固定
    bx0, by0 = 330.0, -272.0
    for n, k, s in heater_module_parts():
        add(n, k, s.translate((bx0, by0, ZT)))
    y_in, y_out, zt = by0 + off + RUN_Y[0], by0 + off + RUN_Y[2], ZT + top
    d_hp = 2 * GROOVE_R
    add("高压管", "SOFT", _tube([(450, tipy, zs), (330, tipy + 60, zs - 110), (bx0 - 70, y_in - 10, zt + 25), (bx0, y_in, zt)], t0=(0, 1, 0), t1=(1, 0, 0), d=d_hp))
    add("高压管", "SOFT", _tube([(bx0 + ox, y_out, zt), (bx0 + ox + 70, y_out + 60, zt + 70), (tro["neb"][0] + 30, tro["neb"][1] - 40, ZS + 150), (tro["neb"][0], tro["neb"][1], ZS + 135)], t0=(1, 0, 0), t1=(0, 0.3, -1), d=d_hp))

    # 设备架在病人另一侧:主机、加湿底座、循环泵和过滤器
    px, py = 300.0, 640.0
    add("设备架立杆(示意)", "BUY", cyl(px, py, 0, 1500, 30))
    stand = lambda s: s.rotate((0, 0, 0), (1, 0, 0), 90).translate((px - BX / 2, py - 20.5, 1180))
    add("主控盒", "PRINT", stand(box_body()))
    add("主控盒盖", "PRINT", stand(box_lid().translate((0, 0, BZ))))
    gw, gh, wy = SCR_W + 2 * SCR_BEZEL_X, SCR_H + 2 * SCR_BEZEL_Y, lid_screen_y()
    add("7 英寸触摸屏(示意)", "SCREEN", box(px - gw / 2, px + gw / 2, py - 20.5 - BZ + 0.2, py - 20.5 - BZ + 2, 1180 + wy - gh / 2, 1180 + wy + gh / 2))
    zsh = 960.0
    add("设备架托板(示意)", "BUY", box(px - 190, px + 190, py - 230, py - 20, zsh - 10, zsh))
    hx, hy = px - 100, py - 125
    for n, k, s in humidifier_parts():
        add(n, k, s.translate((hx, hy, zsh)))
    add("循环泵和过滤器(示意)", "BUY", box(px + 30, px + 160, py - 190, py - 60, zsh, zsh + 90))
    ztop = zsh + 45 + 85
    add("加热输气管(进气)", "SOFT", _tube([(hx, hy, ztop), (hx + 20, hy - 180, ztop + 110), (tro["in"][0] - 10, tro["in"][1] + 170, ZS + 190), (tro["in"][0], tro["in"][1], ZS + 80)], t0=(0, 0, 1), t1=(0, -0.2, -1), d=10))
    add("回气管(经过滤器)", "SOFT", _tube([(tro["out"][0], tro["out"][1], ZS + 80), (tro["out"][0] + 10, tro["out"][1] + 170, ZS + 200), (px + 110, py - 300, zsh + 230), (px + 95, py - 125, zsh + 90)], t0=(0, 0, 1), t1=(0, 0.2, -1), d=10))
    return parts


# 名称 -> (生成函数, 做法, 中文名)
BUILDERS = {
    "01_line_plate_lower_AL6061": (lambda: plate(False), "CNC", "保温铝板 下板"),
    "02_line_plate_upper_AL6061": (lambda: plate(True), "CNC", "保温铝板 上板"),
    "03_line_shell_lower": (lambda: heater_shell(False), "PRINT", "保温板 下壳"),
    "04_line_shell_upper": (lambda: heater_shell(True), "PRINT", "保温板 上壳"),
    "05_syringe_jacket_half": (syringe_jacket_half, "PRINT", "注射筒加热套 半壳(做 2 件)"),
    "06_humidifier_plate_AL6061": (hum_plate, "CNC", "加湿铝盘"),
    "07_humidifier_base": (hum_base, "PRINT", "加湿底座"),
    "08_control_box_body": (box_body, "PRINT", "主控盒"),
    "09_control_box_lid": (box_lid, "PRINT", "主控盒盖"),
}
VIEW_ONLY = {
    "00_plates_open_check": (heater_assembly, "VIEW", "上下铝板对合检查(上板抬起 12)"),
    "20_line_warmer": (lambda: heater_module_parts(0), "VIEW", "高压管保温板装配"),
    "21_line_warmer_open": (lambda: heater_module_parts(25), "VIEW", "高压管保温板装配(打开)"),
    "22_syringe_jacket": (lambda: syringe_jacket_parts(0), "VIEW", "注射筒加热套装配"),
    "23_humidifier": (humidifier_parts, "VIEW", "加湿加热底座装配"),
    "30_full_assembly": (full_assembly, "VIEW", "手术室整体布置"),
}


def export_all(log=print):
    for name, (fn, how, title) in BUILDERS.items():
        part = fn(); solid = part.val(); bb = solid.BoundingBox()
        os.makedirs(OUT_DIR[how], exist_ok=True)
        cq.exporters.export(part, os.path.join(OUT_DIR[how], name + ".step"))
        if how == "PRINT":                      # 打印件另给 STL;铝板只发 STEP
            cq.exporters.export(part, os.path.join(OUT_DIR[how], name + ".stl"), tolerance=0.05, angularTolerance=0.2)
        log(f"{name:26s} {how:5s} {bb.xlen:6.1f} x {bb.ylen:5.1f} x {bb.zlen:5.1f} mm  体积 {solid.Volume() / 1000:7.1f} cm3  valid={solid.isValid()}")


if __name__ == "__main__":
    export_all()
