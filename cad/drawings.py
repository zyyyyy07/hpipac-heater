#!/usr/bin/env python3
"""生成加工图纸:两片铝板的带尺寸二维图(SVG),并合成一个网页。尺寸取自 build.py 的当前参数。
运行: python drawings.py   输出: drawings/plate_lower.svg, drawings/plate_upper.svg, ../docs/parts-drawings.html
"""
import os
import build as b

HERE = os.path.dirname(os.path.abspath(__file__))
DR = os.path.join(HERE, "drawings"); os.makedirs(DR, exist_ok=True)
S = 3.6           # 俯视图比例 px/mm
OX, OY = 90, 70   # 俯视图左上角


def plate_svg(upper):
    mir = (lambda p: (p[0], b.PW - p[1])) if upper else (lambda p: p)
    X = lambda x: OX + x * S
    Y = lambda y: OY + (b.PW - y) * S          # y 向上
    runs = [b.PW - v for v in b.RUN_Y] if upper else list(b.RUN_Y)
    xr, xl, R = b.PL - b.TURN_X, b.TURN_X, b.BEND_R
    sw = 0 if runs[0] > runs[1] else 1         # 圆弧方向
    path = (f"M{X(0)} {Y(runs[0])} H{X(xr)} A{R*S} {R*S} 0 0 {1-sw} {X(xr)} {Y(runs[1])} "
            f"H{X(xl)} A{R*S} {R*S} 0 0 {sw} {X(xl)} {Y(runs[2])} H{X(b.PL)}")
    screws = [mir(p) for p in b.SCREWS]; dowels = [mir(p) for p in b.DOWELS]
    ntc = b.NTC_X if not upper else b.NTC_X[:1]
    o = []
    W, H = max(1000, int(OX + b.PL * S + 70)), int(OY + b.PW * S + 460)
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" font-family="Arial,Microsoft YaHei,sans-serif" font-size="12">')
    o.append(f'<rect width="{W}" height="{H}" fill="#fff"/><rect x="8" y="8" width="{W-16}" height="{H-16}" fill="none" stroke="#000" stroke-width="1.5"/>')
    name = "上板" if upper else "下板"
    o.append(f'<text x="24" y="36" font-size="18" font-weight="bold">加温铝板 · {name}(槽面视图) 比例示意,以标注尺寸和 STEP 模型为准</text>')
    # 外形、槽
    o.append(f'<rect x="{X(0)}" y="{Y(b.PW)}" width="{b.PL*S}" height="{b.PW*S}" fill="#eef3f5" stroke="#000" stroke-width="1.8"/>')
    o.append(f'<path d="{path}" fill="none" stroke="#9cc6d2" stroke-width="{4*S}"/>')
    o.append(f'<path d="{path}" fill="none" stroke="#000" stroke-width="0.8" stroke-dasharray="14 4 3 4"/>')
    # 孔
    for x, y in screws:
        o.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="{(1.7 if upper else 1.25)*S}" fill="#fff" stroke="#000" stroke-width="1.2"/>')
        o.append(f'<path d="M{X(x)-9} {Y(y)} H{X(x)+9} M{X(x)} {Y(y)-9} V{Y(y)+9}" stroke="#000" stroke-width="0.5"/>')
    for x, y in dowels:
        o.append(f'<circle cx="{X(x)}" cy="{Y(y)}" r="{1.5*S}" fill="#000"/>')
    for x in ntc:
        o.append(f'<rect x="{X(x)-1.1*S}" y="{Y(20)}" width="{2.2*S}" height="{20*S}" fill="none" stroke="#c0392b" stroke-width="1" stroke-dasharray="5 3"/>')
    # 坐标标注:下方 X,左侧 Y
    xs = sorted(set([0, xl, xr, b.PL] + [p[0] for p in screws + dowels] + list(ntc)))
    ys = sorted(set([0, b.PW] + runs + [p[1] for p in screws + dowels]))
    yb = Y(0) + 16
    for i, x in enumerate(xs):
        lvl = yb + (i % 2) * 16
        o.append(f'<path d="M{X(x)} {Y(0)+3} V{lvl+2}" stroke="#555" stroke-width="0.6"/><text x="{X(x)}" y="{lvl+15}" text-anchor="middle">{x:g}</text>')
    for i, y in enumerate(ys):
        lx = X(0) - 14 - (i % 2) * 26
        o.append(f'<path d="M{X(0)-3} {Y(y)} H{lx}" stroke="#555" stroke-width="0.6"/><text x="{lx-4}" y="{Y(y)+4}" text-anchor="end">{y:g}</text>')
    o.append(f'<text x="{X(0)-60}" y="{Y(0)+50}" font-size="11" fill="#555">坐标原点:左下角</text>')
    o.append(f'<text x="{X(xr)+R*S+6}" y="{Y((runs[0]+runs[1])/2)+4}">R{R:g}</text><text x="{X(xl)-R*S-30}" y="{Y((runs[1]+runs[2])/2)+4}">R{R:g}</text>')
    o.append(f'<text x="{X(100)}" y="{Y(runs[1])-12}" text-anchor="middle" fill="#0a6f83">槽中心线(点划线),全长 {b.groove_length():.0f}</text>')
    o.append(f'<text x="{X(4)}" y="{Y(runs[0])-10}" fill="#0a6f83">进液 →</text><text x="{X(b.PL)-60}" y="{Y(runs[2])+{True:20,False:-10}[runs[2]<10]}" fill="#0a6f83">→ 出液</text>')
    o.append(f'<text x="{X(ntc[0])+10}" y="{Y(12)}" fill="#c0392b">测温孔(虚线,从此长边钻入)</text>')
    # 槽截面详图 10:1
    cx, k = 130, 10
    cy = int(OY + b.PW * S + 300)
    o.append(f'<text x="24" y="{cy - b.PT*k - 52}" font-size="14" font-weight="bold">槽截面 A(10:1)</text>')
    half = (b.GROOVE_R**2 - (b.GROOVE_R - b.GROOVE_DEPTH)**2) ** 0.5
    top, bot = cy - b.PT * k, cy
    o.append(f'<path d="M{cx-90} {top} H{cx-half*k} A{b.GROOVE_R*k} {b.GROOVE_R*k} 0 0 0 {cx+half*k} {top} H{cx+90} V{bot} H{cx-90} Z" fill="#eef3f5" stroke="#000" stroke-width="1.5"/>')
    o.append(f'<circle cx="{cx}" cy="{top + (b.PT - b.NTC_Z)*k}" r="{1.1*k}" fill="#fff" stroke="#c0392b" stroke-dasharray="5 3"/>')
    o.append(f'<path d="M{cx+110} {top} V{bot} M{cx+104} {top} H{cx+116} M{cx+104} {bot} H{cx+116}" stroke="#555" fill="none"/><text x="{cx+120}" y="{(top+bot)/2+4}">板厚 {b.PT:g}</text>')
    o.append(f'<path d="M{cx} {top} V{top+b.GROOVE_DEPTH*k}" stroke="#555"/><text x="{cx-88}" y="{top-28}">R{b.GROOVE_R:g} 球头刀,槽深 {b.GROOVE_DEPTH:g}(+0.05 / 0)</text>')
    o.append(f'<text x="{cx-88}" y="{top-10}">槽口宽 {2*half:.2f},倒角 C0.2 去毛刺</text>')
    o.append(f'<text x="{cx-88}" y="{bot+20}" fill="#c0392b">测温孔 Ø2.2 深 20,孔中心距槽面 {b.PT - b.NTC_Z:.2f}</text>')
    # 孔表与技术要求
    tx = 400; ty = OY + b.PW * S + 130
    o.append(f'<text x="{tx}" y="{ty}" font-size="14" font-weight="bold">孔表</text>')
    rows = [("4 ×", "Ø3.4 通孔" if upper else "Ø2.5 通孔,攻 M3", " ".join(f"({x:g},{y:g})" for x, y in screws)),
            ("2 ×", "Ø3 H7 通孔(定位销)", " ".join(f"({x:g},{y:g})" for x, y in dowels)),
            (f"{len(ntc)} ×", "Ø2.2 深 20,自 y=0 长边钻入", " ".join(f"x={x:g}" for x in ntc) + f",z=距槽面 {b.PT - b.NTC_Z:.2f}")]
    for i, (n, d, p) in enumerate(rows):
        o.append(f'<text x="{tx}" y="{ty+22+i*20}">{n}</text><text x="{tx+34}" y="{ty+22+i*20}">{d}</text><text x="{tx+250}" y="{ty+22+i*20}">{p}</text>')
    notes = ["技术要求", "1. 材料 6061-T6 铝合金,数量 1。", f"2. 外形 {b.PL:g} × {b.PW:g} × {b.PT:g},未注公差 ±0.1。",
             "3. 槽面(合模面)平面度 0.05,槽内粗糙度 Ra ≤1.6。", "4. 槽中心线位置度 0.1(上下板合模后槽须对齐)。",
             "5. 锐边倒钝 C0.3。样机阶段不做表面处理;成品做硬质阳极氧化。", "6. 上板与下板为镜像件,不可互换,请分别按各自 STEP 加工。"]
    for i, t in enumerate(notes):
        o.append(f'<text x="{tx}" y="{ty+100+i*20}" {"font-size=\"14\" font-weight=\"bold\"" if i == 0 else ""}>{t}</text>')
    o.append(f'<text x="{W-24}" y="{H-22}" text-anchor="end" font-size="11" fill="#555">输液加温监控一体机 样机 v0.1 · {"02_plate_upper" if upper else "01_plate_lower"}_AL6061.step · 单位 mm</text>')
    o.append("</svg>")
    return "\n".join(o)


def write_all():
    """按当前参数重新生成两张铝板加工图和图纸网页。"""
    lower, upper = plate_svg(False), plate_svg(True)
    open(os.path.join(DR, "plate_lower.svg"), "w", encoding="utf-8").write(lower)
    open(os.path.join(DR, "plate_upper.svg"), "w", encoding="utf-8").write(upper)
    html = open(os.path.join(HERE, "drawings_template.html"), encoding="utf-8").read()
    html = html.replace("{{LOWER}}", lower).replace("{{UPPER}}", upper)
    out = os.path.normpath(os.path.join(HERE, "..", "docs", "parts-drawings.html"))
    open(out, "w", encoding="utf-8").write(html)
    return out


if __name__ == "__main__":
    print("written", write_all())
