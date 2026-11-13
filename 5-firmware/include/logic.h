// hPIPAC 前端加热系统:阶段、报警、加热设定和 PI 控制的全部判定逻辑。
// 不依赖 Arduino,可以在电脑上单独编译测试(见 host_test/test_logic.cpp)。
// 约定见 1-design/interface-spec.md。原则:有疑问时选更安全的一边(加热关)。
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "config.h"

// ---------- 阶段 ----------
enum Phase : uint8_t { IDLE, PREHEAT, READY, NEBULIZE, EXPOSE, EVAC, DONE };
static const char *const PHASE_NAME[] = {"IDLE", "PREHEAT", "READY", "NEBULIZE", "EXPOSE", "EVAC", "DONE"};

// ---------- 加热通路 ----------
enum Heater : uint8_t { H_SYR, H_LINE, H_HUM, H_TUBE, H_COUNT };
static const char *const HEATER_NAME[] = {"syr", "line", "hum", "tube"};

// ---------- 报警(顺序与接口约定第 4 节一致)----------
enum Alarm : uint16_t {
  A_OVERTEMP_DRUG = 1 << 0, A_OVERTEMP_GAS = 1 << 1, A_IP_HIGH = 1 << 2, A_SENSOR = 1 << 3,
  A_PRESS_HIGH = 1 << 4, A_PRESS_LOW = 1 << 5,                                     // 以上为高级
  A_WATER_LOW = 1 << 6, A_LID = 1 << 7, A_PREHEAT_SLOW = 1 << 8, A_IP_LOW = 1 << 9, A_EXPOSE_END = 1 << 10
};
static const char *const ALARM_NAME[] = {"OVERTEMP_DRUG", "OVERTEMP_GAS", "IP_HIGH", "SENSOR", "PRESS_HIGH", "PRESS_LOW",
                                         "WATER_LOW", "LID", "PREHEAT_SLOW", "IP_LOW", "EXPOSE_END"};
static const int ALARM_COUNT = 11;
static const uint16_t A_HIGH = A_OVERTEMP_DRUG | A_OVERTEMP_GAS | A_IP_HIGH | A_SENSOR | A_PRESS_HIGH | A_PRESS_LOW;
static const uint16_t A_LATCHED = A_OVERTEMP_DRUG | A_OVERTEMP_GAS | A_SENSOR;   // 只有重新上电才能清除

// SENSOR 报警具体坏在哪一路(锁定)
enum Fault : uint8_t { F_SYR = 1, F_LINE = 2, F_HUM = 4, F_TUBE = 8, F_PRESS = 16 };

// ---------- 输入 ----------
struct Inputs {
  uint32_t now = 0;                       // ms
  float syr1 = NAN, syr2 = NAN;           // 读不到为 NAN
  float line1 = NAN, line2 = NAN, lineOut = NAN;
  float humPlate = NAN, humOut = NAN, gasEnd = NAN;
  float ip1 = NAN, ip2 = NAN;
  float press = NAN;                      // mmHg
  bool lidClosed = true;                  // 没装合盖开关时固定为 true
  bool pressFitted = true;                // 装了压力传感器(HAS_PRESSURE)
};

// ---------- 输出 ----------
struct Outputs {
  bool on[H_COUNT] = {false, false, false, false};   // 该路允许加热
  float set[H_COUNT] = {0, 0, 0, 0};                  // 该路设定温度 ℃(0 = 不加热;手动测试时也是 0)
  bool pumpOn = false;
  float pumpFlow = 0;                                 // 流量设定 L/min
};

