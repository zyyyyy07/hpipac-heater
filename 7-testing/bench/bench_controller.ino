// 输液加温台架温控程序(ESP32, arduino-esp32 3.x)
// 未经实机编译和运行验证。首次上电先不接加热片,确认温度读数正常。
// 串口 115200 命令:
//   p41            板温固定 41 ℃
//   t37 q120 k0.01 目标温度模式:穿刺点目标 37 ℃,流量 120 mL/h,下游散热 0.01 W/K
//   x              停止加热
#include <Arduino.h>

const int PIN_NTC[3] = {34, 35, 32};   // 控制、保护、上板
const int PIN_HEAT = 25;
const float R_FIXED = 10000.0, R0 = 10000.0, BETA = 3950.0, T0K = 298.15;
float OFFSET[3] = {0, 0, 0};           // S0 校准后填入各传感器偏差(℃)

const float PLATE_MAX = 41.0;          // 板温硬上限
const float TRIP = 42.5;               // 软件过温锁定
const float UA_HX = 0.96;              // 换热器 UA,W/K,试验后改成实测值
const float KP = 0.35, KI = 0.012;     // 占空比/℃,占空比/(℃·s)

enum Mode { OFF, PLATE, TARGET } mode = OFF;
float plateSet = 0, target = 37, flow = 120, kLoss = 0.01;
float integ = 0, duty = 0, T[3];
bool latched = false;
const char *why = "";

float readNTC(int i) {
  uint32_t mv = 0;
  for (int n = 0; n < 16; n++) mv += analogReadMilliVolts(PIN_NTC[i]);
  float v = mv / 16.0 / 1000.0;
  if (v < 0.05 || v > 3.25) return NAN;              // 开路或短路
  float r = R_FIXED * (3.3 - v) / v;                 // NTC 在上臂
  float tk = 1.0 / (1.0 / T0K + log(r / R0) / BETA);
  return tk - 273.15 + OFFSET[i];
}

// 目标温度模式:由流量和散热反推需要的板温
float plateForTarget(float tin) {
  float mc = flow / 3600.0 * 4.18;                   // W/K
  if (mc < 0.005) return target;                     // 停流:只保温
  float out = tin + (target - tin) / exp(-kLoss / mc);   // 补偿下游散热后的出口温度
  float e = exp(-UA_HX / mc);
  float tp = (out - tin * e) / (1.0 - e);            // 需要的板温
  return constrain(tp, target, PLATE_MAX);
}

void trip(const char *reason) {
  latched = true; why = reason; mode = OFF; duty = 0;
  ledcWrite(PIN_HEAT, 0);
}

void parse(String s) {
  s.trim();
  if (s == "x") { mode = OFF; integ = 0; return; }
  if (s.startsWith("p")) {
    plateSet = constrain(s.substring(1).toFloat(), 20.0, PLATE_MAX);
    mode = PLATE; return;
  }
  int i;
  if (s.startsWith("t")) { target = constrain(s.substring(1).toFloat(), 33.0, 41.0); mode = TARGET; }
  if ((i = s.indexOf('q')) >= 0) flow = s.substring(i + 1).toFloat();
  if ((i = s.indexOf('k')) >= 0) kLoss = s.substring(i + 1).toFloat();
}

void setup() {
  Serial.begin(115200);
  ledcAttach(PIN_HEAT, 1000, 10);      // 1 kHz, 10 位
  ledcWrite(PIN_HEAT, 0);
  Serial.println("ms,ntc1,ntc2,ntc3,plate_set,duty_pct,state");
}

void loop() {
  static uint32_t last = 0;
  if (Serial.available()) parse(Serial.readStringUntil('\n'));
  if (millis() - last < 1000) return;
  last = millis();

  for (int i = 0; i < 3; i++) T[i] = readNTC(i);

  if (!latched) {
    for (int i = 0; i < 3; i++) {
      if (isnan(T[i]) || T[i] < 0 || T[i] > 60) trip("sensor");
      else if (T[i] >= TRIP) trip("overtemp");
    }
    if (!latched && fabs(T[0] - T[1]) > 1.5) trip("mismatch");
  }

  if (!latched && mode != OFF) {
    if (mode == TARGET) plateSet = plateForTarget(22.0);   // 进液温度暂按 22 ℃,可改为实测
    float err = plateSet - T[0];
    integ = constrain(integ + KI * err, 0.0, 1.0);
    if (err < -0.5) integ = 0;                             // 超过设定即清积分
    duty = constrain(KP * err + integ, 0.0, 1.0);
  } else {
    duty = 0;
  }
  ledcWrite(PIN_HEAT, (uint32_t)(duty * 1023));

  Serial.printf("%lu,%.2f,%.2f,%.2f,%.2f,%.0f,%s\n", (unsigned long)millis(), T[0], T[1], T[2],
                plateSet, duty * 100,
                latched ? why : (mode == OFF ? "off" : (mode == PLATE ? "plate" : "target")));
}
