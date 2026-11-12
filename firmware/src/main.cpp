// 输液加温监控一体机 · 样机主控固件(ESP32-DevKitC,Arduino 框架)
// 本文件只做硬件读写、显示和联网;所有判定逻辑在 include/logic.h。
// 串口 115200 命令(整机分步测试用,输入 help 查看)。
#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include <HX711.h>
#include <Adafruit_ADS1X15.h>
#include <U8g2lib.h>
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
#define CH_HEAT 0
#define CH_CLAMP 1

Adafruit_ADS1115 ads;
HX711 scale;
U8G2_SSD1306_128X64_NONAME_F_HW_I2C oled(U8G2_R0, U8X8_PIN_NONE);
Preferences prefs;
Core core;

bool adsOk = false, scaleOk = false, netOk = false, logCsv = false, rawDrop = false;
float tPlate1 = NAN, tPlate2 = NAN, tOutlet = NAN, tAmbient = NAN;
float heatDuty = 0, heatInteg = 0;
float weightG = 0, weightStart = 0, scaleFactor = 420.0f;
long scaleOffset = 0;
float flowDrop = 0, flowWeight = NAN, flowCal = 1.0f, flowShown = 0, dpm = 0, remMl = 0;
uint32_t dropsAtStart = 0;
int batPct = -1;

// ---------- 液滴检测(1 kHz 采样任务)----------
portMUX_TYPE dropMux = portMUX_INITIALIZER_UNLOCKED;
volatile uint32_t dropCount = 0, lastDropMs = 0;
volatile uint32_t dropIv[6] = {0}; volatile uint8_t dropIvN = 0, dropIvI = 0;
volatile float dropBase = 0, dropNoise = 0; volatile int dropRaw = 0;

void dropTask(void *) {
  float base = analogRead(PIN_DROP), noise = 10;
  bool inDrop = false; uint32_t tIn = 0;
  for (;;) {
    int x = analogRead(PIN_DROP);
    uint32_t now = millis();
    float dev = fabsf(x - base);
    float thr = fmaxf((float)DROP_MIN_DELTA, 6.0f * noise);
    if (!inDrop) {
      if (dev > thr && now - lastDropMs > DROP_REFRACT_MS) {
        inDrop = true; tIn = now;
        portENTER_CRITICAL(&dropMux);
        if (lastDropMs) { dropIv[dropIvI] = now - lastDropMs; dropIvI = (dropIvI + 1) % 6; if (dropIvN < 6) dropIvN++; }
        lastDropMs = now; dropCount++;
        portEXIT_CRITICAL(&dropMux);
      } else {
        base += (x - base) * 0.002f;
        noise += (dev - noise) * 0.002f;
      }
    } else if (dev < thr * 0.5f) inDrop = false;
    else if (now - tIn > 300) { base = x; inDrop = false; }   // 不是液滴,是环境光或液面变化
    dropBase = base; dropNoise = noise; dropRaw = x;
    vTaskDelay(1);
  }
}

void updateDropFlow(uint32_t now) {
  uint32_t iv[6], n, last;
  portENTER_CRITICAL(&dropMux);
  n = dropIvN; last = lastDropMs; for (int i = 0; i < 6; i++) iv[i] = dropIv[i];
  portEXIT_CRITICAL(&dropMux);
  if (n == 0 || !last) { dpm = 0; flowDrop = 0; return; }
  float mean = 0; for (uint32_t i = 0; i < n; i++) mean += iv[i]; mean /= n;
  float since = now - last;
  float eff = since > 2 * mean ? since : mean;            // 滴得变慢时让读数跟着降
  dpm = since > 30000 ? 0 : 60000.0f / eff;
  flowDrop = dpm * 60.0f / core.df;
}
void resetDropStats() {
  portENTER_CRITICAL(&dropMux); dropIvN = 0; dropIvI = 0; lastDropMs = 0; portEXIT_CRITICAL(&dropMux);
}

