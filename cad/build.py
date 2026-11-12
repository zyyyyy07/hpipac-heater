#!/usr/bin/env python3
"""样机全部结构件的参数化三维模型(STEP 给 CNC/改图用,STL 给 3D 打印用)。
依赖: pip install cadquery
  python build.py      按 params.json(没有则用默认值)导出全部零件到 out/
  python studio.py     打开三维查看器,在浏览器里旋转查看、改尺寸、保存
所有尺寸单位 mm。
"""
import json, os
import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PARAMS_FILE = os.path.join(HERE, "params.json")

# (键, 名称, 默认值, 最小, 最大, 步长, 分组)
PARAMS = [
    ("PL", "铝板长", 200.0, 120, 300, 1, "加温铝板"),
    ("PW", "铝板宽", 64.0, 50, 110, 1, "加温铝板"),
    ("PT", "铝板厚", 6.0, 5, 10, 0.5, "加温铝板"),
    ("GROOVE_R", "槽半径(球头刀 R)", 2.0, 1.5, 3.0, 0.05, "加温铝板"),
    ("GROOVE_DEPTH", "单片槽深", 1.95, 1.2, 3.0, 0.05, "加温铝板"),
    ("BEND_R", "管路转弯半径", 12.0, 8, 22, 0.5, "加温铝板"),
    ("S_WALL", "壁厚", 2.5, 1.6, 4, 0.1, "加温模块外壳"),
    ("S_FLOOR", "底厚", 2.0, 1.2, 4, 0.1, "加温模块外壳"),
    ("S_GAP", "铝板四周间隙", 1.5, 0.3, 4, 0.1, "加温模块外壳"),
    ("S_INSUL", "保温层厚", 3.0, 1, 10, 0.5, "加温模块外壳"),
    ("DRIP_D", "滴斗外径", 17.0, 12, 24, 0.1, "滴斗传感器夹"),
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


# ---------------- 加温模块外壳(3D 打印,上下各一) ----------------
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
    else:                                                            # 上壳:4 个螺丝过孔,拧 M3 夹紧螺丝用
        for pt in SCREWS:
            s = s.cut(cq.Workplane("XY").center(pt[0] + off, PW - pt[1] + off).circle(3.5).extrude(S_FLOOR))
    return s


# ---------------- 滴斗传感器夹(3D 打印) ----------------
def drip_clip():
    w, dpt, h = DRIP_D + 23.0, DRIP_D + 13.0, 24.0
    c = cq.Workplane("XY").box(w, dpt, h).edges("|Z").fillet(3)
    c = c.cut(cq.Workplane("XY").circle(DRIP_D / 2).extrude(h, both=True))                           # 滴斗孔
    c = c.cut(cq.Workplane("XY").center(0, dpt / 2).rect(DRIP_D - 3.5, dpt).extrude(h, both=True))   # 前开口,卡入
    c = c.cut(cq.Workplane("YZ").circle(2.6).extrude(w, both=True))                                  # 5 mm 红外对管同轴孔
    for x in (-(DRIP_D / 2 + 4.5), DRIP_D / 2 + 4.5):                                                # 背面 2 x M3 安装孔
        c = c.cut(cq.Workplane("XZ").workplane(offset=dpt / 2 - 8).center(x, 0).circle(1.7).extrude(-10))
    return c


# ---------------- 称重传感器固定座(3D 打印或铝) ----------------
def loadcell_mount():
    b = cq.Workplane("XY").box(60, 30, 12).edges("|Z").fillet(3)
    b = b.union(cq.Workplane("XY").workplane(offset=6).center(-17.5, 0).rect(25, 14).extrude(2))   # 固定端垫高 2,另一端悬空
    for x in (-25, -10):                                    # 条形称重传感器固定端:2 x M5,孔距 15
        b = b.cut(cq.Workplane("XY").center(x, 0).circle(2.7).extrude(20, both=True))
    for x, y in ((8, -10), (8, 10), (24, -10), (24, 10)):   # 4 x M4 固定到主机盒或抱杆夹
        b = b.cut(cq.Workplane("XY").center(x, y).circle(2.2).extrude(20, both=True))
    return b


# ---------------- 主控盒(3D 打印) ----------------
def box_body():
    b = cq.Workplane("XY").box(BX, BY, BZ, centered=False).edges("|Z").fillet(8).faces("<Z").edges().fillet(min(2, BW * 0.7))
    b = b.cut(cq.Workplane("XY").workplane(offset=BW).center(BW, BW).rect(BX - 2 * BW, BY - 2 * BW, centered=False).extrude(BZ))
    for x, y in ((9, 9), (BX - 9, 9), (9, BY - 9), (BX - 9, BY - 9)):       # 四角螺丝柱,M3 自攻
        b = b.union(cq.Workplane("XY").workplane(offset=BW).center(x, y).circle(4.5).circle(1.3).extrude(BZ - BW))
    side = lambda x, d: cq.Workplane("XZ").center(x, BZ * 0.4).circle(d / 2).extrude(-BW - 1)   # y=0 侧面开孔
    step = (BX - 60) / 4
    for i, d in enumerate((8.2, 16.2, 12.2, 12.2, 12.2)):   # DC 电源座;GX16 加温线;GX12 滴斗、称重、夹管阀
        b = b.cut(side(30 + i * step, d))
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
    """加温模块四件按装配位置摆放。lift 为上半部抬起的距离。返回 [(名称, 类别, 实体)]。"""
    off = S_GAP + S_WALL
    oy = PW + 2 * off
    zp = S_FLOOR + S_INSUL                      # 下板底面高度
    top = S_FLOOR + S_DEPTH                     # 合模面高度
    return [
        ("加温模块 下壳", "PRINT", heater_shell(False)),
        ("加温铝板 下板", "AL", plate(False).translate((off, off, zp))),
        ("加温铝板 上板", "AL", _flip(plate(True), PW, 0).translate((off, off, top + PT + lift))),
        ("加温模块 上壳", "PRINT", _flip(heater_shell(True), oy, 2 * top + lift)),
    ]


def _tube(pts, d=4.1):
    """沿折线/曲线扫出一段输液管。pts 为三维点,第一段必须竖直向下。"""
    x0, y0, z0 = pts[0]
    if len(pts) == 2:
        return cq.Workplane("XY").workplane(offset=pts[1][2]).center(x0, y0).circle(d / 2).extrude(z0 - pts[1][2])
    path = cq.Workplane("XY").spline(pts, tangents=[(0, 0, -1), (0.3, -1, -0.1)])
    return cq.Workplane("XY").workplane(offset=z0).center(x0, y0).circle(d / 2).sweep(path)


def full_assembly():
    """仅供查看:整机挂在输液架上的样子。灰色和半透明的是外购件和耗材的示意,尺寸为常见规格。"""
    off = S_GAP + S_WALL
    ox = PL + 2 * off
    top = S_FLOOR + S_DEPTH
    XT, YT = BX / 2 + 40.0, -31.0               # 输液管所在的竖线
    ZB = BY + 15.0                              # 滴斗下端高度
    parts = []
    add = lambda n, k, s: parts.append((n, k, s))
    box = lambda x0, x1, y0, y1, z0, z1: cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False).translate((x0, y0, z0))
    cyl = lambda x, y, z0, z1, d: cq.Workplane("XY").workplane(offset=z0).center(x, y).circle(d / 2).extrude(z1 - z0)

    z_arm = ZB + 60 + 15 + 190 + 30             # 横臂底面:滴斗 60 + 袋口 15 + 袋 190 + 挂钩 30
    add("输液架立杆 Ø25(示意)", "BUY", cyl(0, 0, -PL - 170, z_arm + 60, 25))
    # 主控盒:竖着夹在立杆上,盖板朝前,接头朝下
    stand = lambda s: s.rotate((0, 0, 0), (1, 0, 0), 90).translate((-BX / 2, -20.5, 0))
    add("主控盒", "PRINT", stand(box_body()))
    add("主控盒盖", "PRINT", stand(box_lid().translate((0, 0, BZ))))
    add("抱杆夹(示意)", "BUY", box(-30, 30, -20.5, 16, BY / 2 - 28, BY / 2 + 28))
    gw, gh, wy = SCR_W + 2 * SCR_BEZEL_X, SCR_H + 2 * SCR_BEZEL_Y, lid_screen_y()
    add("7 英寸触摸屏(示意)", "SCREEN", box(-gw / 2, gw / 2, -20.5 - BZ + 0.2, -20.5 - BZ + 2, wy - gh / 2, wy + gh / 2))
    # 称重:横臂 + 固定座 + 条形称重传感器 + 挂钩
    add("抱杆夹横臂(示意)", "BUY", box(-22, XT - 20, -50, 16, z_arm, z_arm + 30))
    mx = XT - 40
    add("称重传感器固定座", "PRINT", loadcell_mount().translate((mx, YT, z_arm + 36)))
    add("条形称重传感器 80×12.7×12.7(示意)", "BUY", box(mx - 32, mx + 48, YT - 6.35, YT + 6.35, z_arm + 38, z_arm + 50.7))
    add("挂钩(示意)", "BUY", cyl(XT, YT, z_arm - 5, z_arm + 38, 3))
    # 输液袋、滴斗、滴斗夹
    zbag = ZB + 75
    add("输液袋 500 mL(示意)", "SOFT", box(XT - 60, XT + 60, YT - 14, YT + 14, zbag, zbag + 190).edges("|Y").fillet(14))
    add("输液袋 500 mL(示意)", "SOFT", cyl(XT, YT, ZB + 60, zbag, 8))
    add("滴斗(示意)", "SOFT", cyl(XT, YT, ZB, ZB + 60, DRIP_D))
    add("滴斗传感器夹", "PRINT", drip_clip().rotate((0, 0, 0), (0, 0, 1), 180).translate((XT, YT, ZB + 26)))
    # 夹管阀:固定在主控盒侧面
    zv = BY * 0.45
    add("常闭电磁夹管阀(示意)", "BUY", box(BX / 2, XT + 16, YT - 16, YT + 16, zv - 20, zv + 20)
        .cut(box(XT - 3, XT + 17, YT - 3, YT + 3, zv - 21, zv + 21)))
    # 加温模块:竖着挂在管路上,入口朝上
    zh = -90.0
    tx = XT - (RUN_Y[0] + off)
    hang = lambda s: s.rotate((0, 0, 0), (1, 0, 0), 90).rotate((0, 0, 0), (0, 1, 0), 90).translate((tx, YT + top, zh))
    for n, k, s in heater_module_parts():
        add(n, k, hang(s))
    x_out = tx + RUN_Y[2] + off
    add("输液管", "SOFT", _tube([(XT, YT, ZB), (XT, YT, zh)]))
    add("输液管", "SOFT", _tube([(x_out, YT, zh - ox), (x_out, YT, zh - ox - 60), (x_out + 30, YT - 70, zh - ox - 150), (x_out + 60, YT - 190, zh - ox - 190)]))
    return parts


