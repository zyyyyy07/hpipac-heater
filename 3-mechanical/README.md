[← 上一步:采购](../2-purchase/README.md) · [总览](../README.md) · [下一步:接线 →](../4-electronics/README.md)

# 第 3 步 · 加工铝件、打印外壳

这一步把 9 种定制零件做出来:三件铝件找 CNC 加工厂,六种塑料件 3D 打印(注射筒加热套半壳要做 2 件)。

**下单前先量三个尺寸,在三维查看器里改成实测值再导出**:注射筒外径、高压管外径、加湿罐底面直径。默认值是我估的,不是按某个具体型号量的。

| 图号 | 零件 | 文件 | 做法 | 说明 |
| --- | --- | --- | --- | --- |
| HP-01 | 保温铝板 下板 | [models/cnc/](models/cnc/)`01_line_plate_lower_AL6061.step` | CNC,6061 铝 | 三折槽夹住高压管。4 个 Ø2.5 孔攻 M3,侧面 2 个测温孔 |
| HP-02 | 保温铝板 上板 | [models/cnc/](models/cnc/)`02_line_plate_upper_AL6061.step` | CNC,6061 铝 | 与下板镜像 |
| HP-03 | 保温板 下壳 | [models/print/](models/print/)`03_line_shell_lower.stl` | 3D 打印 | 一侧有两个绑带耳 |
| HP-04 | 保温板 上壳 | [models/print/](models/print/)`04_line_shell_upper.stl` | 3D 打印 | |
| HP-05 | 注射筒加热套 半壳 | [models/print/](models/print/)`05_syringe_jacket_half.stl` | 3D 打印,**做 2 件** | 两片对扣包住针筒,内贴硅胶加热片和保温棉 |
| HP-06 | 加湿铝盘 | [models/cnc/](models/cnc/)`06_humidifier_plate_AL6061.step` | CNC,6061 铝 | 上面放加湿罐,下面贴加热片。3 个 M3 沉头孔,侧面 2 个测温孔 |
| HP-07 | 加湿底座 | [models/print/](models/print/)`07_humidifier_base.stl` | 3D 打印,PETG 或耐温 ABS | 托住铝盘,里面走线 |
| HP-08 | 主控盒 | [models/print/](models/print/)`08_control_box_body.stl` | 3D 打印 | 侧面 7 个航空插座孔 |
| HP-09 | 主控盒盖 | [models/print/](models/print/)`09_control_box_lid.stl` | 3D 打印 | 7 英寸触摸屏窗、3 个指示灯、中止键、消音键、蜂鸣器 |

## 发给加工厂

- 图纸是 [drawings/HP-drawings.pdf](drawings/HP-drawings.pdf),每个零件一张 A3,含三视图、孔表、公差和技术要求。二维线稿在 [drawings/dxf/](drawings/dxf/)。
- 铝件发图纸第 1、2、6 页,加 `models/cnc/` 里的三个 STEP。
- 打印件发 `models/print/` 里的 STL 或 STEP。
- 图纸由脚本生成,没有经过加工厂审图,下单前请对方确认能否按图加工。
- 给 CNC 厂的要求:槽用球头刀,槽面 Ra ≤1.6,槽口去毛刺,合模面平面度 0.05。

## 看模型和改尺寸

```
pip install cadquery reportlab ezdxf
cd 3-mechanical/tools
python studio.py        (浏览器打开 http://127.0.0.1:8095)
```

可以旋转、剖切、拖滑块改尺寸。左边列表下方有装配视图:高压管保温板、注射筒加热套、加湿加热底座、手术室整体布置。点“保存并导出”后模型和图纸按新尺寸重新生成。

## 装配要点

- **高压管保温板**:铝板只接触高压管外壁。高压管压进下板的槽里,合上上板,拧 4 颗 M3。保温板用绑带穿过下壳的两个耳固定在手术台边,**不能吊在高压管上**,高压管两端留松弛。硬的编织高压管可能弯不到默认的 15 mm 半径,先拿实物试弯,不行就在查看器里加大“高压管转弯半径”。
- **注射筒加热套**:硅胶加热片贴在一片半壳内侧,外面垫保温棉;两只测温探头贴在加热片和针筒之间。两片对扣后用 M3 螺丝或绑带固定。不要挡住注射器的活塞行程和针筒刻度。
- **加湿加热底座**:加热片贴在铝盘底面,铝盘用 3 颗 M3 沉头螺丝固定在底座上,中间垫硅胶隔热垫。铝盘最高到 85 ℃,底座外壁会热,放在托板上不要靠人。
- **主控盒**:模块的固定位置按实物在盒底打孔或贴双面胶。

以上装配方式都没有做过实物验证。

---

[← 上一步:采购](../2-purchase/README.md) · [总览](../README.md) · [下一步:接线 →](../4-electronics/README.md)
