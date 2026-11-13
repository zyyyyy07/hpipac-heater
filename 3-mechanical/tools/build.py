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
    ("NOZ_D", "喷头杆外径", 10.0, 8, 12, 0.5, "气助雾化喷头"),
    ("NOZ_L", "喷头杆长度", 200.0, 120, 280, 5, "气助雾化喷头"),
    ("NOZ_ORI", "喷口直径", 2.0, 1.8, 3.0, 0.05, "气助雾化喷头"),
    ("CAP_OD", "药液毛细管外径", 1.6, 1.0, 2.0, 0.1, "气助雾化喷头"),
    ("SYR_D", "注射筒外径", 30.0, 15, 75, 0.5, "注射筒加热套"),
    ("SYR_L", "加热段长度", 100.0, 50, 200, 1, "注射筒加热套"),
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
    if p["NOZ_ORI"] < p["CAP_OD"] + 0.25:
        raise ValueError(f"喷口太小:要比毛细管外径至少大 0.25,否则环形气隙做不出来(当前毛细管 {p['CAP_OD']:g})")
    if p["NOZ_ORI"] > p["NOZ_D"] - 5:
        raise ValueError("喷口太大:超过了喷头杆内腔")
    if p["BX"] < p["SCR_W"] + 2 * SCR_BEZEL_X + 2 * p["BW"] + 5:
        raise ValueError(f"主控盒太短:放下这块触摸屏至少需要盒长 {p['SCR_W'] + 2 * SCR_BEZEL_X + 2 * p['BW'] + 5:g}")
    if p["BY"] < p["SCR_H"] + 2 * SCR_BEZEL_Y + p["BW"] + 26.5:
        raise ValueError(f"主控盒太窄:屏幕下方还要放一排指示灯和按键,至少需要盒宽 {p['SCR_H'] + 2 * SCR_BEZEL_Y + p['BW'] + 26.5:g}")
    g = globals()
    g.update(p)
    g["P"] = p
    g["GAS_AREA"] = round(3.14159265 / 4 * (p["NOZ_ORI"] ** 2 - p["CAP_OD"] ** 2), 3)             # 环形气隙面积 mm2
    return p


def load_params():
    if os.path.exists(PARAMS_FILE):
        with open(PARAMS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


apply(load_params())


# ---------------- 气助加热雾化喷头 ----------------
# 喷头轴线沿 Z,喷口在 z=0 朝下。药液走中心毛细管,温热的 CO2 走毛细管外面的环形通道,
# 在喷口处高速气流把药液撕成雾(外混式双流体雾化)。
TIP_H, MAN_X, MAN_Y, MAN_Z, MAN_IN = 14.0, 36.0, 30.0, 50.0, 20.0


def nozzle_tip():
    """喷嘴头:压进喷头杆下端。内腔收缩到喷口,毛细管从喷口中心伸出。"""
    ro, rb, rj = NOZ_D / 2, NOZ_D / 2 - 2, NOZ_ORI / 2
    pts = [(rj, 0), (ro - 1, 0), (ro, 1), (ro, 8), (ro - 1, 8), (ro - 1, TIP_H), (rb, TIP_H), (rb, 4), (rj, 1)]
    return cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))


def nozzle_spider():
    """定心旋流片:放在喷嘴头内腔里,把毛细管定在正中;三条切向槽让气流带旋转,喷雾锥角更大。"""
    r = NOZ_D / 2 - 2 - 0.03
    d = cq.Workplane("XY").circle(r).circle(CAP_OD / 2 + 0.03).extrude(4)
    for a in (0, 120, 240):
        slot = cq.Workplane("XY").center(r / 2 + 0.6, CAP_OD / 2 + 1.0).rect(r, 1.0).extrude(4)
        d = d.cut(slot.rotate((0, 0, 0), (0, 0, 1), a))
    return d