# 名称 -> (生成函数, 做法, 中文名)
BUILDERS = {
    "01_plate_lower_AL6061": (lambda: plate(False), "CNC", "加温铝板 下板"),
    "02_plate_upper_AL6061": (lambda: plate(True), "CNC", "加温铝板 上板"),
    "03_heater_shell_lower": (lambda: heater_shell(False), "PRINT", "加温模块 下壳"),
    "04_heater_shell_upper": (lambda: heater_shell(True), "PRINT", "加温模块 上壳"),
    "05_drip_sensor_clip": (drip_clip, "PRINT", "滴斗传感器夹"),
    "06_loadcell_mount": (loadcell_mount, "PRINT", "称重传感器固定座"),
    "07_control_box_body": (box_body, "PRINT", "主控盒"),
    "08_control_box_lid": (box_lid, "PRINT", "主控盒盖"),
}
VIEW_ONLY = {
    "00_plates_open_check": (heater_assembly, "VIEW", "上下铝板对合检查(上板抬起 12)"),
    "20_heater_module": (lambda: heater_module_parts(0), "VIEW", "加温模块装配"),
    "21_heater_module_open": (lambda: heater_module_parts(25), "VIEW", "加温模块装配(打开)"),
    "30_full_assembly": (full_assembly, "VIEW", "整机装配"),
}


def export_all(log=print):
    os.makedirs(OUT, exist_ok=True)
    for name, (fn, how, title) in BUILDERS.items():
        part = fn(); solid = part.val(); bb = solid.BoundingBox()
        cq.exporters.export(part, os.path.join(OUT, name + ".step"))
        cq.exporters.export(part, os.path.join(OUT, name + ".stl"), tolerance=0.05, angularTolerance=0.2)
        log(f"{name:26s} {how:5s} {bb.xlen:6.1f} x {bb.ylen:5.1f} x {bb.zlen:5.1f} mm  体积 {solid.Volume() / 1000:7.1f} cm3  valid={solid.isValid()}")


if __name__ == "__main__":
    export_all()