// ---------- 温度 ----------
float ntcTemp(float v, float vref, float offset) {
  if (v < 0.05f || v > vref - 0.05f) return NAN;          // 开路或短路
  float r = NTC_R_FIXED * (vref - v) / v;                  // NTC 接电源侧
  return 1.0f / (1.0f / 298.15f + logf(r / NTC_R0) / NTC_BETA) - 273.15f + offset;
}
void readTemps() {
  if (adsOk) {
    float vref = ads.computeVolts(ads.readADC_SingleEnded(3));
    if (vref < 3.0f || vref > 3.6f) { tPlate1 = tPlate2 = tOutlet = NAN; }
    else {
      tPlate1 = ntcTemp(ads.computeVolts(ads.readADC_SingleEnded(0)), vref, OFFSET_PLATE1);
      tPlate2 = ntcTemp(ads.computeVolts(ads.readADC_SingleEnded(1)), vref, OFFSET_PLATE2);
      tOutlet = ntcTemp(ads.computeVolts(ads.readADC_SingleEnded(2)), vref, OFFSET_OUTLET);
    }
  }
  uint32_t mv = 0; for (int i = 0; i < 8; i++) mv += analogReadMilliVolts(PIN_AMBIENT);
  float a = ntcTemp(mv / 8000.0f, 3.3f, OFFSET_AMBIENT);
  tAmbient = isnan(a) ? NAN : (isnan(tAmbient) ? a : tAmbient + (a - tAmbient) * 0.05f);
}

// ---------- 称重 ----------
struct WSample { uint32_t t; float w; };
WSample wbuf[24]; uint8_t wN = 0, wI = 0; uint32_t wLast = 0;
void resetWeightFlow() { wN = wI = 0; flowWeight = NAN; flowCal = 1.0f; }
void readScale(uint32_t now) {
  if (!HAS_SCALE || !scale.is_ready()) return;
  float w = (scale.read() - scaleOffset) / scaleFactor;
  weightG = scaleOk ? weightG + (w - weightG) * 0.15f : w;
  scaleOk = true;
  if (core.st == RUN && now - wLast >= 5000) {            // 每 5 s 记一点,最近 2 分钟做线性回归
    wLast = now; wbuf[wI] = {now, weightG}; wI = (wI + 1) % 24; if (wN < 24) wN++;
    if (wN >= 12) {
      double st = 0, sw = 0, stt = 0, stw = 0; uint32_t t0 = wbuf[(wI + 24 - wN) % 24].t;
      for (int i = 0; i < wN; i++) { WSample &s = wbuf[(wI + 24 - wN + i) % 24]; double t = (s.t - t0) / 3600000.0;
        st += t; sw += s.w; stt += t * t; stw += t * s.w; }
      double den = wN * stt - st * st;
      flowWeight = den > 0 ? (float)(-(wN * stw - st * sw) / den) : NAN;   // g/h ≈ mL/h
      if (!isnan(flowWeight) && flowDrop > 10 && flowWeight > 10) {
        float k = flowWeight / flowDrop; k = constrain(k, 0.7f, 1.3f);
        flowCal += (k - flowCal) * 0.1f;                    // 用称重慢慢修正滴系数误差
      }
    }
  }
}

// ---------- 执行器 ----------
uint32_t clampSince = 0; bool clampState = false;
void driveClamp(bool open, uint32_t now) {
  if (open && !clampState) clampSince = now;
  clampState = open;
  float d = !open ? 0 : (now - clampSince < CLAMP_PULL_MS ? 1.0f : CLAMP_HOLD_DUTY);
  PWM_WRITE(PIN_CLAMP, CH_CLAMP, (uint32_t)(d * 1023));
}
void driveHeater() {                                        // 每 200 ms
  if (core.plateSet <= 0 || isnan(tPlate1)) { heatDuty = 0; heatInteg = 0; digitalWrite(PIN_HEAT_EN, LOW); }
  else {
    digitalWrite(PIN_HEAT_EN, HIGH);
    float err = core.plateSet - tPlate1;
    heatInteg = constrain(heatInteg + HEAT_KI * err * 0.2f, 0.0f, 1.0f);
    if (err < -0.5f) heatInteg = 0;
    heatDuty = constrain(HEAT_KP * err + heatInteg, 0.0f, HEAT_DUTY_MAX);
  }
  PWM_WRITE(PIN_HEAT_PWM, CH_HEAT, (uint32_t)(heatDuty * 1023));
}
void driveSignals(uint32_t now) {
  uint16_t a = core.alarms, aud = audible(core, now);
  bool hi = a & A_HIGH, med = a & ~A_HIGH;
  bool fast = (now / 200) % 2, slow = (now % 2000) < 200;
  digitalWrite(PIN_LED_R, hi && fast);
  digitalWrite(PIN_LED_Y, !hi && (med || core.st == PAUSE));
  digitalWrite(PIN_LED_G, core.st == RUN || (core.st == READY && (now / 500) % 2));
  digitalWrite(PIN_BUZZER, (aud & A_HIGH) ? fast : ((aud & ~A_HIGH) ? slow : false));
}

