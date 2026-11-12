// 状态机、报警与温度设定的全部判定逻辑。不依赖 Arduino,可以在电脑上单独编译测试(见 test/test_logic.cpp)。
#pragma once
#include <math.h>
#include <stdint.h>
#include <string.h>
#include "config.h"

enum State : uint8_t { IDLE, READY, RUN, PAUSE, DONE, BENCH };
static const char *const STATE_NAME[] = {"IDLE", "READY", "RUN", "PAUSE", "DONE", "BENCH"};

enum Alarm : uint16_t {
  A_OVERTEMP = 1, A_SENSOR = 2, A_EMPTY = 4, A_FREEFLOW = 8,          // 高级:截停
  A_NOFLOW = 16, A_FLOWDEV = 32, A_TEMPDEV = 64, A_LID = 128, A_LOWVOL = 256, A_LOWBAT = 512
};
static const char *const ALARM_NAME[] = {"OVERTEMP", "SENSOR", "EMPTY", "FREEFLOW", "NOFLOW",
                                         "FLOWDEV", "TEMPDEV", "LID", "LOWVOL", "LOWBAT"};
static const int ALARM_COUNT = 10;
static const uint16_t A_HIGH = A_OVERTEMP | A_SENSOR | A_EMPTY | A_FREEFLOW | A_NOFLOW;
static const uint16_t A_LATCHED = A_OVERTEMP | A_SENSOR;   // 只有重新上电才能清除

struct Inputs {
  uint32_t now;          // ms
  float plate1, plate2;  // 两只板温 NTC,读不到为 NAN
  float ambient;         // 进液/环境温度
  bool lidClosed;
  float flow;            // 实测流速 mL/h
  uint32_t msSinceDrop;  // 距上一滴的时间
  float rem;             // 余量 mL
  int bat;               // 电量 %,无电池为 -1
};

struct Core {
  State st = IDLE;
  uint16_t alarms = 0, muted = 0;
  float vol = 0, rateSet = 0, tempSet = 0, benchPlate = 0;
  int df = 20;
  char task[12] = "";
  bool benchClamp = false;
  // 输出
  float plateSet = 0;    // 0 = 不加热
  bool clampOpen = false;
  float delivered = 0;   // 估算的到达温度
  // 计时
  uint32_t tRun = 0, tMis = 0, tFree = 0, tDev = 0, tTemp = 0, tMute = 0;
};

// 需要的板温:先补偿下游散热得到出口温度,再由换热效率反推板温。结果夹在 [目标, PLATE_MAX]。
inline float plateFor(float target, float flow, float tin) {
  float mc = flow / 3600.0f * 4.18f;
  if (mc < 0.005f) return target;
  float out = tin + (target - tin) / expf(-K_LOSS / mc);
  float e = expf(-UA_HX / mc);
  float tp = (out - tin * e) / (1.0f - e);
  if (tp < target) tp = target;
  if (tp > PLATE_MAX) tp = PLATE_MAX;
  return tp;
}

// 由实测板温估算到达穿刺点的温度
inline float deliveredEst(float plate, float flow, float tin) {
  float mc = flow / 3600.0f * 4.18f;
  if (mc < 0.005f) return plate;
  return tin + (plate - tin) * (1.0f - expf(-UA_HX / mc)) * expf(-K_LOSS / mc);
}

inline bool heatingWanted(const Core &c) {
  return (c.tempSet > 0 && (c.st == READY || c.st == RUN || c.st == PAUSE)) || (c.st == BENCH && c.benchPlate > 0);
}

inline void coreReady(Core &c, float temp, const char *task) {
  if (c.st != IDLE) return;
  c.st = READY; c.tempSet = temp;
  strncpy(c.task, task, sizeof(c.task) - 1); c.task[sizeof(c.task) - 1] = 0;
}
inline void coreUnready(Core &c) {
  if (c.st == READY) { c.st = IDLE; c.tempSet = 0; c.task[0] = 0; }
}
inline bool coreStart(Core &c, uint32_t now, float vol, float rate, float temp, int df, const char *task) {
  if (c.st != IDLE && c.st != READY) return false;
  if (vol <= 0 || rate <= 0 || df <= 0) return false;
  if (temp > 0 && (c.alarms & A_LATCHED)) return false;
  c.vol = vol; c.rateSet = rate; c.df = df;
  c.tempSet = temp <= 0 ? 0 : (temp < TEMP_SET_MIN ? TEMP_SET_MIN : (temp > PLATE_MAX ? PLATE_MAX : temp));
  strncpy(c.task, task, sizeof(c.task) - 1); c.task[sizeof(c.task) - 1] = 0;
  c.alarms &= (A_LATCHED | A_LOWBAT); c.muted = 0;
  c.st = RUN; c.tRun = now; c.tFree = c.tDev = c.tTemp = 0;
  return true;
}
inline void corePause(Core &c) { if (c.st == RUN) c.st = PAUSE; }
inline bool coreResume(Core &c, uint32_t now) {
  if (c.st != PAUSE) return false;
  if (c.tempSet > 0 && (c.alarms & A_LATCHED)) return false;   // 加温已锁定:需重新上电
  c.alarms &= ~(A_NOFLOW | A_FREEFLOW); c.muted = 0;
  c.st = RUN; c.tRun = now; c.tFree = c.tDev = c.tTemp = 0;
  return true;
}
inline void coreFinish(Core &c) {
  if (c.st == RUN) return;                                     // 输液中不能直接结束,先暂停
  c.st = IDLE; c.alarms &= (A_LATCHED | A_LOWBAT); c.muted = 0;
  c.tempSet = 0; c.vol = 0; c.rateSet = 0; c.task[0] = 0; c.benchPlate = 0; c.benchClamp = false;
}
inline void coreMute(Core &c, uint32_t now) { c.muted = c.alarms; c.tMute = now; }
inline uint16_t audible(const Core &c, uint32_t now) {
  return (now - c.tMute < MUTE_MS) ? (c.alarms & ~c.muted) : c.alarms;
}