def nozzle_manifold():
    """歧管:喷头留在体外的部分。喷头杆从下面插入,气从侧面进,毛细管从顶上穿出,背面贴加热片。"""
    m = cq.Workplane("XY").box(MAN_X, MAN_Y, MAN_Z, centered=(True, True, False)).edges("|Z").fillet(3)
    m = m.cut(cq.Workplane("XY").circle(NOZ_D / 2 + 0.03).extrude(MAN_IN))                                   # 喷头杆插孔
    m = m.cut(cq.Workplane("XY").workplane(offset=MAN_IN).circle(NOZ_D / 2 - 1).extrude(16))                 # 气室
    m = m.cut(cq.Workplane("XY").workplane(offset=MAN_IN + 16).circle(CAP_OD / 2 + 0.05).extrude(MAN_Z))     # 毛细管穿孔
    m = m.cut(cq.Workplane("XY").workplane(offset=MAN_Z - 6).circle(2.5).extrude(6))                         # 顶部 M6 压紧接头底孔
    zg = MAN_IN + 8
    m = m.cut(cq.Workplane("YZ").workplane(offset=MAN_X / 2).center(0, zg).circle(4.3).extrude(-10))        # +X 面进气口 G1/8
    m = m.cut(cq.Workplane("YZ").workplane(offset=MAN_X / 2).center(0, zg).circle(3.0).extrude(-MAN_X / 2))
    m = m.cut(cq.Workplane("YZ").workplane(offset=-MAN_X / 2).center(0, zg).circle(2.1).extrude(MAN_X / 2))  # -X 面测压口 M5
    for x, z in ((-11, 10), (11, 40)):                                                                      # +Y 面 2 个测温孔
        m = m.cut(cq.Workplane("XZ").workplane(offset=-MAN_Y / 2).center(x, z).circle(1.1).extrude(13))
    return m


def nozzle_parts():
    """喷头装配:喷嘴头、旋流片、喷头杆、毛细管、歧管。"""
    zt = 8.0                                             # 喷头杆下端
    zm = zt + NOZ_L - MAN_IN                             # 歧管底面
    shaft = cq.Workplane("XY").workplane(offset=zt).circle(NOZ_D / 2).circle(NOZ_D / 2 - 1).extrude(NOZ_L)
    cap = cq.Workplane("XY").workplane(offset=-0.5).circle(CAP_OD / 2).circle(CAP_OD / 2 - 0.3).extrude(zm + MAN_Z + 30)
    return [("喷嘴头", "AL", nozzle_tip()), ("定心旋流片", "PRINT", nozzle_spider().translate((0, 0, 5))),
            ("喷头杆(不锈钢管,外购)", "BUY", shaft), ("药液毛细管(外购)", "SCREEN", cap),
            ("喷头歧管", "AL", nozzle_manifold().translate((0, 0, zm)))]


# ---------------- 注射筒加热套(3D 打印,两个相同的半壳) ----------------
SYR_GAP = 4.5     # 注射筒与半壳之间留给硅胶加热片和保温棉的厚度


def syringe_jacket_half():
    """半圆筒,轴线沿 X。两片对扣包住注射泵的针筒,内衬硅胶加热片。"""
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
    for i, d in enumerate((16.2, 16.2, 16.2, 16.2, 16.2, 12.2, 12.2)):   # GX16:电源、注射筒套、喷头歧管、加湿底座、输气管;GX12:循环泵、腹腔探头和压力
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