// ---------- 动作 ----------
void doStart(float vol, float rate, float temp, int df, const char *task) {
  uint32_t now = millis();
  if (!coreStart(core, now, vol, rate, temp, df, task)) { Serial.println("ERR start refused"); return; }
  weightStart = weightG; dropsAtStart = dropCount; resetDropStats(); resetWeightFlow(); remMl = vol;
}
void doResume() { if (coreResume(core, millis())) { resetDropStats(); wN = wI = 0; } else Serial.println("ERR resume refused"); }

// ---------- 联网(独立任务,不阻塞控制)----------
struct Cmd { char c[8]; float v, vol, rate, temp; int df; char task[12]; };
QueueHandle_t cmdQ; SemaphoreHandle_t snapMux; String snapJson;

void buildSnapshot() {
  JsonDocument d;
  d["id"] = DEVICE_ID; d["st"] = STATE_NAME[core.st == BENCH ? IDLE : core.st]; d["task"] = core.task[0] ? core.task : nullptr;
  d["tp"] = isnan(tPlate1) ? 0 : round(tPlate1 * 100) / 100.0; d["to"] = isnan(core.delivered) ? 0 : round(core.delivered * 100) / 100.0;
  d["tw"] = isnan(tOutlet) ? 0 : round(tOutlet * 100) / 100.0;
  d["ts"] = core.tempSet; d["fl"] = round(flowShown * 10) / 10.0; d["fs"] = core.rateSet; d["dpm"] = round(dpm * 10) / 10.0;
  d["w"] = round(weightG * 10) / 10.0; d["rem"] = round(remMl * 10) / 10.0;
  d["eta"] = (core.st == RUN && flowShown > 1) ? round(remMl / flowShown * 600) / 10.0 : -1;
  d["heat"] = (int)(heatDuty * 100); d["clamp"] = clampState ? 1 : 0;
  if (batPct >= 0) d["bat"] = batPct;
  JsonArray al = d["al"].to<JsonArray>();
  for (int i = 0; i < ALARM_COUNT; i++) if (core.alarms & (1 << i)) al.add(ALARM_NAME[i]);
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
          Cmd m = {}; strlcpy(m.c, c["c"] | "", sizeof(m.c)); m.v = c["v"] | 0.0f;
          m.vol = c["vol"] | 0.0f; m.rate = c["rate"] | 0.0f; m.temp = c["temp"] | 0.0f; m.df = c["df"] | 20;
          strlcpy(m.task, c["task"] | "", sizeof(m.task));
          xQueueSend(cmdQ, &m, 0);
        }
        Cmd m = {};
        if (!r["task"].isNull()) { strlcpy(m.c, "ready", sizeof(m.c)); m.temp = r["task"]["temp"] | 0.0f; strlcpy(m.task, r["task"]["id"] | "", sizeof(m.task)); }
        else strlcpy(m.c, "unready", sizeof(m.c));
        xQueueSend(cmdQ, &m, 0);
      }
    }
    http.end();
  }
}

void handleCmd(const Cmd &m) {
  if (!strcmp(m.c, "ready")) coreReady(core, m.temp, m.task);
  else if (!strcmp(m.c, "unready")) coreUnready(core);
  else if (!strcmp(m.c, "start")) doStart(m.vol, m.rate, m.temp, m.df, m.task);
  else if (!strcmp(m.c, "pause")) corePause(core);
  else if (!strcmp(m.c, "resume")) doResume();
  else if (!strcmp(m.c, "mute")) coreMute(core, millis());
  else if (!strcmp(m.c, "finish")) coreFinish(core);
  else if (!strcmp(m.c, "rate") && m.v > 0) core.rateSet = m.v;
  else if (!strcmp(m.c, "temp")) core.tempSet = m.v <= 0 ? 0 : constrain(m.v, TEMP_SET_MIN, PLATE_MAX);
}

