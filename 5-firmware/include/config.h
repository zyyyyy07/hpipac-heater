// hPIPAC 前端加热系统 · 样机配置。烧录前改这一页。
// 字段、阶段、报警的含义见 1-design/interface-spec.md。
#pragma once

// ---- 网络 ----
#define WIFI_SSID     "your-wifi"
#define WIFI_PASS     "your-password"
#define SERVER_URL    "http://192.168.1.100:8080"   // 运行服务器程序的电脑
#define DEVICE_ID     "HP-001"                      // 每台设备不同

// ---- 引脚(ESP32-DevKitC,WROOM-32 模组)----
// 没有使用启动配置脚(0、2、5、12、15)。
#define PIN_SDA         21   // I2C:三片 ADS1115(0x48、0x49、0x4A)
#define PIN_SCL         22
#define PIN_HEAT_SYR    25   // 注射筒加热套 MOS(低边 PWM,高电平导通)
#define PIN_HEAT_LINE   26   // 高压管保温板 MOS
#define PIN_HEAT_HUM    27   // 加湿加热底座 MOS
#define PIN_HEAT_TUBE   17   // 加热输气管 MOS
#define PIN_HEAT_EN     33   // 加热总开关 MOS(串在四路加热的电源上,高电平接通)
#define PIN_PUMP        16   // 循环泵 PWM(高电平 = 转)
#define PIN_BUZZER       4   // 有源蜂鸣器
#define PIN_LED_R       18
#define PIN_LED_Y       23
#define PIN_LED_G       19
#define PIN_BTN_ABORT   32   // 暂停(中止)按键,按下接地
#define PIN_BTN_MUTE    13   // 消音按键,按下接地
#define PIN_LID         35   // 高压管保温板合盖干簧管,合盖接地,外接 10k 上拉到 3.3V(GPIO35 没有内部上拉)
// 五只 MOS 的栅极和 PIN_HEAT_EN 都要各接一只 10k 下拉电阻:ESP32 复位或没上电时输出保持关断。

// ---- ADS1115 通道分配 ----
// 十只 NTC(10k B3950)都是同一种分压:3.3V — NTC — 测量点 — 10k 固定电阻 — GND。
// 比例测量:U1 的 A3 直接接 3.3V 电源,读出的电压作为全部 NTC 的基准,电源波动不影响温度读数。
// 每一路的“控制”和“保护”两只传感器故意放在不同的芯片上,一片 ADS1115 出错时两只读数会对不上。
//
// | 芯片 | 地址 | ADDR 脚接 | A0      | A1    | A2       | A3              |
// | ---- | ---- | --------- | ------- | ----- | -------- | --------------- |
// | U1   | 0x48 | GND       | syr1    | line1 | humOut   | 3.3V 基准       |
// | U2   | 0x49 | 3.3V      | syr2    | line2 | humPlate | gasEnd          |
// | U3   | 0x4A | SDA       | lineOut | ip1   | ip2      | press(经分压) |
//
// 压力传感器:0–50 mmHg,5 V 供电,输出 0.5–4.5 V。输出经 10k(上)/20k(下)分压成 0.33–3.0 V 后接 U3 的 A3。
// 选 ADS1115 而不是 ESP32 自带 ADC:自带 ADC 非线性大,而且 Wi-Fi 工作时 ADC2 不能用。
// 传感器输出与它的 5 V 供电成比例,固件没有测 5 V,5 V 的误差会按比例带进压力读数。
#define ADS_ADDR_1      0x48
#define ADS_ADDR_2      0x49
#define ADS_ADDR_3      0x4A

// ---- 选装件 ----
#define HAS_PRESSURE    1    // 0 = 没装压力传感器:press 上报 null,压力报警不起作用
#define HAS_IP_PROBES   1    // 0 = 没装腹腔温度探头:ip1/ip2 上报 null,READY 只能用 ready 命令手动确认
#define HAS_LID_SWITCH  1    // 0 = 没装合盖开关:按“已合盖”处理,LID 报警不起作用

// ---- 温度传感器 ----
#define NTC_R0          10000.0f
#define NTC_BETA        3950.0f
#define NTC_R_FIXED     10000.0f
#define OFFSET_SYR1     0.0f   // 校准后填入(℃)
#define OFFSET_SYR2     0.0f
#define OFFSET_LINE1    0.0f
#define OFFSET_LINE2    0.0f
#define OFFSET_LINEOUT  0.0f
#define OFFSET_HUMPLATE 0.0f
#define OFFSET_HUMOUT   0.0f
#define OFFSET_GASEND   0.0f
#define OFFSET_IP1      0.0f
#define OFFSET_IP2      0.0f

