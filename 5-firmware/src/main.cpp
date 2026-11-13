// hPIPAC 前端加热系统 · 样机主控固件(ESP32-DevKitC,Arduino 框架)
// 本文件只做硬件读写、指示和联网;所有判定逻辑在 include/logic.h。
// 串口 115200 命令(整机分步测试用,输入 help 查看)。
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <ArduinoJson.h>
#include <Adafruit_ADS1X15.h>
#include <esp_task_wdt.h>
#include "config.h"
#include "logic.h"

#if ESP_ARDUINO_VERSION_MAJOR >= 3
#define PWM_ATTACH(pin, ch, freq, res) ledcAttach(pin, freq, res)
#define PWM_WRITE(pin, ch, v) ledcWrite(pin, v)
#else
#define PWM_ATTACH(pin, ch, freq, res) do { ledcSetup(ch, freq, res); ledcAttachPin(pin, ch); } while (0)
#define PWM_WRITE(pin, ch, v) ledcWrite(ch, v)
#endif
#define PWM_MAX 1023                      // 10 位
#define PWM_CH_PUMP 4                     // 加热四路用 LEDC 通道 0–3(1 kHz),泵用通道 4(20 kHz)

static const uint8_t HEAT_PIN[H_COUNT] = {PIN_HEAT_SYR, PIN_HEAT_LINE, PIN_HEAT_HUM, PIN_HEAT_TUBE};

Adafruit_ADS1115 ads[3];
static const uint8_t ADS_ADDR[3] = {ADS_ADDR_1, ADS_ADDR_2, ADS_ADDR_3};
bool adsOk[3] = {false, false, false};

Core core;
Ctrl ctrl;
Inputs sens;                              // 最近一次读数
bool netOk = false, logCsv = false;

// ---------- 执行器 ----------
// 把全部输出置于安全状态:四路加热关、加热总开关断开、泵停
void outputsSafe() {
  digitalWrite(PIN_HEAT_EN, LOW);
  for (int h = 0; h < H_COUNT; h++) PWM_WRITE(HEAT_PIN[h], h, 0);
  PWM_WRITE(PIN_PUMP, PWM_CH_PUMP, 0);
}
void driveOutputs() {
  bool any = false;
  for (int h = 0; h < H_COUNT; h++) {
    float d = core.out.on[h] ? ctrl.duty[h] : 0;      // 不允许加热的通路,无论 PI 算出什么都写 0
    if (d > 0) any = true;
    PWM_WRITE(HEAT_PIN[h], h, (uint32_t)(d * PWM_MAX));
  }
  digitalWrite(PIN_HEAT_EN, any ? HIGH : LOW);        // 没有任何一路出力时断开加热总开关
  PWM_WRITE(PIN_PUMP, PWM_CH_PUMP, (uint32_t)((core.out.pumpOn ? ctrl.pumpDuty : 0) * PWM_MAX));
}

// ---------- 传感器 ----------
float adsVolts(int chip, int ch) {
  if (!adsOk[chip]) return NAN;
  return ads[chip].computeVolts(ads[chip].readADC_SingleEnded(ch));
}
float ntcTemp(float v, float vref, float offset) {
  if (!(v >= 0.05f) || !(v <= vref - 0.05f)) return NAN;   // 开路、短路或芯片没应答
  float r = NTC_R_FIXED * (vref - v) / v;                   // NTC 接电源侧
  return 1.0f / (1.0f / 298.15f + logf(r / NTC_R0) / NTC_BETA) - 273.15f + offset;
}
void readSensors() {
  // 通道分配见 config.h 的表
  float vref = adsVolts(0, 3);
  bool refOk = vref >= 3.0f && vref <= 3.6f;               // 基准不对:全部温度按读不到处理
  auto T = [&](int chip, int ch, float off) { return refOk ? ntcTemp(adsVolts(chip, ch), vref, off) : NAN; };
  sens.syr1     = T(0, 0, OFFSET_SYR1);
  sens.line1    = T(0, 1, OFFSET_LINE1);
  sens.humOut   = T(0, 2, OFFSET_HUMOUT);
  sens.syr2     = T(1, 0, OFFSET_SYR2);
  sens.line2    = T(1, 1, OFFSET_LINE2);
  sens.humPlate = T(1, 2, OFFSET_HUMPLATE);
  sens.gasEnd   = T(1, 3, OFFSET_GASEND);
  sens.lineOut  = T(2, 0, OFFSET_LINEOUT);
#if HAS_IP_PROBES
  sens.ip1 = T(2, 1, OFFSET_IP1);
  sens.ip2 = T(2, 2, OFFSET_IP2);
#else
  sens.ip1 = sens.ip2 = NAN;
#endif
#if HAS_PRESSURE
  float vp = adsVolts(2, 3) * PRESS_DIVIDER;               // 还原成传感器输出电压
  // 低于 0.25 V 或高于 4.75 V:断线或短路
  sens.press = (vp >= 0.25f && vp <= 4.75f) ? (vp - PRESS_V_ZERO) / PRESS_V_SPAN * PRESS_RANGE + OFFSET_PRESS : NAN;
  sens.pressFitted = true;
#else
  sens.press = NAN; sens.pressFitted = false;
#endif
#if HAS_LID_SWITCH
  sens.lidClosed = digitalRead(PIN_LID) == LOW;
#else
  sens.lidClosed = true;
#endif
}