// ---------- 状态 ----------
struct Core {
  Phase ph = IDLE;
  uint16_t alarms = 0, muted = 0;
  uint8_t faults = 0;                     // Fault 位,锁定
  float target = TARGET_DEFAULT;
  float flowSet = FLOW_DEFAULT;
  int exposeMin = EXPOSE_MIN_DEFAULT;
  bool circInExpose = false;
  bool ipSkip = false;                    // ready 命令:跳过腹腔温度条件
  bool slowAck = false;                   // PREHEAT_SLOW 已确认,本次预热不再提示
  bool muteOn = false;
  bool pressEst = false;                  // PREHEAT 中压力到过 8 mmHg(气腹已建立),泵可以循环
  bool ipClear = false, pressOk = false;  // 上一步的读数是否允许 ack 清除 IP_HIGH / PRESS_HIGH
  // 串口手动测试(只在 IDLE)
  float manDuty[H_COUNT] = {0, 0, 0, 0};
  float manPump = 0;
  // 计时(0 = 没在计)
  uint32_t tPhase = 0, tExpose = 0, tMute = 0, tMan = 0;
  uint32_t tNull[H_COUNT] = {0, 0, 0, 0}, tNullPress = 0, tMisSyr = 0, tMisLine = 0;
  uint32_t tPressHi = 0, tPressLo = 0, tWater = 0, tLost = 0, tIpLow = 0, tPumpRun = 0;
  Outputs out;
};

// ---------- 小工具 ----------
inline bool validT(float v) { return v == v && v > -20.0f && v < 150.0f; }
inline bool validP(float v) { return v == v && v > -10.0f && v < 100.0f; }
inline float sat01(float v) { return !(v > 0.0f) ? 0.0f : (v > 1.0f ? 1.0f : v); }

// 条件连续成立满 ms 毫秒返回 true。t0 是这个条件的计时变量。
inline bool held(uint32_t &t0, bool cond, uint32_t now, uint32_t ms) {
  if (!cond) { t0 = 0; return false; }
  if (!t0) t0 = now ? now : 1;
  return now - t0 >= ms;
}

// 药液通路(SYR、LINE)的设定值:无论目标是多少,都不超过 43.0 ℃。目标不是数时返回 0(不加热)。
inline float drugSetpoint(float target) {
  if (!(target == target) || target <= 0) return 0;
  return target > DRUG_SET_MAX ? DRUG_SET_MAX : target;
}
// 气体通路的设定值同样有上限:目标被夹在 TARGET_MAX 以内。
inline float gasTarget(float target) {
  if (!(target == target) || target <= 0) return 0;
  return target > TARGET_MAX ? TARGET_MAX : target;
}

// 腹腔平均温度。只有一只探头有读数时用那一只;都没有返回 NAN。
inline float ipAvg(const Inputs &in) {
  bool a = validT(in.ip1), b = validT(in.ip2);
  if (a && b) return (in.ip1 + in.ip2) * 0.5f;
  return a ? in.ip1 : (b ? in.ip2 : NAN);
}

inline bool manualActive(const Core &c) {
  return c.manPump > 0 || c.manDuty[0] > 0 || c.manDuty[1] > 0 || c.manDuty[2] > 0 || c.manDuty[3] > 0;
}
inline void clearManual(Core &c) { c.manPump = 0; for (int i = 0; i < H_COUNT; i++) c.manDuty[i] = 0; }

// 按阶段(或手动测试)这一路是否想要加热。报警造成的关断不在这里算。
inline bool wantsHeat(const Core &c, int h) {
  switch (c.ph) {
    case PREHEAT: case READY: case NEBULIZE: return true;
    case EXPOSE: return h == H_HUM || h == H_TUBE;
    case IDLE: return c.manDuty[h] > 0;
    default: return false;
  }
}
// 按阶段是否该循环(不看气腹是否已建立)。用来判断压力传感器是不是必须有读数。
inline bool phaseWantsPump(const Core &c) {
  switch (c.ph) {
    case PREHEAT: case READY: return c.flowSet > 0;
    case EXPOSE: return c.circInExpose && c.flowSet > 0;
    case IDLE: return c.manPump > 0;
    default: return false;                // NEBULIZE:不把气溶胶抽走
  }
}
// 泵现在想不想转。PREHEAT 中要等气腹建立(press 到过 8 mmHg)才转;没装压力传感器时不等。
inline bool wantsPump(const Core &c, const Inputs &in) {
  if (!phaseWantsPump(c)) return false;
  if (c.ph == PREHEAT && in.pressFitted && !c.pressEst) return false;
  return true;
}