// ---- 压力传感器 ----
#define PRESS_DIVIDER   1.5f   // 分压还原系数 = (10k + 20k) / 20k
#define PRESS_V_ZERO    0.5f   // 0 mmHg 时的输出电压
#define PRESS_V_SPAN    4.0f   // 满量程电压跨度(0.5–4.5 V)
#define PRESS_RANGE     50.0f  // 满量程 mmHg
#define OFFSET_PRESS    0.0f   // 校准后填入(mmHg)

// ---- 循环泵 ----
// 没有接转速反馈。流量是按占空比估算的:flow = 占空比 × PUMP_LPM_AT_FULL。
// PUMP_LPM_AT_FULL 要接上整条回路(过滤器、加湿罐、输气管)用流量计实测后修改。
#define PUMP_LPM_AT_FULL 15.0f
#define FLOW_MAX         15.0f
#define FLOW_DEFAULT     10.0f

// ---- 目标温度与上限(与接口约定一致,不要随意改)----
#define TARGET_MIN      37.0f
#define TARGET_MAX      43.0f
#define TARGET_DEFAULT  42.0f
#define DRUG_SET_MAX    43.0f  // 药液通路(SYR、LINE)设定值和加热面的硬上限
#define DRUG_TRIP       43.8f  // OVERTEMP_DRUG
#define GAS_END_MAX     43.5f  // 病人端气温上限:到这个值 TUBE 输出归零
#define GAS_END_TRIP    44.5f  // OVERTEMP_GAS
#define HUM_OUT_MAX     45.0f  // 加湿罐出口气温上限:到这个值 HUM 输出归零
#define HUM_OUT_TRIP    46.0f  // OVERTEMP_GAS
#define HUM_PLATE_MAX   85.0f  // 加湿底座上限:到这个值 HUM 输出归零
#define HUM_PLATE_STANDBY 60.0f // 循环泵不转时的底座待机上限(没有气流,不把底座烧高)
#define HUM_PLATE_FOLD  5.0f   // 底座温度进入上限以下这么多度时,HUM 输出开始按比例收小
#define HUM_PLATE_TRIP  88.0f  // OVERTEMP_GAS
#define HUM_OVER_TARGET 1.0f   // 加湿罐出口气温设定 = 目标 + 1 ℃
#define IP_HIGH_TRIP    43.5f
#define IP_HIGH_CLEAR   42.5f

// ---- 报警判定 ----
#define PAIR_MISMATCH   1.5f     // 成对传感器允许的最大差值
#define MISMATCH_MS     10000
#define SENSOR_NULL_MS  1000     // 传感器读不到持续这么久才锁定 SENSOR(期间该路输出已经是零)
#define PRESS_HIGH_MMHG 18.0f
#define PRESS_HIGH_MS   3000
#define PRESS_LOW_MMHG  6.0f
#define PRESS_LOW_MS    5000
#define PRESS_EST_MMHG  8.0f     // PREHEAT 中压力到这个值(气腹已建立)泵才开始循环
#define WATER_PUMP_MS   120000   // 泵连续运转满这么久才开始判 WATER_LOW
#define WATER_PLATE_C   75.0f
#define WATER_DELTA_C   3.0f
#define WATER_MS        120000
#define PREHEAT_SLOW_MS 3600000
#define IP_LOW_DELTA_C  2.0f
#define IP_LOW_MS       300000
#define MUTE_MS         120000

// ---- 阶段 ----
#define READY_BAND_C     0.5f    // SYR、LINE 到温判定:目标 ±0.5 ℃
#define READY_GAS_DELTA  1.0f    // gasEnd ≥ 目标 − 1 ℃
#define READY_IP_DELTA   1.0f    // 腹腔平均温度 ≥ 目标 − 1 ℃
#define READY_LOST_MS    60000   // READY 条件失去这么久掉回 PREHEAT
#define EXPOSE_MIN_DEFAULT 30
#define EXPOSE_MIN_MIN   1
#define EXPOSE_MIN_MAX   60

// ---- 加热控制(PI,输出占空比 0–1;台架实测后调整)----
#define CONTROL_DT      0.2f     // 控制周期,秒
#define SYR_KP          0.35f
#define SYR_KI          0.012f
#define LINE_KP         0.35f
#define LINE_KI         0.012f
#define HUM_KP          0.20f
#define HUM_KI          0.004f
#define TUBE_KP         0.30f
#define TUBE_KI         0.010f
#define SYR_DUTY_MAX    1.0f     // 电源电压高于加热件额定电压时调低
#define LINE_DUTY_MAX   1.0f
#define HUM_DUTY_MAX    1.0f
#define TUBE_DUTY_MAX   1.0f

// ---- 串口手动测试 ----
#define MANUAL_TIMEOUT_MS 600000 // heat / pump 手动输出 10 分钟后自动关