// ---------- 指示 ----------
void driveSignals(uint32_t now) {
  uint16_t a = core.alarms, aud = audible(core, now);
  bool hi = a & A_HIGH, med = a & ~A_HIGH;
  bool fast = (now / 200) % 2, slow = (now / 1000) % 2, beep = (now % 2000) < 200;
  digitalWrite(PIN_LED_R, hi && fast);                                        // 高级报警:红灯快闪
  digitalWrite(PIN_LED_Y, med);                                               // 中级报警:黄灯亮
  bool steady = core.ph == READY || core.ph == NEBULIZE || core.ph == EXPOSE;
  digitalWrite(PIN_LED_G, steady || (core.ph == PREHEAT && slow));            // 预热:绿灯慢闪
  digitalWrite(PIN_BUZZER, (aud & A_HIGH) ? fast : ((aud & ~A_HIGH) ? beep : false));
}

// ---------- 命令 ----------
struct Cmd { char kind[16]; float value; };
QueueHandle_t cmdQ; SemaphoreHandle_t snapMux; String snapJson;

void runCmd(const char *kind, float value, const char *from) {
  bool ok = coreCommand(core, millis(), kind, value);
  if (ok && !strcmp(kind, "abort")) outputsSafe();          // 中止:不等下一个控制周期,立即关
  Serial.printf("%s %s %s -> %s\n", ok ? "OK" : "ERR", from, kind, ok ? PHASE_NAME[core.ph] : "拒绝(超范围或当前阶段不允许)");
}

// ---------- 联网(独立任务,不阻塞控制)----------
static void putT(JsonObject o, const char *k, float v) {
  if (isnan(v)) o[k] = nullptr; else o[k] = round(v * 100) / 100.0;
}
void buildSnapshot(uint32_t now) {
  JsonDocument d;
  d["id"] = DEVICE_ID; d["ph"] = PHASE_NAME[core.ph];
  d["target"] = round(core.target * 10) / 10.0; d["exposeMin"] = core.exposeMin;
  d["flowSet"] = round(core.flowSet * 10) / 10.0; d["circInExpose"] = core.circInExpose;
  JsonObject t = d["t"].to<JsonObject>();
  putT(t, "syr1", sens.syr1); putT(t, "syr2", sens.syr2); putT(t, "line1", sens.line1); putT(t, "line2", sens.line2);
  putT(t, "lineOut", sens.lineOut); putT(t, "humPlate", sens.humPlate); putT(t, "humOut", sens.humOut);
  putT(t, "gasEnd", sens.gasEnd); putT(t, "ip1", sens.ip1); putT(t, "ip2", sens.ip2);
  if (isnan(sens.press)) d["press"] = nullptr; else d["press"] = round(sens.press * 10) / 10.0;
  d["flow"] = round(flowEstimate(ctrl.pumpDuty) * 10) / 10.0;      // 按占空比估算,不是实测
  JsonObject du = d["duty"].to<JsonObject>();
  for (int h = 0; h < H_COUNT; h++) du[HEATER_NAME[h]] = (int)lroundf(ctrl.duty[h] * 100);
  du["pump"] = (int)lroundf(ctrl.pumpDuty * 100);
  d["phSec"] = phaseSec(core, now); d["exposeLeft"] = exposeLeftSec(core, now);
  JsonArray al = d["al"].to<JsonArray>();
  for (int i = 0; i < ALARM_COUNT; i++) if (core.alarms & (1 << i)) al.add(ALARM_NAME[i]);
  d["muted"] = isMuted(core, now);
  String s; serializeJson(d, s);
  xSemaphoreTake(snapMux, portMAX_DELAY); snapJson = s; xSemaphoreGive(snapMux);
}