// READY 的自动条件
inline bool readyCond(const Core &c, const Inputs &in) {
  const float t = c.target;
  const float d[4] = {in.syr1, in.syr2, in.line1, in.line2};
  for (int i = 0; i < 4; i++) if (!validT(d[i]) || fabsf(d[i] - t) > READY_BAND_C) return false;
  if (!validT(in.gasEnd) || in.gasEnd < t - READY_GAS_DELTA) return false;
  if (!c.ipSkip) { float ip = ipAvg(in); if (!(ip == ip) || ip < t - READY_IP_DELTA) return false; }
  return true;
}

inline void enterPhase(Core &c, Phase p, uint32_t now) {
  c.ph = p; c.tPhase = now; c.slowAck = false; c.tLost = 0; c.tIpLow = 0;
  if (p != IDLE) clearManual(c);
}

inline uint32_t phaseSec(const Core &c, uint32_t now) { return (now - c.tPhase) / 1000; }
inline int32_t exposeLeftSec(const Core &c, uint32_t now) {
  if (c.ph != EXPOSE) return -1;
  uint32_t total = (uint32_t)c.exposeMin * 60u, el = (now - c.tExpose) / 1000;
  return el >= total ? 0 : (int32_t)(total - el);
}
inline bool isMuted(const Core &c, uint32_t now) { return c.muteOn && now - c.tMute < MUTE_MS; }
// 还在响的报警(消音只对按下时已有的报警起作用,新报警照响)
inline uint16_t audible(const Core &c, uint32_t now) { return isMuted(c, now) ? (c.alarms & ~c.muted) : c.alarms; }

// ---------- 命令(返回 false = 拒绝)----------
inline bool cmdPreheat(Core &c, uint32_t now) {
  if (c.ph != IDLE) return false;
  if (c.alarms & A_HIGH) return false;                 // 有高级报警(含锁定)时不允许开始
  c.ipSkip = false; c.pressEst = false;
  enterPhase(c, PREHEAT, now);
  return true;
}
inline bool cmdReady(Core &c, uint32_t) {              // 只跳过腹腔温度条件,其余条件仍要满足才会进 READY
  if (c.ph != PREHEAT) return false;
  c.ipSkip = true;
  return true;
}
inline bool cmdNebulize(Core &c, uint32_t now) {
  if (c.ph != READY) return false;
  if (c.alarms & A_HIGH) return false;
  enterPhase(c, NEBULIZE, now);
  return true;
}
inline bool cmdExpose(Core &c, uint32_t now) {
  if (c.ph != NEBULIZE) return false;
  enterPhase(c, EXPOSE, now); c.tExpose = now;
  return true;
}
inline bool cmdEvac(Core &c, uint32_t now) {
  if (c.ph != EXPOSE) return false;
  enterPhase(c, EVAC, now);
  return true;
}
inline bool cmdFinish(Core &c, uint32_t now) {         // EVAC → DONE,再发一次 DONE → IDLE
  if (c.ph == EVAC) { enterPhase(c, DONE, now); return true; }
  if (c.ph == DONE) {
    enterPhase(c, IDLE, now);
    c.alarms &= (A_LATCHED | A_IP_HIGH);               // IP_HIGH 只能经 ack 清除
    c.muted &= c.alarms; c.ipSkip = false;
    return true;
  }
  return false;
}
inline bool cmdAbort(Core &c, uint32_t now) {          // 任何阶段 → EVAC;输出立即关
  clearManual(c);
  if (c.ph != EVAC) enterPhase(c, EVAC, now);
  c.out = Outputs();
  return true;
}
inline bool cmdTarget(Core &c, float v) {
  if (!(v >= TARGET_MIN && v <= TARGET_MAX)) return false;
  c.target = v; return true;
}
inline bool cmdFlow(Core &c, float v) {
  if (!(v >= 0.0f && v <= FLOW_MAX)) return false;
  c.flowSet = v; return true;
}
inline bool cmdExposeMin(Core &c, float v) {
  if (!(v >= EXPOSE_MIN_MIN && v <= EXPOSE_MIN_MAX)) return false;
  c.exposeMin = (int)(v + 0.5f); return true;
}
inline bool cmdCircInExpose(Core &c, float v) {        // 只接受 0 或 1
  if (v == 1.0f) { c.circInExpose = true; return true; }
  if (v == 0.0f) { c.circInExpose = false; return true; }
  return false;
}
// 确认可恢复的报警。锁定的报警不能清。条件还在的 IP_HIGH、PRESS_HIGH 不能清。没有清掉任何报警返回 false。
inline bool cmdAck(Core &c) {
  uint16_t clr = c.alarms & (A_PRESS_LOW | A_WATER_LOW | A_EXPOSE_END | A_PREHEAT_SLOW | A_IP_LOW);
  if ((c.alarms & A_IP_HIGH) && c.ipClear) clr |= A_IP_HIGH;
  if ((c.alarms & A_PRESS_HIGH) && c.pressOk) clr |= A_PRESS_HIGH;
  if (!clr) return false;
  if (clr & A_PREHEAT_SLOW) c.slowAck = true;
  if (clr & A_IP_LOW) c.tIpLow = 0;
  if (clr & A_PRESS_HIGH) c.tPressHi = 0;
  if (clr & A_PRESS_LOW) c.tPressLo = 0;
  if (clr & A_WATER_LOW) c.tWater = 0;
  c.alarms &= ~clr; c.muted &= c.alarms;
  return true;
}
inline bool cmdMute(Core &c, uint32_t now) { c.muted = c.alarms; c.tMute = now; c.muteOn = true; return true; }