// ---------- 串口命令(分步测试)----------
void help() {
  Serial.println(F("status | log 1/0 (每秒一行CSV) | raw 1/0 (滴斗原始信号)\n"
                   "tare (空钩去皮) | cal <克> (挂已知砝码标定) \n"
                   "plate <℃> (台架:固定板温,0关) | clamp 1/0 (台架:开关夹管阀)\n"
                   "start <mL> <mL/h> <℃> <滴系数> (不经服务器本地开始) | pause | resume | finish | mute"));
}
void status() {
  Serial.printf("st=%s alarms=0x%03X plate=%.2f/%.2f set=%.2f duty=%.0f%% outlet=%.2f amb=%.2f lid=%d\n",
                STATE_NAME[core.st], core.alarms, tPlate1, tPlate2, core.plateSet, heatDuty * 100, tOutlet, tAmbient,
                HAS_LID_SWITCH ? digitalRead(PIN_LID) == LOW : 1);
  Serial.printf("drops=%lu dpm=%.1f flowDrop=%.1f flowWeight=%.1f cal=%.2f weight=%.1fg rem=%.1f clamp=%d wifi=%d ads=%d\n",
                (unsigned long)dropCount, dpm, flowDrop, flowWeight, flowCal, weightG, remMl, clampState, netOk, adsOk);
}
void serialCmd(String s) {
  s.trim(); if (!s.length()) return;
  float a = 0, b = 0, c = 0; int d = 20; char w[12] = "";
  sscanf(s.c_str(), "%11s %f %f %f %d", w, &a, &b, &c, &d);
  if (!strcmp(w, "help")) help();
  else if (!strcmp(w, "status")) status();
  else if (!strcmp(w, "log")) { logCsv = a > 0; if (logCsv) Serial.println("ms,state,plate1,plate2,plate_set,duty,outlet,ambient,dpm,flow,flow_w,weight,rem,alarms"); }
  else if (!strcmp(w, "raw")) rawDrop = a > 0;
  else if (!strcmp(w, "tare")) { scaleOffset = scale.read_average(20); prefs.putLong("off", scaleOffset); Serial.println("OK tare"); }
  else if (!strcmp(w, "cal") && a > 0) { scaleFactor = (scale.read_average(20) - scaleOffset) / a; prefs.putFloat("fac", scaleFactor); Serial.printf("OK factor=%.3f\n", scaleFactor); }
  else if (!strcmp(w, "plate")) { if (core.st == IDLE || core.st == BENCH) { core.st = a > 0 || core.benchClamp ? BENCH : IDLE; core.benchPlate = a; } }
  else if (!strcmp(w, "clamp")) { if (core.st == IDLE || core.st == BENCH) { core.benchClamp = a > 0; core.st = core.benchClamp || core.benchPlate > 0 ? BENCH : IDLE; } }
  else if (!strcmp(w, "start")) { if (core.st == BENCH) coreFinish(core); doStart(a, b, c, d, "LOCAL"); }
  else if (!strcmp(w, "pause")) corePause(core);
  else if (!strcmp(w, "resume")) doResume();
  else if (!strcmp(w, "finish")) coreFinish(core);
  else if (!strcmp(w, "mute")) coreMute(core, millis());
  else Serial.println("? 输入 help");
}

// ---------- 显示 ----------
void drawOled() {
  char l[4][24];
  snprintf(l[0], 24, "%s %s%s", STATE_NAME[core.st], netOk ? "NET" : "---", core.alarms ? " !" : "");
  if (core.tempSet > 0 || core.st == BENCH) snprintf(l[1], 24, "T %.1f/%.1fC", isnan(core.delivered) ? 0 : core.delivered, core.st == BENCH ? core.benchPlate : core.tempSet);
  else snprintf(l[1], 24, "T off  %.1fC", isnan(tAmbient) ? 0 : tAmbient);
  snprintf(l[2], 24, "F %.0f/%.0f mL/h", flowShown, core.rateSet);
  if (core.alarms) { int i = 0; while (i < ALARM_COUNT && !(core.alarms & (1 << i))) i++; snprintf(l[3], 24, "ALM %s", ALARM_NAME[i]); }
  else if (core.st == RUN && flowShown > 1) snprintf(l[3], 24, "R %.0fmL %.0fmin", remMl, remMl / flowShown * 60);
  else snprintf(l[3], 24, "R %.0fmL  W %.0fg", remMl, weightG);
  oled.clearBuffer(); oled.setFont(u8g2_font_7x14B_tr);
  for (int i = 0; i < 4; i++) oled.drawStr(0, 14 + i * 16, l[i]);
  oled.sendBuffer();
}