void netTask(void *) {
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(2000));
    if (WiFi.status() != WL_CONNECTED) { netOk = false; WiFi.reconnect(); vTaskDelay(pdMS_TO_TICKS(3000)); continue; }
    String body;
    xSemaphoreTake(snapMux, portMAX_DELAY); body = snapJson; xSemaphoreGive(snapMux);
    if (!body.length()) continue;
    HTTPClient http; http.setTimeout(1500); http.setConnectTimeout(1500);
    http.begin(String(SERVER_URL) + "/api/device/telemetry");
    http.addHeader("Content-Type", "application/json");
    int code = http.POST(body);
    netOk = code == 200;
    if (netOk) {
      JsonDocument r;
      if (!deserializeJson(r, http.getString())) {
        for (JsonObject c : r["cmds"].as<JsonArray>()) {
          Cmd m = {}; strlcpy(m.kind, c["kind"] | "", sizeof(m.kind));
          JsonVariant v = c["value"];
          m.value = v.is<bool>() ? (v.as<bool>() ? 1.0f : 0.0f) : (v.is<float>() ? v.as<float>() : NAN);
          xQueueSend(cmdQ, &m, 0);                          // 交给主循环执行
        }
      }
    }
    http.end();
  }
}

// ---------- 串口命令(分步测试)----------
void help() {
  Serial.println(F(
    "status                      看一次全部读数和状态\n"
    "log 1|0                     每秒一行 CSV\n"
    "heat <syr|line|hum|tube> <占空比%>   手动加热,只在 IDLE;过温保护照常;0 = 关;10 分钟自动关\n"
    "pump <占空比%>              手动转泵,只在 IDLE;0 = 关\n"
    "preheat | ready | nebulize | expose | evac | finish | abort | ack | mute\n"
    "target <37.0-43.0> | flow <0-15> | exposeMin <1-60> | circInExpose <1|0>"));
}
void status() {
  uint32_t now = millis();
  Serial.printf("ph=%s phSec=%lu exposeLeft=%ld target=%.1f flowSet=%.1f exposeMin=%d circInExpose=%d\n",
                PHASE_NAME[core.ph], (unsigned long)phaseSec(core, now), (long)exposeLeftSec(core, now),
                core.target, core.flowSet, core.exposeMin, core.circInExpose);
  Serial.printf("syr=%.2f/%.2f line=%.2f/%.2f lineOut=%.2f humPlate=%.2f humOut=%.2f gasEnd=%.2f ip=%.2f/%.2f press=%.1f lid=%d\n",
                sens.syr1, sens.syr2, sens.line1, sens.line2, sens.lineOut, sens.humPlate, sens.humOut, sens.gasEnd,
                sens.ip1, sens.ip2, sens.press, sens.lidClosed);
  Serial.printf("set=%.1f/%.1f/%.1f/%.1f duty%%=%.0f/%.0f/%.0f/%.0f pump%%=%.0f flow~%.1f (syr/line/hum/tube)\n",
                core.out.set[0], core.out.set[1], core.out.set[2], core.out.set[3],
                ctrl.duty[0] * 100, ctrl.duty[1] * 100, ctrl.duty[2] * 100, ctrl.duty[3] * 100,
                ctrl.pumpDuty * 100, flowEstimate(ctrl.pumpDuty));
  Serial.printf("alarms=0x%03X faults=0x%02X muted=%d wifi=%d ads=%d%d%d\n", core.alarms, core.faults,
                isMuted(core, now), netOk, adsOk[0], adsOk[1], adsOk[2]);
  for (int i = 0; i < ALARM_COUNT; i++) if (core.alarms & (1 << i)) Serial.printf("  报警: %s\n", ALARM_NAME[i]);
}
void serialCmd(String s) {
  s.trim(); if (!s.length()) return;
  char w[16] = "", a1[16] = ""; float a2 = NAN;
  int n = sscanf(s.c_str(), "%15s %15s %f", w, a1, &a2);
  float v = NAN;                                            // 第一个参数按数字解析,不是数字就是 NAN
  if (n >= 2) { char *end; float x = strtof(a1, &end); if (end != a1 && *end == 0) v = x; }
  uint32_t now = millis();
  if (!strcmp(w, "help")) help();
  else if (!strcmp(w, "status")) status();
  else if (!strcmp(w, "log")) {
    logCsv = v > 0;
    if (logCsv) Serial.println("ms,ph,syr1,syr2,line1,line2,lineOut,humPlate,humOut,gasEnd,ip1,ip2,press,duty_syr,duty_line,duty_hum,duty_tube,duty_pump,alarms");
  }
  else if (!strcmp(w, "heat")) {
    int h = -1; for (int i = 0; i < H_COUNT; i++) if (!strcmp(a1, HEATER_NAME[i])) h = i;
    bool ok = n >= 3 && cmdManualHeat(core, now, h, a2 / 100.0f);
    Serial.println(ok ? "OK heat" : "ERR heat 拒绝(只在 IDLE、无高级报警、0-100)");
  }
  else if (!strcmp(w, "pump")) {
    bool ok = cmdManualPump(core, now, v / 100.0f);
    Serial.println(ok ? "OK pump" : "ERR pump 拒绝(只在 IDLE、无高级报警、0-100)");
  }
  else if (!strcmp(w, "preheat") || !strcmp(w, "ready") || !strcmp(w, "nebulize") || !strcmp(w, "expose") ||
           !strcmp(w, "evac") || !strcmp(w, "finish") || !strcmp(w, "abort") || !strcmp(w, "ack") || !strcmp(w, "mute") ||
           !strcmp(w, "target") || !strcmp(w, "flow") || !strcmp(w, "exposeMin") || !strcmp(w, "circInExpose"))
    runCmd(w, v, "serial");
  else Serial.println("? 输入 help");
}