inline void setAlarm(Core &c, uint16_t a, bool on) { if (on) c.alarms |= a; else c.alarms &= ~a; }

// 每 200 ms 调一次
inline void coreStep(Core &c, const Inputs &in) {
  const uint32_t now = in.now;
  const bool want = heatingWanted(c);

  // ---- 温度安全 ----
  bool v1 = !isnan(in.plate1) && in.plate1 > 0 && in.plate1 < 70;
  bool v2 = !isnan(in.plate2) && in.plate2 > 0 && in.plate2 < 70;
  if ((v1 && in.plate1 >= PLATE_TRIP) || (v2 && in.plate2 >= PLATE_TRIP)) c.alarms |= A_OVERTEMP;
  if (want) {
    bool bad = !v1 || !v2;
    if (!bad && fabsf(in.plate1 - in.plate2) > PLATE_MISMATCH) {
      if (!c.tMis) c.tMis = now ? now : 1;
      if (now - c.tMis > 3000) bad = true;
    } else c.tMis = 0;
    if (bad) c.alarms |= A_SENSOR;
  }
  const bool latched = c.alarms & A_LATCHED;
  if (latched && c.st == RUN && (c.tempSet > 0 || (c.alarms & A_OVERTEMP))) c.st = PAUSE;
  const bool lidOpen = want && !in.lidClosed;
  setAlarm(c, A_LID, lidOpen);
  setAlarm(c, A_LOWBAT, in.bat >= 0 && in.bat < 15);

  // ---- 输液中的判定 ----
  const float tin = isnan(in.ambient) ? 22.0f : in.ambient;
  if (c.st == RUN) {
    const bool lowvol = in.rem <= fmaxf(LOWVOL_ML, LOWVOL_FRAC * c.vol);
    setAlarm(c, A_LOWVOL, lowvol);

    // 停滴:滴空(余量低)→ 结束;否则按堵管处理。两种情况都截停。
    uint32_t sinceRun = now - c.tRun;
    uint32_t noDrop = in.msSinceDrop < sinceRun ? in.msSinceDrop : sinceRun;
    float expMs = 3600000.0f / (c.rateSet * c.df);
    uint32_t limit = (uint32_t)fmaxf((float)NODROP_MIN_MS, 4.0f * expMs);
    if (sinceRun < START_GRACE_MS && limit < START_GRACE_MS) limit = START_GRACE_MS;
    if (noDrop >= limit) {
      if (lowvol) { c.st = DONE; c.alarms |= A_EMPTY; c.alarms &= ~(A_FLOWDEV | A_TEMPDEV | A_LOWVOL); }
      else { c.st = PAUSE; c.alarms |= A_NOFLOW; }
    }
  }
  if (c.st == RUN) {
    // 流速失控:超过设定 2 倍且多出 60 mL/h,持续 15 s → 截停
    if (in.flow > FREEFLOW_FACTOR * c.rateSet && in.flow > c.rateSet + 60) {
      if (!c.tFree) c.tFree = now ? now : 1;
      if (now - c.tFree >= FREEFLOW_MS) { c.st = PAUSE; c.alarms |= A_FREEFLOW; }
    } else c.tFree = 0;
    // 流速偏差
    if (now - c.tRun > 60000 && fabsf(in.flow - c.rateSet) > FLOWDEV_FRAC * c.rateSet) {
      if (!c.tDev) c.tDev = now ? now : 1;
      if (now - c.tDev >= FLOWDEV_MS) c.alarms |= A_FLOWDEV;
    } else { c.tDev = 0; c.alarms &= ~A_FLOWDEV; }
  } else { c.tFree = c.tDev = 0; c.alarms &= ~A_FLOWDEV; }

  // ---- 板温设定 ----
  if (!want || latched || lidOpen) c.plateSet = 0;
  else if (c.st == BENCH) c.plateSet = c.benchPlate > PLATE_MAX ? PLATE_MAX : c.benchPlate;
  else if (c.st == RUN && in.flow >= 5) c.plateSet = plateFor(c.tempSet, in.flow, tin);
  else c.plateSet = c.tempSet;                      // 预热、暂停、停流:只保温到目标值

  c.delivered = v1 ? deliveredEst(in.plate1, c.st == RUN ? in.flow : 0, tin) : NAN;

  // 温度偏差:输液 5 分钟后仍偏离设定 2 ℃ 以上并持续 3 分钟
  if (c.st == RUN && c.tempSet > 0 && !latched && now - c.tRun > 300000 && v1 &&
      fabsf(c.delivered - c.tempSet) > TEMPDEV_C) {
    if (!c.tTemp) c.tTemp = now ? now : 1;
    if (now - c.tTemp >= TEMPDEV_MS) c.alarms |= A_TEMPDEV;
  } else { c.tTemp = 0; c.alarms &= ~A_TEMPDEV; }

  c.clampOpen = (c.st == RUN) || (c.st == BENCH && c.benchClamp);
}
