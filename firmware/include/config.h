// 样机配置。烧录前改这一页。
#pragma once

// ---- 网络 ----
#define WIFI_SSID     "your-wifi"
#define WIFI_PASS     "your-password"
#define SERVER_URL    "http://192.168.1.100:8080"   // 运行 server.py 的电脑
#define DEVICE_ID     "IW-001"                      // 每台设备不同

// ---- 引脚(ESP32-DevKitC)----
#define PIN_SDA        21   // I2C:ADS1115(0x48);选装 OLED(0x3C)
#define PIN_SCL        22
#define PIN_HX_DT      16   // HX711 称重
#define PIN_HX_SCK     17
#define PIN_DROP       34   // 滴斗光电三极管(模拟输入)
#define PIN_DROP_LED   26   // 滴斗红外发射管
#define PIN_HEAT_PWM   25   // 加热 MOS(低边 PWM)
#define PIN_HEAT_EN    33   // 加热总开关(第二只 MOS 或继电器,高电平接通)
#define PIN_CLAMP      27   // 常闭夹管阀 MOS(通电打开)
#define PIN_BUZZER     14   // 有源蜂鸣器
#define PIN_LED_R      18
#define PIN_LED_Y      23
#define PIN_LED_G      19
#define PIN_BTN_STOP   32   // 暂停/恢复 按键,按下接地
#define PIN_BTN_MUTE   13   // 消音 按键,按下接地
#define PIN_LID        35   // 加温盖干簧管,合盖接地,外接 10k 上拉到 3.3V
#define PIN_AMBIENT    36   // 环境 NTC(10k 分压,NTC 接 3.3V)
#define PIN_VBAT       39   // 电池电压分压(100k:22k)。不接电池时把 HAS_BATTERY 设 0

// ADS1115 通道:A0 板温(控制) A1 板温(保护) A2 出口管壁 A3 接 3.3V 电源(比例测量基准)
#define HAS_SCALE      1    // 0 = 不装称重,只按滴数算余量
#define HAS_BATTERY    0
#define HAS_LID_SWITCH 1
#define HAS_OLED       0    // 1 = 另接一块 0.96 吋 SSD1306 小屏作本机状态显示;默认不用,主显示是触摸屏

// ---- 温度 ----
#define NTC_R0         10000.0f
#define NTC_BETA       3950.0f
#define NTC_R_FIXED    10000.0f
#define OFFSET_PLATE1  0.0f   // 校准后填入(℃)
#define OFFSET_PLATE2  0.0f
#define OFFSET_OUTLET  0.0f
#define OFFSET_AMBIENT 0.0f
#define TEMP_SET_MIN   33.0f
#define PLATE_MAX      41.0f  // 加热面硬上限
#define PLATE_TRIP     42.0f  // 软件过温锁定
#define PLATE_MISMATCH 1.5f   // 两只板温 NTC 允许的最大差值
#define HEAT_DUTY_MAX  1.0f   // 电源电压高于加热片额定电压时调低
#define HEAT_KP        0.35f
#define HEAT_KI        0.012f
#define UA_HX          0.96f  // 换热能力 W/K,台架实测后修改
#define K_LOSS         0.010f // 出口到穿刺点的散热 W/K(25 cm 带保温套的估计值)

// ---- 流量与报警 ----
#define DROP_MIN_DELTA   120    // 液滴信号最小变化量(ADC 计数),用串口 raw 1 观察后调整
#define DROP_REFRACT_MS  70
#define NODROP_MIN_MS    20000  // 至少这么久没有液滴才判停滴
#define START_GRACE_MS   30000  // 开始/恢复后的宽限期
#define LOWVOL_ML        10.0f
#define LOWVOL_FRAC      0.05f
#define FREEFLOW_FACTOR  2.0f
#define FREEFLOW_MS      15000
#define FLOWDEV_FRAC     0.20f
#define FLOWDEV_MS       60000
#define TEMPDEV_C        2.0f
#define TEMPDEV_MS       180000
#define MUTE_MS          120000
#define CLAMP_PULL_MS    300
#define CLAMP_HOLD_DUTY  0.5f
