[← 上一步:接线](../4-electronics/README.md) · [总览](../README.md) · [下一步:软件 →](../6-software/README.md)

# 第 5 步 · 烧录固件

把程序烧进 ESP32。

1. 安装 VS Code 和 PlatformIO 插件,或命令行 `pip install platformio`。
2. 打开本文件夹,编辑 [include/config.h](include/config.h):填 Wi-Fi 名称和密码、服务器电脑的 IP、设备编号。
3. 用 USB 线连接 ESP32,运行:

```
pio run -t upload
pio device monitor
```

在 Windows 上请把本文件夹复制到很短的路径下再编译(例如 `D:\iw\firmware`)。我在一个很深的文件夹里第一次编译时,因为 Windows 路径长度限制而安装库失败,换到短路径后通过。

串口里输入 `help` 可以看到全部测试命令。**第一次上电不要接加热片和夹管阀** ,先做[第 7 步](../7-testing/README.md)的 T1–T3。

## 文件说明

| 文件 | 内容 | 验证情况 |
| --- | --- | --- |
| [include/config.h](include/config.h) | Wi-Fi、服务器地址、引脚、阈值。烧录前必须改 | — |
| [include/logic.h](include/logic.h) | 状态机,滴空、堵管、过温、报警判定 | 电脑上单元测试 40 项通过 |
| [src/main.cpp](src/main.cpp) | 硬件驱动、联网、串口测试命令 | 编译通过;没有在硬件上运行过 |
| [host_test/](host_test/) | 判定逻辑的单元测试,在电脑上跑 | — |

---

[← 上一步:接线](../4-electronics/README.md) · [总览](../README.md) · [下一步:软件 →](../6-software/README.md)