// 串口手动测试:只允许在 IDLE,且没有高级报警。duty 为 0–1。过温保护照常起作用。
inline bool cmdManualHeat(Core &c, uint32_t now, int h, float duty) {
  if (c.ph != IDLE || h < 0 || h >= H_COUNT || !(duty >= 0.0f && duty <= 1.0f)) return false;
  if (duty > 0 && (c.alarms & A_HIGH)) return false;
  c.manDuty[h] = duty; c.tMan = now; return true;
}
inline bool cmdManualPump(Core &c, uint32_t now, float duty) {
  if (c.ph != IDLE || !(duty >= 0.0f && duty <= 1.0f)) return false;
  if (duty > 0 && (c.alarms & A_HIGH)) return false;
  c.manPump = duty; c.tMan = now; return true;
}

// 按名字执行一条协议命令(服务器下发和串口共用)。value 没有时传 NAN。
inline bool coreCommand(Core &c, uint32_t now, const char *kind, float value) {
  if (!strcmp(kind, "preheat")) return cmdPreheat(c, now);
  if (!strcmp(kind, "ready")) return cmdReady(c, now);
  if (!strcmp(kind, "nebulize")) return cmdNebulize(c, now);
  if (!strcmp(kind, "expose")) return cmdExpose(c, now);
  if (!strcmp(kind, "evac")) return cmdEvac(c, now);
  if (!strcmp(kind, "finish")) return cmdFinish(c, now);
  if (!strcmp(kind, "abort")) return cmdAbort(c, now);
  if (!strcmp(kind, "target")) return cmdTarget(c, value);
  if (!strcmp(kind, "flow")) return cmdFlow(c, value);
  if (!strcmp(kind, "exposeMin")) return cmdExposeMin(c, value);
  if (!strcmp(kind, "circInExpose")) return cmdCircInExpose(c, value);
  if (!strcmp(kind, "ack")) return cmdAck(c);
  if (!strcmp(kind, "mute")) return cmdMute(c, now);
  return false;
}

inline void setAlarm(Core &c, uint16_t a, bool on) { if (on) c.alarms |= a; else c.alarms &= ~a; }