def syringe_jacket_parts(lift=0.0):
    """两片加热套包住注射筒。轴线沿 X。"""
    ro = SYR_D / 2 + SYR_GAP + 2.5
    upper = syringe_jacket_half().translate((0, 0, lift))
    lower = syringe_jacket_half().rotate((0, 0, 0), (1, 0, 0), 180).translate((0, 0, -lift))
    syr = cq.Workplane("YZ").workplane(offset=-25).circle(SYR_D / 2).extrude(SYR_L + 45)
    tip = cq.Workplane("YZ").workplane(offset=SYR_L + 20).circle(4).extrude(25)
    return [("注射筒加热套 半壳", "PRINT", upper), ("注射筒加热套 半壳", "PRINT", lower),
            ("注射泵针筒(示意)", "SOFT", syr), ("注射泵针筒(示意)", "SOFT", tip)]


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
    parts = []
    add = lambda n, k, s: parts.append((n, k, s))
    box = lambda x0, x1, y0, y1, z0, z1: cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))
    cyl = lambda x, y, z0, z1, d: cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(d / 2).extrude(z1 - z0)
    ZT = 860.0                                                         # 手术台面高度
    add("手术台(示意)", "BUY", box(0, 900, -280, 280, ZT - 60, ZT))
    add("病人腹部(示意)", "SOFT", cq.Workplane("XY").workplane(offset=ZT).center(450, 0).ellipse(270, 175).extrude(120).edges(">Z").fillet(55))
    ZS = ZT + 120                                                      # 腹壁最高处
    nx, ny = 430.0, 30.0                                               # 喷头所在的穿刺器
    ox_, oy_ = 570.0, -60.0                                            # 回气的穿刺器
    add("穿刺器(示意)", "BUY", cq.Workplane("XY").workplane(offset=ZS - 30).center(nx, ny).circle(7.5).circle(NOZ_D / 2 + 0.3).extrude(110))
    add("穿刺器(示意)", "BUY", cyl(ox_, oy_, ZS - 30, ZS + 80, 13))
    add("腹腔温度探头(示意)", "BUY", cyl(380, -90, ZS - 20, ZS + 40, 3))
    add("腹腔温度探头(示意)", "BUY", cyl(520, 80, ZS - 20, ZS + 40, 3))
    # 喷头:喷口伸进腹腔 40 mm
    z0 = ZS - 40
    for n, k, s in nozzle_parts():
        add(n, k, s.translate((nx, ny, z0)))
    zm = z0 + 8 + NOZ_L - MAN_IN                                       # 歧管底面
    gas_in = (nx + MAN_X / 2, ny, zm + MAN_IN + 8)
    cap_top = (nx, ny, zm + MAN_Z + 30)

    # 注射泵在病人一侧
    add("注射泵(示意)", "BUY", cyl(450, -620, 0, 1000, 34))
    add("注射泵(示意)", "BUY", box(330, 590, -690, -560, 1000, 1090))
    zs = 1090 + SYR_D / 2 + SYR_GAP + 6
    for n, k, s in syringe_jacket_parts():
        add(n, k, s.translate((370, -625, zs)))
    tipx = 370 + SYR_L + 45
    add("药液细管", "SOFT", _tube([(tipx, -625, zs), (tipx + 60, -520, zs + 60), (nx + 40, ny - 150, cap_top[2] + 90), cap_top], t0=(1, 0, 0), t1=(0, 0.3, -1), d=2.5))

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
    add("加热输气管(到喷头)", "SOFT", _tube([(hx, hy, ztop), (hx + 30, hy - 180, ztop + 120), (gas_in[0] + 130, gas_in[1] + 120, gas_in[2] + 40), gas_in], t0=(0, 0, 1), t1=(-1, -0.3, 0), d=10))
    add("回气管(经过滤器)", "SOFT", _tube([(ox_, oy_, ZS + 80), (ox_ + 10, oy_ + 170, ZS + 200), (px + 110, py - 300, zsh + 230), (px + 95, py - 125, zsh + 90)], t0=(0, 0, 1), t1=(0, 0.2, -1), d=10))
    return parts


# 名称 -> (生成函数, 做法, 中文名)
BUILDERS = {
    "01_nozzle_tip_316L": (nozzle_tip, "CNC", "喷嘴头"),
    "02_nozzle_spider_316L": (nozzle_spider, "CNC", "定心旋流片"),
    "03_nozzle_manifold_AL6061": (nozzle_manifold, "CNC", "喷头歧管"),
    "04_syringe_jacket_half": (syringe_jacket_half, "PRINT", "注射筒加热套 半壳(做 2 件)"),
    "05_humidifier_plate_AL6061": (hum_plate, "CNC", "加湿铝盘"),
    "06_humidifier_base": (hum_base, "PRINT", "加湿底座"),
    "07_control_box_body": (box_body, "PRINT", "主控盒"),
    "08_control_box_lid": (box_lid, "PRINT", "主控盒盖"),
}
VIEW_ONLY = {
    "20_nozzle": (nozzle_parts, "VIEW", "气助雾化喷头装配(点“剖切”看内部)"),
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
