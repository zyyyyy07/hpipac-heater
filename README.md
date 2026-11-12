# 输液加温监控一体机 · 功能样机 v0.1

输液时在靠近病人的一段管路上用干式铝板给药液加温,同时监测滴速和余量,滴空或异常时自动夹管截停并报警,护士站大屏集中显示每张床的输液情况。

**这是功能样机,用水或生理盐水测试。未取得医疗器械注册证,不能用于病人。** 加温性能只有计算值,没有做过热仿真、受力仿真或实测;药品加温上限表是演示数据,需要药剂科审核。

## 按步骤做

从上到下一步一步来,每一步点进去是那一步的说明和文件。

| 步骤 | 做什么 | 文件夹 | 需要硬件吗 |
| --- | --- | --- | --- |
| 1 | [了解方案](1-design/README.md):为什么这样设计、文献依据、市面上的同类产品 | [1-design/](1-design/) | 不需要 |
| 2 | [采购](2-purchase/README.md):清单、规格、大致价格 | [2-purchase/](2-purchase/) | — |
| 3 | [加工铝板、打印外壳](3-mechanical/README.md):图纸、三维模型、怎么发给加工厂 | [3-mechanical/](3-mechanical/) | — |
| 4 | [接线](4-electronics/README.md):电源回路、接线表、触摸屏和树莓派 | [4-electronics/](4-electronics/) | 需要 |
| 5 | [烧录固件](5-firmware/README.md):ESP32 程序 | [5-firmware/](5-firmware/) | 需要 |
| 6 | [架服务器、设置触摸屏](6-software/README.md):配液端、护士站大屏、床旁屏 | [6-software/](6-software/) | 不需要 |
| 7 | [分步测试](7-testing/README.md):T1 到 T16,从上电自检到整机联网 | [7-testing/](7-testing/) | 需要 |

等零件到货的时候可以先做第 6 步,用模拟设备把整套软件跑起来看效果。

## 每个文件夹里是什么

| 文件夹 | 内容 |
| --- | --- |
| [1-design/](1-design/) | 设计方案 |
| [2-purchase/](2-purchase/) | 采购清单 |
| [3-mechanical/drawings/](3-mechanical/drawings/) | 发给加工厂的图纸:8 张 A3 工程图(PDF)和每个零件的 DXF |
| [3-mechanical/models/cnc/](3-mechanical/models/cnc/) | 要 CNC 加工的两片铝板(STEP) |
| [3-mechanical/models/print/](3-mechanical/models/print/) | 要 3D 打印的六个零件(STL 和 STEP) |
| [3-mechanical/tools/](3-mechanical/tools/) | 模型脚本、图纸脚本、三维查看器 |
| [4-electronics/](4-electronics/) | 电路:电源回路图和接线表(没有定制电路板) |
| [5-firmware/](5-firmware/) | ESP32 固件 |
| [6-software/](6-software/) | 服务器、四个网页、设备模拟器、树莓派开机全屏脚本 |
| [7-testing/](7-testing/) | 整机分步测试、安全说明、已知风险 |
| [7-testing/bench/](7-testing/bench/) | 单独验证加温能力的台架试验方案、控制程序、记录表 |

## 不用硬件先看效果

软件界面:

```
cd 6-software
python server.py
python simulator.py http://127.0.0.1:8080 4 20     (另开一个窗口)
```

浏览器打开 `http://127.0.0.1:8080/ward`(护士站大屏)、`/pharmacy`(配液端)、`/bedside?dev=IW-001`(床旁屏)、`/panel?dev=IW-001`(主机正面的触摸屏、指示灯和按键)。

三维模型和整机装配:

```
pip install cadquery reportlab ezdxf
cd 3-mechanical/tools
python studio.py        (浏览器打开 http://127.0.0.1:8095)
```

## 哪些验证过,哪些没有

| 内容 | 验证情况 |
| --- | --- |
| 服务器和四个网页 | 已运行,全流程自测 27 项通过,页面用模拟设备操作过 |
| 固件判定逻辑(滴空、堵管、过温、报警) | 电脑上单元测试 40 项通过 |
| 固件硬件驱动 | 编译通过;没有在真实硬件上运行过 |
| 三维模型 | 实体有效,上下铝板对齐已用程序校验;没有实际加工或打印过 |
| 图纸 | 已生成并逐页看过;没有经过加工厂审图 |
| 加温能力、外壳温度 | 只有稳态计算;没有热仿真,没有实测 |
| 加温模块的固定和受力 | 只按重量和标准估算;没有受力仿真,没有实测 |
| 树莓派开机全屏脚本 | 没有在真机上运行过 |

## 样机与成品的差别

- 触摸屏由盒内的树莓派驱动,显示的是服务器上的网页,断网时不更新;成品应把界面做进嵌入式固件。
- 没有定制电路板,用开发板和现成模块按接线表搭建。
- 不自动调速,只自动截停。
- 单颗 ESP32;成品应拆成安全主控和界面主控两颗。
- 用 12 V 适配器供电,没有电池。
- 服务器无登录、无加密,只能在测试网络中使用,不要录入真实病人信息。