void setup() {
  // 先把所有执行器置于安全状态:加热总开关断开、四路加热关、泵停。
  // 看门狗复位或任何其他复位后都从这里重新开始,阶段回到 IDLE。
  pinMode(PIN_HEAT_EN, OUTPUT); digitalWrite(PIN_HEAT_EN, LOW);
  for (int h = 0; h < H_COUNT; h++) {
    pinMode(HEAT_PIN[h], OUTPUT); digitalWrite(HEAT_PIN[h], LOW);
    PWM_ATTACH(HEAT_PIN[h], h, 1000, 10);
  }
  pinMode(PIN_PUMP, OUTPUT); digitalWrite(PIN_PUMP, LOW);
  PWM_ATTACH(PIN_PUMP, PWM_CH_PUMP, 20000, 10);
  outputsSafe();
  for (int p : {PIN_BUZZER, PIN_LED_R, PIN_LED_Y, PIN_LED_G}) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
  pinMode(PIN_BTN_ABORT, INPUT_PULLUP); pinMode(PIN_BTN_MUTE, INPUT_PULLUP); pinMode(PIN_LID, INPUT);

  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL); Wire.setClock(400000);
  for (int i = 0; i < 3; i++) {
    adsOk[i] = ads[i].begin(ADS_ADDR[i]);
    if (adsOk[i]) { ads[i].setGain(GAIN_ONE); ads[i].setDataRate(RATE_ADS1115_475SPS); }   // ±4.096 V;12 个通道约 50 ms 读完
  }
  cmdQ = xQueueCreate(16, sizeof(Cmd)); snapMux = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 1, nullptr, 0);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t wc = {.timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wc);
#else
  esp_task_wdt_init(5, true);
#endif
  esp_task_wdt_add(nullptr);                                // 主循环卡死 5 s 即复位;复位后输出回到安全状态
  Serial.printf("\n%s ready. reset=%d ads=%d%d%d  输入 help 查看命令\n", DEVICE_ID, (int)esp_reset_reason(),
                adsOk[0], adsOk[1], adsOk[2]);
}

void loop() {
  static uint32_t t200 = 0, t1000 = 0, tBtn = 0; static bool bAbort = false, bMute = false;
  uint32_t now = millis();
  esp_task_wdt_reset();

  if (Serial.available()) serialCmd(Serial.readStringUntil('\n'));
  Cmd m; while (xQueueReceive(cmdQ, &m, 0)) runCmd(m.kind, m.value, "net");

  if (now - tBtn >= 30) {                                   // 按键(下降沿)
    tBtn = now;
    bool s = digitalRead(PIN_BTN_ABORT) == LOW, u = digitalRead(PIN_BTN_MUTE) == LOW;
    // 暂停(中止)键:只在预热到暴露之间起作用;IDLE、EVAC、DONE 时按了没有效果
    if (s && !bAbort && core.ph >= PREHEAT && core.ph <= EXPOSE) runCmd("abort", NAN, "button");
    if (u && !bMute) cmdMute(core, now);
    bAbort = s; bMute = u;
  }

  if (now - t200 >= 200) {                                  // 控制周期
    t200 = now;
    readSensors();
    sens.now = now;
    Phase before = core.ph; uint16_t alBefore = core.alarms;
    coreStep(core, sens);
    controlStep(ctrl, core, sens, CONTROL_DT);
    driveOutputs();
    if (before != core.ph) Serial.printf("PHASE %s -> %s\n", PHASE_NAME[before], PHASE_NAME[core.ph]);
    if (alBefore != core.alarms) Serial.printf("ALARMS 0x%03X -> 0x%03X\n", alBefore, core.alarms);
    buildSnapshot(now);
  }
  driveSignals(now);

  if (now - t1000 >= 1000) {
    t1000 = now;
    if (logCsv) Serial.printf("%lu,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.1f,%.0f,%.0f,%.0f,%.0f,%.0f,0x%03X\n",
                              (unsigned long)now, PHASE_NAME[core.ph], sens.syr1, sens.syr2, sens.line1, sens.line2, sens.lineOut,
                              sens.humPlate, sens.humOut, sens.gasEnd, sens.ip1, sens.ip2, sens.press,
                              ctrl.duty[0] * 100, ctrl.duty[1] * 100, ctrl.duty[2] * 100, ctrl.duty[3] * 100, ctrl.pumpDuty * 100, core.alarms);
  }
}
