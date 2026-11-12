# 输液加温监控一体机 · 功能样机 v0.1

输液时在靠近病人的一段管路上用干式铝板给药液加温,同时监测滴速和余量,滴空或异常时自动夹管截停并报警,护士站大屏集中显示每张床的输液情况。

**这是功能样机,用水或生理盐水测试。未取得医疗器械注册证,不能用于病人。** 加温性能数字目前只有计算值,还没有实测;药品加温上限表是演示数据,需要药剂科审核。

## 从哪里看起

| 想做什么 | 看这里 |
|---|---|
| 了解整体方案、文献依据、市场上的同类产品 | `docs/design.html` |
| 采购、接线、烧录、15 步整机测试 | `docs/build-guide.html` |
| 单独验证加温能力的台架试验 | `docs/bench-test.html`,程序和记录表在 `bench/` |
| 把零件发给加工厂 | 图纸 `cad/drawings/IW-drawings.pdf`,模型 `cad/out/*.step`,见下面“发给加工厂” |
| 看整机装配、改零件尺寸 | 运行 `cad/studio.py` |

`docs/` 里的网页直接用浏览器打开。

## 目录

| 路径 | 内容 | 验证情况 |
|---|---|---|
| `server/server.py` | 服务器(Python 标准库,无依赖) | `test_flow.py` 27 项通过 |
| `server/static/` | 配液端、护士站大屏、床旁屏三个页面 | 已在浏览器中查看 |
| `server/simulator.py` | 设备模拟器,没有硬件时用 | 已运行 |
| `firmware/include/logic.h` | 状态机、滴空/堵管/过温/报警判定 | 电脑上单元测试 40 项通过 |
| `firmware/src/main.cpp` | ESP32 硬件驱动、OLED、联网 | PlatformIO 编译通过;未在硬件上运行 |
| `firmware/include/config.h` | Wi-Fi、服务器地址、引脚、阈值 | 烧录前必须修改 |
| `firmware/host_test/` | 判定逻辑单元测试 | — |
| `bench/` | 加温台架试验的控制程序和记录表 | 程序未在硬件上运行 |
| `cad/studio.py` | 三维查看器:整机装配、单个零件、改尺寸、保存导出 | 已运行并在浏览器中操作过 |
| `cad/build.py` | 参数化模型脚本(CadQuery) | 已运行 |
| `cad/drawings/` | 图纸包:8 张 A3 工程图(PDF)和每个零件的 DXF | 已生成并逐页看过;未经加工厂审图 |
| `cad/drawings.py` | 图纸生成脚本,尺寸取自当前参数 | 已运行 |
| `cad/out/` | 8 个零件的 STEP 和 STL | 实体有效,上下板对齐已校验;未实际加工 |

## 快速开始(不需要硬件)

```
cd server
python server.py
python simulator.py http://127.0.0.1:8080 4 20     (另开一个窗口)
```

浏览器打开 `http://127.0.0.1:8080/ward`、`/pharmacy`、`/bedside?dev=IW-001`。

## 看模型、改尺寸

```
pip install cadquery reportlab ezdxf
cd cad
python studio.py        (浏览器打开 http://127.0.0.1:8095)
```

左边列表最下面的“整机装配”是整台设备挂在输液架上的样子,灰色和半透明的部分是外购件和耗材的示意。改完尺寸点“保存并导出”,`cad/out/` 和图纸包会按新尺寸重新生成。

## 发给加工厂

| 零件 | 做法 | 发什么 |
|---|---|---|
| IW-01、IW-02 两片加温铝板 | CNC 铣削,6061-T6 | `cad/drawings/IW-drawings.pdf` 第 1、2 页 + `cad/out/01_*.step`、`02_*.step` |
| IW-03 至 IW-08 外壳、夹具、主控盒 | 3D 打印,PETG | `cad/out/` 里对应的 `.step` 或 `.stl`,图纸第 3 至 8 页供核对尺寸 |

图纸上标了总体尺寸、每个孔的位置直径深度、公差和技术要求,其余形状以同名 STEP 模型为准。`cad/drawings/dxf/` 是三视图的 1:1 线稿,加工厂要二维文件时用。图纸由脚本自动生成,还没有经过加工厂审图,下单前请让对方确认能否按图加工。

## 固件

```
cd firmware            (Windows 上请放在短路径下,例如 D:\iw\firmware)
pio run -t upload
pio device monitor     (输入 help 查看测试命令)
```

## 样机与成品的差别

- 床旁触摸屏用平板浏览器代替,主机上只有一块小 OLED。
- 没有定制电路板,用开发板和现成模块按接线表搭建。
- 不自动调速,只自动截停。
- 单颗 ESP32;成品应拆成安全主控和界面主控两颗。
- 服务器无登录、无加密,只能在测试网络中使用,不要录入真实病人信息。