// ---------- 主判定:每 200 ms 调一次 ----------
inline void coreStep(Core &c, const Inputs &in) {
  const uint32_t now = in.now;
  const bool manual = c.ph == IDLE;
  if (!manual || (manualActive(c) && now - c.tMan >= MANUAL_TIMEOUT_MS)) clearManual(c);

  // 1. 过温(任何阶段都判,锁定)。NAN 的比较结果是 false,读不到的情况由 SENSOR 处理。
  if (in.syr1 >= DRUG_TRIP || in.syr2 >= DRUG_TRIP || in.line1 >= DRUG_TRIP || in.line2 >= DRUG_TRIP)
    c.alarms |= A_OVERTEMP_DRUG;
  if (in.gasEnd >= GAS_END_TRIP || in.humOut >= HUM_OUT_TRIP || in.humPlate >= HUM_PLATE_TRIP)
    c.alarms |= A_OVERTEMP_GAS;

  // 2. 腹腔过热(任何阶段都判;只有 ack 且已降到 42.5 ℃ 以下才清)
  const bool v1 = validT(in.ip1), v2 = validT(in.ip2);
  if (in.ip1 >= IP_HIGH_TRIP || in.ip2 >= IP_HIGH_TRIP) c.alarms |= A_IP_HIGH;
  c.ipClear = (v1 || v2) && (!v1 || in.ip1 < IP_HIGH_CLEAR) && (!v2 || in.ip2 < IP_HIGH_CLEAR);

  // 3. 传感器(只在该路想要加热时判;锁定)
  bool want[H_COUNT];
  for (int h = 0; h < H_COUNT; h++) want[h] = wantsHeat(c, h);
  const bool nul[H_COUNT] = {
    !validT(in.syr1) || !validT(in.syr2),
    !validT(in.line1) || !validT(in.line2),
    !validT(in.humPlate) || !validT(in.humOut),
    !validT(in.gasEnd)};
  static const uint8_t FBIT[H_COUNT] = {F_SYR, F_LINE, F_HUM, F_TUBE};
  for (int h = 0; h < H_COUNT; h++)
    if (held(c.tNull[h], want[h] && nul[h], now, SENSOR_NULL_MS)) c.faults |= FBIT[h];
  if (held(c.tMisSyr, want[H_SYR] && !nul[H_SYR] && fabsf(in.syr1 - in.syr2) > PAIR_MISMATCH, now, MISMATCH_MS))
    c.faults |= F_SYR;
  if (held(c.tMisLine, want[H_LINE] && !nul[H_LINE] && fabsf(in.line1 - in.line2) > PAIR_MISMATCH, now, MISMATCH_MS))
    c.faults |= F_LINE;
  // 压力传感器装了却读不到:自动循环时没法判超压和漏气,按传感器故障停泵。手动测泵时不判。
  const bool pv = validP(in.press);
  if (held(c.tNullPress, !manual && phaseWantsPump(c) && in.pressFitted && !pv, now, SENSOR_NULL_MS)) c.faults |= F_PRESS;
  if (c.faults) c.alarms |= A_SENSOR;

  // 4. 压力。置位后保持,直到 ack。
  c.pressOk = pv && in.press < PRESS_HIGH_MMHG;
  if (held(c.tPressHi, pv && in.press >= PRESS_HIGH_MMHG, now, PRESS_HIGH_MS)) c.alarms |= A_PRESS_HIGH;
  // “循环中”= 上一步泵确实开着(不含手动测泵)
  if (held(c.tPressLo, !manual && c.out.pumpOn && pv && in.press <= PRESS_LOW_MMHG, now, PRESS_LOW_MS)) {
    c.alarms |= A_PRESS_LOW;
    c.pressEst = false;                   // PREHEAT 中 ack 之后也要等压力重新到 8 mmHg 才再转
  }
  // 气腹已建立:PREHEAT 中压力到 8 mmHg。记住这个状态,压力在 6–8 之间波动时泵不来回启停。
  if (c.ph == PREHEAT && pv && in.press >= PRESS_EST_MMHG && !(c.alarms & A_PRESS_LOW)) c.pressEst = true;

  // 5. 加湿罐缺水。只在泵已连续运转满 120 秒之后才判(没有气流时出口气温本来就上不去);
  //    泵一停两个计时都清零。上一步 HUM 确实开着;手动测试时不判。置位后保持,直到 ack。
  const bool pumpLong = held(c.tPumpRun, !manual && c.out.pumpOn, now, WATER_PUMP_MS);
  if (held(c.tWater, pumpLong && c.out.on[H_HUM] && validT(in.humPlate) && validT(in.humOut) &&
                     in.humPlate >= WATER_PLATE_C && in.humOut < c.target - WATER_DELTA_C, now, WATER_MS))
    c.alarms |= A_WATER_LOW;

  // 6. 合盖:LINE 想加热而盖没合上。合上自动消失。
  setAlarm(c, A_LID, want[H_LINE] && !in.lidClosed);

  // 7. 阶段的自动转换
  if (c.ph == PREHEAT) {
    if (readyCond(c, in) && !(c.alarms & A_HIGH)) enterPhase(c, READY, now);
  } else if (c.ph == READY) {
    if (held(c.tLost, !readyCond(c, in) || (c.alarms & A_HIGH), now, READY_LOST_MS)) enterPhase(c, PREHEAT, now);
  } else if (c.ph == EXPOSE) {
    if (now - c.tExpose >= (uint32_t)c.exposeMin * 60000u) { enterPhase(c, EVAC, now); c.alarms |= A_EXPOSE_END; }
  }

  // 8. 提示类报警
  setAlarm(c, A_PREHEAT_SLOW, c.ph == PREHEAT && !c.slowAck && now - c.tPhase >= PREHEAT_SLOW_MS);
  {
    const float ip = ipAvg(in);
    const bool low = c.ph == EXPOSE && ip == ip && ip < c.target - IP_LOW_DELTA_C;
    setAlarm(c, A_IP_LOW, held(c.tIpLow, low, now, IP_LOW_MS));
  }
  c.muted &= c.alarms;

  // 9. 输出。先按(可能已变的)阶段决定想不想开,再减去报警要求关掉的。
  const uint16_t a = c.alarms;
  const bool blkDrug = a & (A_OVERTEMP_DRUG | A_IP_HIGH);
  // 气体通路当作一个整体:HUM 或 TUBE 任何一只传感器坏了,HUM、TUBE、PUMP 都关(病人端气温已无法监控)
  const bool blkGas = (a & (A_OVERTEMP_GAS | A_IP_HIGH)) || (c.faults & (F_HUM | F_TUBE));
  Outputs &o = c.out;
  o.on[H_SYR]  = wantsHeat(c, H_SYR)  && !blkDrug && !(c.faults & F_SYR);
  o.on[H_LINE] = wantsHeat(c, H_LINE) && !blkDrug && !(c.faults & F_LINE) && !(a & A_LID);
  o.on[H_HUM]  = wantsHeat(c, H_HUM)  && !blkGas && !(a & A_WATER_LOW);
  o.on[H_TUBE] = wantsHeat(c, H_TUBE) && !blkGas;
  o.pumpOn = wantsPump(c, in) && !blkGas && !(a & (A_PRESS_HIGH | A_PRESS_LOW)) && !(c.faults & F_PRESS);
  const float ds = manual ? 0 : drugSetpoint(c.target), gt = manual ? 0 : gasTarget(c.target);
  o.set[H_SYR]  = o.on[H_SYR]  ? ds : 0;
  o.set[H_LINE] = o.on[H_LINE] ? ds : 0;
  o.set[H_HUM]  = (o.on[H_HUM] && gt > 0) ? gt + HUM_OVER_TARGET : 0;
  o.set[H_TUBE] = o.on[H_TUBE] ? gt : 0;
  if (!manual) for (int h = 0; h < H_COUNT; h++) if (o.set[h] <= 0) o.on[h] = false;   // 设定值无效 → 关
  o.pumpFlow = o.pumpOn ? (manual ? c.manPump * PUMP_LPM_AT_FULL : c.flowSet) : 0;
}

