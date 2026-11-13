[← 上一步:接线](../4-electronics/README.md) · [总览](../README.md) · [下一步:软件 →](../6-software/README.md)

# 第 5 步 · 烧录固件

把 hPIPAC 前端加热系统的主控程序烧进 ESP32。程序负责四路加热(SYR、LINE、HUM、TUBE)、循环泵、报警,以及每 2 秒向服务器上报一次。字段、阶段、报警的定义见[接口约定](../1-design/interface-spec.md)。

## 烧录

1. 安装 VS Code 和 PlatformIO 插件,或命令行 `pip install platformio`。
2. 打开本文件夹,编辑 [include/config.h](include/config.h)(见下一节)。
3. 用 USB 线连接 ESP32,运行:

```
pio run -t upload
pio device monitor
```

在 Windows 上请把本文件夹复制到很短的路径下再编译(例如 `D:\hp\firmware`)。文件夹太深时会因为 Windows 路径长度限制而安装库失败。

**第一次上电不要接加热件和循环泵** ,先按[第 7 步](../7-testing/README.md)用串口命令逐项检查传感器读数和报警。

## config.h 里要改的内容

| 项目 | 说明 |
| --- | --- |
| `WIFI_SSID`、`WIFI_PASS` | Wi-Fi 名称和密码 |
| `SERVER_URL` | 运行服务器程序的电脑地址,例如 `http://192.168.1.100:8080` |
| `DEVICE_ID` | 设备编号,默认 `HP-001`,每台不同 |
| `HAS_PRESSURE`、`HAS_IP_PROBES`、`HAS_LID_SWITCH` | 没装压力传感器、腹腔温度探头、合盖开关时设为 0 |
| `OFFSET_*` | 每只温度传感器和压力传感器的校准偏差,校准后填入 |
| `PUMP_LPM_AT_FULL` | 循环泵满占空比时的流量。固件没有流量计,上报的 `flow` 是按占空比估算的,这个数要接上整条回路实测后修改 |
| `*_KP`、`*_KI`、`*_DUTY_MAX` | 各路加热的 PI 参数和最大占空比,台架实测后调整 |

引脚和三片 ADS1115 的通道分配表也在 config.h 里,接线要和它一致。温度上限和报警阈值与接口约定一致,不要随意改。

## 串口测试命令

串口 115200,输入 `help` 可以看到全部命令。

| 命令 | 作用 |
| --- | --- |
| `status` | 打印一次全部读数、设定值、占空比、报警 |
| `log 1` / `log 0` | 每秒输出一行 CSV / 停止 |
| `heat <syr\|line\|hum\|tube> <占空比%>` | 手动给一路加热,只在 IDLE 可用。过温保护照常起作用;`0` 关闭;10 分钟后自动关 |
| `pump <占空比%>` | 手动转循环泵,只在 IDLE 可用;`0` 关闭 |
| `preheat`、`ready`、`nebulize`、`expose`、`evac`、`finish`、`abort` | 与服务器下发的同名命令相同 |
| `target <37.0–43.0>`、`flow <0–15>`、`exposeMin <1–60>`、`circInExpose <1\|0>` | 改设定值,超范围会被拒绝 |
| `ack`、`mute` | 确认可恢复的报警、消音 2 分钟 |

每条命令都会回一行 `OK …` 或 `ERR …`。阶段和报警有变化时串口也会打印一行。

几点要知道的行为:

- 上电、复位、看门狗复位后,四路加热、加热总开关、循环泵都是关的,阶段回到 IDLE。
- PREHEAT 中循环泵要等 `press` 到 8 mmHg(气腹已建立)才转,之前不转也不报警;`HAS_PRESSURE` 为 0 时不等。
- 循环泵不转时,HUM 底座上限从 85 ℃ 降到 60 ℃;`WATER_LOW` 只在泵连续转满 120 秒后才判。
- `finish` 要发两次:第一次 EVAC → DONE,第二次 DONE → IDLE。
- 面板上的暂停(中止)键在 PREHEAT 到 EXPOSE 之间按下等于 `abort`。
- `OVERTEMP_DRUG`、`OVERTEMP_GAS`、`SENSOR` 是锁定报警,只有重新上电才能清除;锁定期间不能开始预热。
- `SENSOR` 只在某一路要加热时才判。IDLE 时传感器没接不会报警,但一发 `preheat` 或 `heat`,1 秒内就会锁定。

## 文件说明

| 文件 | 内容 | 验证情况 |
| --- | --- | --- |
| [include/config.h](include/config.h) | Wi-Fi、服务器地址、引脚、ADS1115 通道分配、阈值。烧录前必须改 | 随固件一起编译通过 |
| [include/logic.h](include/logic.h) | 阶段转换、报警判定、各路设定值、PI 控制。不依赖硬件 | 电脑上单元测试 223 项全部通过 |
| [src/main.cpp](src/main.cpp) | 传感器读取、PWM 输出、指示灯和蜂鸣器、联网、串口测试命令 | 编译通过(RAM 15.5%,Flash 39.5%);没有在硬件上运行过 |
| [host_test/test_logic.cpp](host_test/test_logic.cpp) | logic.h 的单元测试,在电脑上跑 | 223 项全部通过 |
| [platformio.ini](platformio.ini) | 编译配置和依赖库 | 编译通过 |

没有验证过的部分:固件没有烧进过真实的电路板;传感器换算、PWM 输出、按键、指示灯、与服务器的实际通信都没有实测;PI 参数和 `PUMP_LPM_AT_FULL` 是初始估计值。

在电脑上重跑单元测试(在本文件夹下):

```
g++ -std=c++17 -Iinclude host_test/test_logic.cpp -o test_logic
./test_logic
```

最后一行是 `ALL PASS (223 checks)` 即为通过。

---

[← 上一步:接线](../4-electronics/README.md) · [总览](../README.md) · [下一步:软件 →](../6-software/README.md)