void setup() {
  // 先把所有执行器置于安全状态:加热关,夹管阀断电夹闭
  pinMode(PIN_HEAT_EN, OUTPUT); digitalWrite(PIN_HEAT_EN, LOW);
  PWM_ATTACH(PIN_HEAT_PWM, CH_HEAT, 1000, 10); PWM_WRITE(PIN_HEAT_PWM, CH_HEAT, 0);
  PWM_ATTACH(PIN_CLAMP, CH_CLAMP, 20000, 10); PWM_WRITE(PIN_CLAMP, CH_CLAMP, 0);
  for (int p : {PIN_BUZZER, PIN_LED_R, PIN_LED_Y, PIN_LED_G, PIN_DROP_LED}) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }
  pinMode(PIN_BTN_STOP, INPUT_PULLUP); pinMode(PIN_BTN_MUTE, INPUT_PULLUP); pinMode(PIN_LID, INPUT);
  digitalWrite(PIN_DROP_LED, HIGH);
  Serial.begin(115200);
  Wire.begin(PIN_SDA, PIN_SCL);
  adsOk = ads.begin(0x48); if (adsOk) { ads.setGain(GAIN_ONE); ads.setDataRate(RATE_ADS1115_250SPS); }
  oled.begin();
  prefs.begin("iw", false); scaleOffset = prefs.getLong("off", 0); scaleFactor = prefs.getFloat("fac", 420.0f);
  if (HAS_SCALE) scale.begin(PIN_HX_DT, PIN_HX_SCK);
  cmdQ = xQueueCreate(16, sizeof(Cmd)); snapMux = xSemaphoreCreateMutex();
  xTaskCreatePinnedToCore(dropTask, "drop", 3072, nullptr, 3, nullptr, 1);
  xTaskCreatePinnedToCore(netTask, "net", 8192, nullptr, 1, nullptr, 0);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t wc = {.timeout_ms = 5000, .idle_core_mask = 0, .trigger_panic = true};
  esp_task_wdt_reconfigure(&wc);
#else
  esp_task_wdt_init(5, true);
#endif
  esp_task_wdt_add(nullptr);                                // 主循环卡死 5 s 即复位;复位后执行器回到安全状态
  Serial.printf("\n%s ready. ads=%d  输入 help 查看命令\n", DEVICE_ID, adsOk);
}

void loop() {
  static uint32_t t200 = 0, t1000 = 0, tBtn = 0; static bool bStop = false, bMute = false;
  uint32_t now = millis();
  esp_task_wdt_reset();

  if (Serial.available()) serialCmd(Serial.readStringUntil('\n'));
  Cmd m; while (xQueueReceive(cmdQ, &m, 0)) handleCmd(m);

  if (now - tBtn >= 30) {                                   // 按键(下降沿)
    tBtn = now;
    bool s = digitalRead(PIN_BTN_STOP) == LOW, u = digitalRead(PIN_BTN_MUTE) == LOW;
    if (s && !bStop) { if (core.st == RUN) corePause(core); else if (core.st == PAUSE) doResume(); else if (core.st == DONE) coreFinish(core); }
    if (u && !bMute) coreMute(core, now);
    bStop = s; bMute = u;
  }

  readScale(now);

  if (now - t200 >= 200) {
    t200 = now;
    readTemps();
    updateDropFlow(now);
    if (core.st == RUN || core.st == PAUSE) {
      float byDrops = core.vol - (dropCount - dropsAtStart) / (float)core.df * flowCal;
      remMl = fmaxf(0, (HAS_SCALE && scaleOk) ? core.vol - (weightStart - weightG) : byDrops);
    }
    flowShown = (core.st == RUN) ? flowDrop * flowCal : 0;
#if HAS_BATTERY
    float vb = analogReadMilliVolts(PIN_VBAT) / 1000.0f * (122.0f / 22.0f);
    batPct = constrain((int)((vb - 13.2f) / (16.4f - 13.2f) * 100), 0, 100);
#endif
    Inputs in;
    in.now = now; in.plate1 = tPlate1; in.plate2 = tPlate2; in.ambient = tAmbient;
    in.lidClosed = HAS_LID_SWITCH ? digitalRead(PIN_LID) == LOW : true;
    in.flow = flowShown; in.msSinceDrop = lastDropMs ? now - lastDropMs : 0xFFFFFFFF; in.rem = remMl; in.bat = batPct;
    State before = core.st;
    coreStep(core, in);
    if (before == RUN && core.st != RUN) Serial.printf("STOP -> %s alarms=0x%03X\n", STATE_NAME[core.st], core.alarms);
    driveHeater();
    buildSnapshot();
  }
  driveClamp(core.clampOpen, now);
  driveSignals(now);

  if (now - t1000 >= 1000) {
    t1000 = now;
    drawOled();
    if (logCsv) Serial.printf("%lu,%s,%.2f,%.2f,%.2f,%.0f,%.2f,%.2f,%.1f,%.1f,%.1f,%.1f,%.1f,0x%03X\n", (unsigned long)now, STATE_NAME[core.st],
                              tPlate1, tPlate2, core.plateSet, heatDuty * 100, tOutlet, tAmbient, dpm, flowShown, flowWeight, weightG, remMl, core.alarms);
    if (rawDrop) Serial.printf("drop raw=%d base=%.0f noise=%.1f count=%lu\n", (int)dropRaw, (float)dropBase, (float)dropNoise, (unsigned long)dropCount);
  }
}