// ---------- PI 控制 ----------
struct Pi { float integ = 0; };

// 一步 PI,返回占空比 0–1。设定或测量不是数时输出 0 并清积分。超调 0.5 ℃ 以上清积分。
inline float piStep(Pi &p, float set, float meas, float dt, float kp, float ki) {
  if (!(set == set) || !(meas == meas) || set <= 0) { p.integ = 0; return 0; }
  const float err = set - meas;
  p.integ = sat01(p.integ + ki * err * dt);
  if (err < -0.5f) p.integ = 0;
  return sat01(kp * err + p.integ);
}

struct Ctrl {
  Pi pi[H_COUNT];
  float duty[H_COUNT] = {0, 0, 0, 0};   // 0–1
  float pumpDuty = 0;                    // 0–1
};

// 药液通路一路的占空比。两只传感器任何一只读不到、或到了 43.0 ℃,输出就是零(自动和手动都一样)。
inline float drugDuty(Pi &p, bool on, bool manual, float manDuty, float set, float ctl, float prot,
                      float dt, float kp, float ki, float dmax) {
  if (!on || !validT(ctl) || !validT(prot)) { p.integ = 0; return 0; }
  float sp = set > DRUG_SET_MAX ? DRUG_SET_MAX : set;                 // 再夹一次,不依赖 coreStep
  float d = manual ? (p.integ = 0, manDuty) : piStep(p, sp, ctl, dt, kp, ki);
  if (ctl >= DRUG_SET_MAX || prot >= DRUG_SET_MAX) return 0;
  d = sat01(d);
  return d > dmax ? dmax : d;
}

