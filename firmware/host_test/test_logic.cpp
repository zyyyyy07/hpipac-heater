// 在电脑上测试 include/logic.h 的判定逻辑(不需要硬件)。
// 编译运行: g++ -std=c++17 -I../include test_logic.cpp -o test_logic && ./test_logic
#include <cstdio>
#include "logic.h"

static int fails = 0;
#define CHECK(name, cond) do { bool ok = (cond); printf("%s %s\n", ok ? "PASS" : "FAIL", name); if (!ok) fails++; } while (0)

struct Sim {
  Core c; Inputs in; uint32_t lastDrop = 0; bool dripping = true;
  Sim() { in.now = 1000; in.plate1 = in.plate2 = 37; in.ambient = 22; in.lidClosed = true; in.flow = 0; in.rem = 250; in.bat = -1; in.msSinceDrop = 0xFFFFFFFF; }
  // 推进 ms 毫秒,每 200 ms 调一次 coreStep。flow 为实际流速。
  void run(uint32_t ms, float flow) {
    for (uint32_t t = 0; t < ms; t += 200) {
      in.now += 200;
      if (dripping && flow > 0) {
        uint32_t iv = (uint32_t)(3600000.0f / (flow * c.df));
        if (in.now - lastDrop >= iv) lastDrop = in.now;
        in.rem -= flow * 0.2f / 3600.0f; if (in.rem < 0) in.rem = 0;
      }
      in.flow = (dripping && c.st == RUN) ? flow : 0;
      in.msSinceDrop = lastDrop ? in.now - lastDrop : 0xFFFFFFFF;
      coreStep(c, in);
    }
  }
  void start(float vol = 250, float rate = 120, float temp = 37, int df = 20) {
    in.rem = vol; lastDrop = 0; dripping = true; coreStart(c, in.now, vol, rate, temp, df, "T1");
  }
};