// 由 coreStep 的输出和传感器读数算各路占空比。每个控制周期在 coreStep 之后调一次。
inline void controlStep(Ctrl &k, const Core &c, const Inputs &in, float dt) {
  const Outputs &o = c.out;
  const bool man = c.ph == IDLE;

  k.duty[H_SYR] = drugDuty(k.pi[H_SYR], o.on[H_SYR], man, c.manDuty[H_SYR], o.set[H_SYR], in.syr1, in.syr2,
                           dt, SYR_KP, SYR_KI, SYR_DUTY_MAX);
  k.duty[H_LINE] = drugDuty(k.pi[H_LINE], o.on[H_LINE], man, c.manDuty[H_LINE], o.set[H_LINE], in.line1, in.line2,
                            dt, LINE_KP, LINE_KI, LINE_DUTY_MAX);

  // HUM:PI 控罐出口气温;底座接近上限时按比例收小,到上限或出口到 45 ℃ 归零。
  // 底座上限:泵在转 85 ℃;泵不转(没有气流)降到 60 ℃ 待机。
  {
    Pi &p = k.pi[H_HUM]; float d = 0;
    const float plateMax = o.pumpOn ? HUM_PLATE_MAX : HUM_PLATE_STANDBY;
    if (!o.on[H_HUM] || !validT(in.humPlate) || !validT(in.humOut)) p.integ = 0;
    else {
      const float spMax = TARGET_MAX + HUM_OVER_TARGET;
      d = man ? (p.integ = 0, c.manDuty[H_HUM])
              : piStep(p, o.set[H_HUM] > spMax ? spMax : o.set[H_HUM], in.humOut, dt, HUM_KP, HUM_KI);
      if (in.humPlate >= plateMax || in.humOut >= HUM_OUT_MAX) d = 0;
      else d *= sat01((plateMax - in.humPlate) / HUM_PLATE_FOLD);
      d = sat01(d); if (d > HUM_DUTY_MAX) d = HUM_DUTY_MAX;
    }
    k.duty[H_HUM] = d;
  }

  // TUBE:PI 控病人端气温;到 43.5 ℃ 归零
  {
    Pi &p = k.pi[H_TUBE]; float d = 0;
    if (!o.on[H_TUBE] || !validT(in.gasEnd)) p.integ = 0;
    else {
      d = man ? (p.integ = 0, c.manDuty[H_TUBE])
              : piStep(p, o.set[H_TUBE] > TARGET_MAX ? TARGET_MAX : o.set[H_TUBE], in.gasEnd, dt, TUBE_KP, TUBE_KI);
      if (in.gasEnd >= GAS_END_MAX) d = 0;
      d = sat01(d); if (d > TUBE_DUTY_MAX) d = TUBE_DUTY_MAX;
    }
    k.duty[H_TUBE] = d;
  }

  // 泵:开环,占空比 = 流量设定 / 满占空比流量
  k.pumpDuty = o.pumpOn ? sat01(o.pumpFlow / PUMP_LPM_AT_FULL) : 0;
}

// 由占空比估算的循环流量 L/min(没有流量计,见 config.h)
inline float flowEstimate(float pumpDuty) { return sat01(pumpDuty) * PUMP_LPM_AT_FULL; }