int main() {
  // 板温设定
  CHECK("板温: 120 mL/h 时略高于目标且不超过 41", plateFor(37, 120, 22) > 37.0f && plateFor(37, 120, 22) <= 41.0f);
  CHECK("板温: 1000 mL/h 时封顶 41", plateFor(37, 1000, 22) == 41.0f);
  CHECK("板温: 停流时等于目标", plateFor(37, 0, 22) == 37.0f);
  bool capped = true;
  for (float f = 1; f <= 2000; f += 7) for (float t = 33; t <= 41; t += 1) for (float a = 5; a <= 35; a += 5)
    if (plateFor(t, f, a) > PLATE_MAX + 1e-4f) capped = false;
  CHECK("板温: 任意流速/目标/环境下都不超过 41", capped);
  CHECK("估算: 500 mL/h 板温 41 时到达温度约 37", fabsf(deliveredEst(41, 500, 22) - 37.2f) < 0.5f);

  { Sim s; s.start(); s.run(120000, 120);
    CHECK("正常输液: 保持 RUN,夹管阀打开,无报警", s.c.st == RUN && s.c.clampOpen && s.c.alarms == 0);
    CHECK("正常输液: 板温设定在 37–41 之间", s.c.plateSet >= 37 && s.c.plateSet <= 41); }

  { Sim s; s.start(); s.run(60000, 120); s.in.rem = 6; s.run(5000, 120);
    CHECK("余量不足: LOWVOL 预警但继续输液", s.c.st == RUN && (s.c.alarms & A_LOWVOL));
    s.dripping = false; s.run(19000, 0);
    CHECK("滴空: 停滴 19 s 时尚未动作", s.c.st == RUN);
    s.run(2000, 0);
    CHECK("滴空: 停滴 20 s 后 DONE + EMPTY", s.c.st == DONE && (s.c.alarms & A_EMPTY));
    CHECK("滴空: 夹管阀关闭,停止加热", !s.c.clampOpen && s.c.plateSet == 0);
    CHECK("滴空: 高级报警可闻", audible(s.c, s.in.now) & A_HIGH);
    coreMute(s.c, s.in.now);
    CHECK("消音: 2 分钟内静音", audible(s.c, s.in.now + 1000) == 0);
    CHECK("消音: 超时后恢复", audible(s.c, s.in.now + MUTE_MS + 1) & A_EMPTY);
    coreFinish(s.c);
    CHECK("结束: 回到 IDLE 并清报警", s.c.st == IDLE && s.c.alarms == 0); }

  { Sim s; s.start(); s.run(60000, 120); s.dripping = false; s.run(21000, 0);
    CHECK("堵管: 余量充足时停滴 → PAUSE + NOFLOW,夹闭", s.c.st == PAUSE && (s.c.alarms & A_NOFLOW) && !s.c.clampOpen);
    CHECK("堵管: 暂停时板温只保温到目标", s.c.plateSet == 37.0f);
    s.dripping = true; coreResume(s.c, s.in.now); s.run(40000, 120);
    CHECK("堵管: 恢复后报警清除", s.c.st == RUN && !(s.c.alarms & A_NOFLOW)); }

  { Sim s; s.start(); s.dripping = false; s.run(25000, 0);
    CHECK("宽限期: 开始后 25 s 无滴不报警", s.c.st == RUN);
    s.run(6000, 0);
    CHECK("宽限期: 30 s 后仍无滴 → 截停", s.c.st == PAUSE && (s.c.alarms & A_NOFLOW)); }

  { Sim s; s.start(250, 10, 37, 20); s.run(40000, 10); s.dripping = false; s.run(60000, 0);
    CHECK("慢速 10 mL/h: 60 s 无滴不误报(滴间隔 18 s)", s.c.st == RUN);
    s.run(15000, 0);
    CHECK("慢速 10 mL/h: 超过 4 个滴间隔后截停", s.c.st == PAUSE); }

  { Sim s; s.start(); s.run(30000, 120); s.in.plate1 = 42.1f; s.in.plate2 = 42.0f; s.run(400, 120);
    CHECK("过温: 42 ℃ 立即锁定,截停,停止加热", s.c.st == PAUSE && (s.c.alarms & A_OVERTEMP) && s.c.plateSet == 0 && !s.c.clampOpen);
    s.in.plate1 = s.in.plate2 = 36; s.run(5000, 0);
    CHECK("过温: 降温后仍锁定,不能恢复", (s.c.alarms & A_OVERTEMP) && s.c.plateSet == 0 && !coreResume(s.c, s.in.now)); }

  { Sim s; s.start(); s.run(30000, 120); s.in.plate2 = NAN; s.run(400, 120);
    CHECK("传感器断线: SENSOR,停止加热并截停", (s.c.alarms & A_SENSOR) && s.c.plateSet == 0 && s.c.st == PAUSE); }

  { Sim s; s.start(); s.run(30000, 120); s.in.plate2 = s.in.plate1 + 2.0f; s.run(2000, 120);
    CHECK("两只 NTC 不一致: 3 s 内不动作", !(s.c.alarms & A_SENSOR));
    s.run(2000, 120);
    CHECK("两只 NTC 不一致: 超过 3 s → SENSOR", (s.c.alarms & A_SENSOR) && s.c.plateSet == 0); }

  { Sim s; s.in.plate1 = s.in.plate2 = NAN; s.start(250, 120, 0, 20); s.run(60000, 120);
    CHECK("不加温任务: 加温模块未接也能正常输液", s.c.st == RUN && s.c.alarms == 0 && s.c.plateSet == 0); }

  { Sim s; s.start(); s.run(30000, 120); s.in.lidClosed = false; s.run(400, 120);
    CHECK("开盖: 停止加热并报警,输液继续", s.c.plateSet == 0 && (s.c.alarms & A_LID) && s.c.st == RUN);
    s.in.lidClosed = true; s.run(400, 120);
    CHECK("合盖: 报警清除,恢复加热", s.c.plateSet >= 37 && !(s.c.alarms & A_LID)); }

  { Sim s; s.start(); s.run(40000, 120); s.run(14000, 400);
    CHECK("流速失控: 14 s 时尚未动作", s.c.st == RUN);
    s.run(1400, 400);
    CHECK("流速失控: 持续 15 s → 截停 + FREEFLOW", s.c.st == PAUSE && (s.c.alarms & A_FREEFLOW) && !s.c.clampOpen); }

  { Sim s; s.start(); s.run(70000, 120); s.run(59000, 80);
    CHECK("流速偏差: 持续不足 60 s 不报", !(s.c.alarms & A_FLOWDEV));
    s.run(2000, 80);
    CHECK("流速偏差: 偏低 33% 持续 60 s → FLOWDEV,不截停", (s.c.alarms & A_FLOWDEV) && s.c.st == RUN);
    s.run(2000, 118);
    CHECK("流速偏差: 调回后自动清除", !(s.c.alarms & A_FLOWDEV)); }

  { Sim s; s.start(500, 500, 37, 20); s.in.plate1 = s.in.plate2 = 34; s.run(500000, 500);
    CHECK("温度偏差: 板温上不去 → 输液 5 分钟后再持续 3 分钟报 TEMPDEV", s.c.alarms & A_TEMPDEV); }

  { Sim s; coreReady(s.c, 37, "T9"); s.run(1000, 0);
    CHECK("预热: READY 时保温到目标,夹管阀关闭", s.c.st == READY && s.c.plateSet == 37.0f && !s.c.clampOpen);
    coreUnready(s.c); s.run(400, 0);
    CHECK("取消任务: 回到 IDLE 并停止加热", s.c.st == IDLE && s.c.plateSet == 0); }

  { Sim s; s.c.st = BENCH; s.c.benchPlate = 45; s.run(400, 0);
    CHECK("台架模式: 板温设定也被限制在 41", s.c.plateSet == 41.0f); }

  { Sim s; s.start(); s.run(10000, 120);
    coreFinish(s.c);
    CHECK("输液中不能直接结束", s.c.st == RUN); }

  printf(fails ? "%d FAILED\n" : "ALL PASS\n", fails);
  return fails ? 1 : 0;
}
