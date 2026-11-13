// 在电脑上测试 include/logic.h 的判定逻辑(不需要硬件)。
// 编译运行: g++ -std=c++17 -I../include test_logic.cpp -o test_logic && ./test_logic
// (没有 g++ 时可以用 python -m ziglang c++ 代替 g++)
#include <cstdio>
#include "logic.h"

static int fails = 0, total = 0;
#define CHECK(name, cond) do { bool ok_ = (cond); total++; printf("%s %s\n", ok_ ? "PASS" : "FAIL", name); if (!ok_) fails++; } while (0)

struct Sim {
  Core c; Inputs in; Ctrl k;
  Sim() { in.now = 1000; good(); }
  // 全部传感器正常且已到温(目标 42):SYR/NOZ 42,出口气 43,喷头端 42,腹腔 41.5,腹腔压力 12 mmHg,雾化气压 60 kPa
  void good() {
    in.syr1 = in.syr2 = in.noz1 = in.noz2 = 42.0f;
    in.humPlate = 60.0f; in.humOut = 43.0f; in.gasEnd = 42.0f;
    in.ip1 = in.ip2 = 41.5f; in.press = 12.0f; in.nozP = 60.0f; in.pressFitted = true; in.nozPFitted = true;
  }
  void cold() { good(); in.syr1 = in.syr2 = in.noz1 = in.noz2 = 25.0f; in.humPlate = 30; in.humOut = 25; in.gasEnd = 25; in.ip1 = in.ip2 = 36.0f; }
  void step() { in.now += 200; coreStep(c, in); controlStep(k, c, in, 0.2f); }
  void run(uint32_t ms) { for (uint32_t t = 0; t < ms; t += 200) step(); }
  bool cmd(const char *kind, float v = NAN) { return coreCommand(c, in.now, kind, v); }
  bool anyHeat() const { return c.out.on[0] || c.out.on[1] || c.out.on[2] || c.out.on[3]; }
  bool allHeat() const { return c.out.on[0] && c.out.on[1] && c.out.on[2] && c.out.on[3]; }
  bool allOff() const { return !anyHeat() && !c.out.pumpOn && k.duty[0] == 0 && k.duty[1] == 0 && k.duty[2] == 0 && k.duty[3] == 0 && k.pumpDuty == 0; }
  // 把状态机推到指定阶段(正常流程)
  void to(Phase p) {
    if (p == IDLE) return;
    if (p == PREHEAT) { cold(); cmd("preheat"); step(); return; }           // PREHEAT:冷态,让它停在预热
    cmd("preheat"); step();                                                 // 已到温:一步进 READY
    if (p == READY) return;
    cmd("nebulize"); step(); if (p == NEBULIZE) return;
    cmd("expose"); step(); if (p == EXPOSE) return;
    cmd("evac"); step(); if (p == EVAC) return;
    cmd("finish"); step();
  }
};

static const Phase ALL_PHASES[] = {IDLE, PREHEAT, READY, NEBULIZE, EXPOSE, EVAC, DONE};

int main() {
  // ================= 1. 设定值上限 =================
  {
    bool ok = true;
    const float targets[] = {-5, 0, 20, 37, 42, 43, 43.01f, 44, 50, 100, 1e9f, INFINITY, -INFINITY, NAN};
    const float temps[] = {NAN, -50, 0, 20, 37, 42.9f, 43, 43.7f, 60, 200, INFINITY};
    for (Phase p : ALL_PHASES) for (float tg : targets) for (float tp : temps) {
      Sim s; s.to(p); s.c.ph = p; s.c.target = tg;                 // 绕过 cmdTarget 直接写入坏值
      s.in.syr1 = s.in.noz2 = tp; s.in.humOut = tp;
      for (int i = 0; i < 3; i++) {
        s.step();
        if (!(s.c.out.set[H_SYR] <= 43.0f) || !(s.c.out.set[H_NOZ] <= 43.0f)) ok = false;
        if (!(s.c.out.set[H_TUBE] <= 43.0f) || !(s.c.out.set[H_HUM] <= 44.0f)) ok = false;
        for (int h = 0; h < H_COUNT; h++) if (!(s.k.duty[h] >= 0 && s.k.duty[h] <= 1)) ok = false;
      }
    }
    CHECK("设定: 任何阶段/目标/读数下 SYR、NOZ 设定值都不超过 43.0", ok);
    CHECK("设定: drugSetpoint(100) = 43.0", drugSetpoint(100) == 43.0f);
    CHECK("设定: drugSetpoint(NAN) = 0(不加热)", drugSetpoint(NAN) == 0.0f);
    CHECK("设定: drugSetpoint(41.5) = 41.5", drugSetpoint(41.5f) == 41.5f);
    Sim s; s.to(READY);
    CHECK("设定: READY 时 SYR=NOZ=TUBE=目标, HUM=目标+1",
          s.c.out.set[H_SYR] == 42.0f && s.c.out.set[H_NOZ] == 42.0f && s.c.out.set[H_TUBE] == 42.0f && s.c.out.set[H_HUM] == 43.0f);
  }

  // ================= 2. PI 与占空比限制 =================
  {
    Pi p;
    float d = piStep(p, 42, 25, 0.2f, 0.35f, 0.012f);
    CHECK("PI: 远低于设定时占空比为 1", d == 1.0f);
    Pi p2; d = piStep(p2, 42, 45, 0.2f, 0.35f, 0.012f);
    CHECK("PI: 高于设定时占空比为 0 且积分清零", d == 0.0f && p2.integ == 0.0f);
    Pi p3; bool rng = true;
    for (int i = 0; i < 5000; i++) { float m = 20 + (i % 300) * 0.1f; float x = piStep(p3, 42, m, 0.2f, 0.35f, 0.012f); if (!(x >= 0 && x <= 1)) rng = false; }
    CHECK("PI: 输出始终在 0–1", rng);
    Pi p4; p4.integ = 0.5f;
    CHECK("PI: 测量为 NAN 时输出 0 并清积分", piStep(p4, 42, NAN, 0.2f, 0.35f, 0.012f) == 0.0f && p4.integ == 0.0f);
    Pi p5; float a = 0; for (int i = 0; i < 200; i++) a = piStep(p5, 42, 41.8f, 0.2f, 0.35f, 0.012f);
    CHECK("PI: 小偏差下积分累积,输出逐步上升", a > 0.35f * 0.2f + 0.05f && a < 1.0f);

    Sim s; s.to(PREHEAT);
    CHECK("占空比: 预热冷态四路都在出力", s.k.duty[H_SYR] > 0.9f && s.k.duty[H_NOZ] > 0.9f && s.k.duty[H_HUM] > 0.5f && s.k.duty[H_TUBE] > 0.9f);
    s.in.syr2 = 43.0f; s.step();
    CHECK("占空比: 保护传感器到 43.0 时 SYR 输出归零", s.k.duty[H_SYR] == 0.0f && s.k.duty[H_NOZ] > 0.9f);
    s.cold(); s.in.humPlate = 85.0f; s.step();
    CHECK("占空比: 底座到 85 时 HUM 输出归零", s.k.duty[H_HUM] == 0.0f);
    s.in.humPlate = 82.5f; s.step();
    CHECK("占空比: 底座 82.5 时 HUM 输出收小到一半以下", s.k.duty[H_HUM] > 0.0f && s.k.duty[H_HUM] <= 0.5f);
    s.cold(); s.in.humOut = 45.0f; s.step();
    CHECK("占空比: 罐出口气温到 45 时 HUM 输出归零", s.k.duty[H_HUM] == 0.0f);
    s.cold(); s.c.target = 43.0f; s.in.gasEnd = 43.5f; s.step();
    CHECK("占空比: 喷头端气温到 43.5 时 TUBE 输出归零", s.k.duty[H_TUBE] == 0.0f);
    s.cold(); s.c.target = 42.0f; s.c.flowSet = 7.5f; s.step();
    CHECK("占空比: 泵占空比 = 流量设定 / 满流量", fabsf(s.k.pumpDuty - 0.5f) < 1e-4f && fabsf(flowEstimate(s.k.pumpDuty) - 7.5f) < 1e-3f);
  }

  // ================= 3. 阶段转换 =================
  {
    Sim s;
    s.step();
    CHECK("阶段: 上电为 IDLE 且全关", s.c.ph == IDLE && s.allOff());
    CHECK("阶段: IDLE 拒绝 ready/nebulize/expose/evac/finish",
          !s.cmd("ready") && !s.cmd("nebulize") && !s.cmd("expose") && !s.cmd("evac") && !s.cmd("finish") && s.c.ph == IDLE);
    CHECK("阶段: preheat IDLE→PREHEAT", s.cmd("preheat") && s.c.ph == PREHEAT);
    s.cold(); s.step();
    CHECK("阶段: PREHEAT 四路全开,泵按设定流量", s.allHeat() && s.c.out.pumpOn && s.c.out.pumpFlow == 10.0f);
    CHECK("阶段: PREHEAT 拒绝 preheat/nebulize/expose/evac/finish",
          !s.cmd("preheat") && !s.cmd("nebulize") && !s.cmd("expose") && !s.cmd("evac") && !s.cmd("finish") && s.c.ph == PREHEAT);
    s.run(5000);
    CHECK("阶段: 没到温不会自动进 READY", s.c.ph == PREHEAT);

    // READY 自动进入的每个条件
    s.good(); s.in.syr2 = 41.4f; s.step();
    CHECK("READY: syr2 低于目标 0.6 不进", s.c.ph == PREHEAT);
    s.good(); s.in.noz1 = 42.6f; s.step();
    CHECK("READY: noz1 高于目标 0.6 不进", s.c.ph == PREHEAT);
    s.good(); s.in.gasEnd = 40.9f; s.step();
    CHECK("READY: gasEnd 低于目标 1.1 不进", s.c.ph == PREHEAT);
    s.good(); s.in.ip1 = 41.0f; s.in.ip2 = 40.8f; s.step();
    CHECK("READY: 腹腔平均 40.9 不进", s.c.ph == PREHEAT);
    s.good(); s.in.ip1 = 41.6f; s.in.ip2 = 40.4f; s.step();
    CHECK("READY: 腹腔平均 41.0(一高一低)进入", s.c.ph == READY);
    CHECK("阶段: READY 保持四路加热和循环", s.allHeat() && s.c.out.pumpOn);
    CHECK("阶段: READY 拒绝 preheat/ready/expose/evac/finish",
          !s.cmd("preheat") && !s.cmd("ready") && !s.cmd("expose") && !s.cmd("evac") && !s.cmd("finish") && s.c.ph == READY);

    // 掉回
    s.in.syr1 = 41.0f; s.run(59000);
    CHECK("READY: 条件失去 59 秒仍是 READY", s.c.ph == READY);
    s.good(); s.run(1000); s.in.syr1 = 41.0f; s.run(30000);
    CHECK("READY: 条件恢复后重新计时", s.c.ph == READY);
    s.run(30200);
    CHECK("READY: 条件失去满 60 秒掉回 PREHEAT", s.c.ph == PREHEAT);
    s.good(); s.step();
    CHECK("READY: 条件恢复后再次自动进入", s.c.ph == READY);

    CHECK("阶段: nebulize READY→NEBULIZE", s.cmd("nebulize") && s.c.ph == NEBULIZE);
    s.step();
    CHECK("阶段: NEBULIZE 四路保持,泵按 nebFlow(默认 12)运转", s.allHeat() && s.c.out.pumpOn && s.c.out.pumpFlow == 12.0f && fabsf(s.k.pumpDuty - 12.0f / 15.0f) < 1e-4f);
    CHECK("阶段: NEBULIZE 中改 nebFlow 立即生效", s.cmd("nebFlow", 8.0f)); s.step();
    CHECK("阶段: NEBULIZE 泵流量跟随 nebFlow 而不是 flowSet", s.c.out.pumpFlow == 8.0f && s.c.flowSet == 10.0f);
    s.cmd("flow", 0); s.step();
    CHECK("阶段: flow=0 不影响喷雾阶段的雾化气", s.c.out.pumpOn && s.c.out.pumpFlow == 8.0f);
    s.cmd("flow", 10);
    CHECK("阶段: NEBULIZE 拒绝 preheat/ready/nebulize/evac/finish",
          !s.cmd("preheat") && !s.cmd("ready") && !s.cmd("nebulize") && !s.cmd("evac") && !s.cmd("finish") && s.c.ph == NEBULIZE);
    s.in.syr1 = 30; s.in.syr2 = 30; s.run(120000);
    CHECK("阶段: NEBULIZE 不会因温度条件自动掉回", s.c.ph == NEBULIZE);
    s.good();
    CHECK("阶段: expose NEBULIZE→EXPOSE", s.cmd("expose") && s.c.ph == EXPOSE);
    s.step();
    CHECK("阶段: EXPOSE 时 SYR、NOZ 关,HUM、TUBE 保持", !s.c.out.on[H_SYR] && !s.c.out.on[H_NOZ] && s.c.out.on[H_HUM] && s.c.out.on[H_TUBE]);
    CHECK("阶段: EXPOSE 默认泵关", !s.c.out.pumpOn);
    CHECK("阶段: EXPOSE 拒绝 preheat/ready/nebulize/expose/finish",
          !s.cmd("preheat") && !s.cmd("ready") && !s.cmd("nebulize") && !s.cmd("expose") && !s.cmd("finish") && s.c.ph == EXPOSE);
    CHECK("阶段: circInExpose=1 被接受", s.cmd("circInExpose", 1)); s.step();
    CHECK("阶段: EXPOSE 且 circInExpose 时泵按 flowSet(不是 nebFlow)运转", s.c.out.pumpOn && s.c.out.pumpFlow == 10.0f && s.c.nebFlow == 8.0f);
    s.cmd("circInExpose", 0); s.step();
    CHECK("阶段: circInExpose=0 后泵关", !s.c.out.pumpOn);
    CHECK("阶段: exposeLeft 在 EXPOSE 中为正", exposeLeftSec(s.c, s.in.now) > 29 * 60 && exposeLeftSec(s.c, s.in.now) <= 30 * 60);
    CHECK("阶段: evac EXPOSE→EVAC(提前)", s.cmd("evac") && s.c.ph == EVAC);
    s.step();
    CHECK("阶段: 提前 evac 不报 EXPOSE_END,且全关", !(s.c.alarms & A_EXPOSE_END) && s.allOff());
    CHECK("阶段: exposeLeft 不在 EXPOSE 时为 -1", exposeLeftSec(s.c, s.in.now) == -1);
    CHECK("阶段: EVAC 拒绝 preheat/ready/nebulize/expose/evac",
          !s.cmd("preheat") && !s.cmd("ready") && !s.cmd("nebulize") && !s.cmd("expose") && !s.cmd("evac") && s.c.ph == EVAC);
    CHECK("阶段: finish EVAC→DONE", s.cmd("finish") && s.c.ph == DONE);
    s.step();
    CHECK("阶段: DONE 全关", s.allOff());
    CHECK("阶段: DONE 拒绝 preheat/ready/nebulize/expose/evac",
          !s.cmd("preheat") && !s.cmd("ready") && !s.cmd("nebulize") && !s.cmd("expose") && !s.cmd("evac") && s.c.ph == DONE);
    CHECK("阶段: finish DONE→IDLE", s.cmd("finish") && s.c.ph == IDLE);
    s.step();
    CHECK("阶段: 回到 IDLE 全关,可再次 preheat", s.allOff() && s.cmd("preheat"));
  }

  // ---- ready 命令(手动跳过腹腔条件)----
  {
    Sim s; s.cmd("preheat"); s.in.ip1 = s.in.ip2 = 38.0f; s.run(2000);
    CHECK("ready: 腹腔 38 时不自动进 READY", s.c.ph == PREHEAT);
    CHECK("ready: PREHEAT 中接受", s.cmd("ready")); s.step();
    CHECK("ready: 跳过腹腔条件后进入 READY", s.c.ph == READY);
    Sim t; t.cmd("preheat"); t.cold(); t.step(); t.cmd("ready"); t.run(3000);
    CHECK("ready: 加热没到温时即使手动确认也不进 READY", t.c.ph == PREHEAT);
    Sim u; u.cmd("preheat"); u.in.ip1 = u.in.ip2 = NAN; u.run(2000);
    CHECK("ready: 腹腔探头都读不到时不自动进 READY", u.c.ph == PREHEAT);
    u.cmd("ready"); u.step();
    CHECK("ready: 探头读不到时可手动确认", u.c.ph == READY);
    Sim v; v.cmd("preheat"); v.in.ip1 = NAN; v.in.ip2 = 41.2f; v.step();
    CHECK("ready: 只有一只探头时用那一只", v.c.ph == READY);
  }

  // ---- 暴露计时 ----
  {
    Sim s; s.to(EXPOSE);
    s.run(30u * 60000u - 2000u);
    CHECK("计时: 30 分钟未到仍是 EXPOSE", s.c.ph == EXPOSE && exposeLeftSec(s.c, s.in.now) > 0);
    s.run(2000);
    CHECK("计时: 到 30 分钟自动转 EVAC 并报 EXPOSE_END", s.c.ph == EVAC && (s.c.alarms & A_EXPOSE_END));
    CHECK("计时: 转 EVAC 后全关", s.allOff());
    CHECK("计时: EXPOSE_END 是中级", !(A_HIGH & A_EXPOSE_END));
    CHECK("计时: ack 清除 EXPOSE_END", s.cmd("ack") && !(s.c.alarms & A_EXPOSE_END));
    Sim t; t.cmd("exposeMin", 2); t.to(EXPOSE); t.run(119000);
    bool before = t.c.ph == EXPOSE; t.run(1200);
    CHECK("计时: exposeMin=2 时 2 分钟转 EVAC", before && t.c.ph == EVAC);
    Sim u; u.to(EXPOSE); u.run(5u * 60000u); u.cmd("exposeMin", 3); u.step();
    CHECK("计时: 暴露中把时间改短到已过的值,立即转 EVAC", u.c.ph == EVAC);
  }

  // ---- 中止 ----
  {
    bool ok = true, off = true;
    for (Phase p : ALL_PHASES) {
      Sim s; s.to(p);
      if (s.c.ph != p) ok = false;
      if (!s.cmd("abort") || s.c.ph != EVAC) ok = false;
      if (s.c.out.pumpOn || s.anyHeat()) off = false;              // 不等下一步,立即关
      s.step(); if (!s.allOff() || s.c.ph != EVAC) off = false;
    }
    CHECK("中止: 从每个阶段 abort 都进入 EVAC", ok);
    CHECK("中止: abort 后加热和泵立即全关", off);
    Sim s; s.to(NEBULIZE); s.cmd("abort");
    CHECK("中止: abort 后可 finish→DONE→IDLE", s.cmd("finish") && s.cmd("finish") && s.c.ph == IDLE);
  }

  // ================= 4. 命令范围 =================
  {
    Sim s;
    CHECK("范围: target 36.9 拒绝", !s.cmd("target", 36.9f) && s.c.target == 42.0f);
    CHECK("范围: target 43.1 拒绝", !s.cmd("target", 43.1f) && s.c.target == 42.0f);
    CHECK("范围: target NAN 拒绝", !s.cmd("target", NAN) && s.c.target == 42.0f);
    CHECK("范围: target 37.0 和 43.0 接受", s.cmd("target", 37.0f) && s.cmd("target", 43.0f) && s.c.target == 43.0f);
    CHECK("范围: flow -0.1 / 15.1 / NAN 拒绝", !s.cmd("flow", -0.1f) && !s.cmd("flow", 15.1f) && !s.cmd("flow", NAN) && s.c.flowSet == 10.0f);
    CHECK("范围: flow 0 和 15 接受", s.cmd("flow", 0) && s.cmd("flow", 15) && s.c.flowSet == 15.0f);
    CHECK("范围: nebFlow 默认 12", s.c.nebFlow == 12.0f);
    CHECK("范围: nebFlow 4.9 / 15.1 / 0 / NAN 拒绝", !s.cmd("nebFlow", 4.9f) && !s.cmd("nebFlow", 15.1f) && !s.cmd("nebFlow", 0) && !s.cmd("nebFlow", NAN) && s.c.nebFlow == 12.0f);
    CHECK("范围: nebFlow 5 和 15 接受", s.cmd("nebFlow", 5) && s.cmd("nebFlow", 15) && s.c.nebFlow == 15.0f);
    CHECK("范围: exposeMin 0 / 61 / NAN 拒绝", !s.cmd("exposeMin", 0) && !s.cmd("exposeMin", 61) && !s.cmd("exposeMin", NAN) && s.c.exposeMin == 30);
    CHECK("范围: exposeMin 1 和 60 接受", s.cmd("exposeMin", 1) && s.cmd("exposeMin", 60) && s.c.exposeMin == 60);
    CHECK("范围: circInExpose 2 / NAN 拒绝", !s.cmd("circInExpose", 2) && !s.cmd("circInExpose", NAN) && !s.c.circInExpose);
    CHECK("范围: 未知命令拒绝", !s.cmd("start") && !s.cmd(""));
    CHECK("范围: 没有可确认的报警时 ack 返回 false", !s.cmd("ack"));
    Sim t; t.to(PREHEAT); t.cmd("flow", 0); t.step();
    CHECK("范围: flow=0 时泵关", !t.c.out.pumpOn && t.k.pumpDuty == 0.0f);
  }

  // ================= 5. 报警 =================
  // ---- OVERTEMP_DRUG ----
  {
    const char *nm[4] = {"OVERTEMP_DRUG: syr1 43.8 触发", "OVERTEMP_DRUG: syr2 43.8 触发", "OVERTEMP_DRUG: noz1 43.8 触发", "OVERTEMP_DRUG: noz2 43.8 触发"};
    for (int i = 0; i < 4; i++) {
      Sim s; s.to(READY);
      float *f[4] = {&s.in.syr1, &s.in.syr2, &s.in.noz1, &s.in.noz2};
      *f[i] = 43.7f; s.step(); bool no = !(s.c.alarms & A_OVERTEMP_DRUG);
      *f[i] = 43.8f; s.step();
      CHECK(nm[i], no && (s.c.alarms & A_OVERTEMP_DRUG) && !s.c.out.on[H_SYR] && !s.c.out.on[H_NOZ] && s.k.duty[H_SYR] == 0 && s.k.duty[H_NOZ] == 0);
    }
    Sim s; s.to(READY); s.in.noz2 = 44.0f; s.step();
    CHECK("OVERTEMP_DRUG: HUM、TUBE、泵不受影响", s.c.out.on[H_HUM] && s.c.out.on[H_TUBE] && s.c.out.pumpOn);
    s.good(); s.run(5000);
    CHECK("OVERTEMP_DRUG: 温度恢复后仍锁定", (s.c.alarms & A_OVERTEMP_DRUG) && !s.c.out.on[H_SYR]);
    CHECK("OVERTEMP_DRUG: ack 清不掉", !s.cmd("ack") && (s.c.alarms & A_OVERTEMP_DRUG));
    CHECK("OVERTEMP_DRUG: 报警期间拒绝 nebulize", !s.cmd("nebulize") && s.c.ph == READY);
    s.cmd("abort"); s.cmd("finish"); s.cmd("finish"); s.step();
    CHECK("OVERTEMP_DRUG: finish 回 IDLE 后仍在", s.c.ph == IDLE && (s.c.alarms & A_OVERTEMP_DRUG));
    CHECK("OVERTEMP_DRUG: 锁定后拒绝再次 preheat", !s.cmd("preheat") && s.c.ph == IDLE);
    Sim i; i.in.syr1 = 50.0f; i.step();
    CHECK("OVERTEMP_DRUG: IDLE 中也判", (i.c.alarms & A_OVERTEMP_DRUG));
  }
  // ---- OVERTEMP_GAS ----
  {
    Sim a; a.to(READY); a.in.gasEnd = 44.4f; a.step(); bool no = !(a.c.alarms & A_OVERTEMP_GAS); a.in.gasEnd = 44.5f; a.step();
    CHECK("OVERTEMP_GAS: gasEnd 44.5 触发,HUM、TUBE、泵关", no && (a.c.alarms & A_OVERTEMP_GAS) && !a.c.out.on[H_HUM] && !a.c.out.on[H_TUBE] && !a.c.out.pumpOn);
    CHECK("OVERTEMP_GAS: SYR、NOZ 不受影响", a.c.out.on[H_SYR] && a.c.out.on[H_NOZ]);
    Sim b; b.to(READY); b.in.humOut = 45.9f; b.step(); no = !(b.c.alarms & A_OVERTEMP_GAS); b.in.humOut = 46.0f; b.step();
    CHECK("OVERTEMP_GAS: humOut 46 触发", no && (b.c.alarms & A_OVERTEMP_GAS) && b.k.duty[H_HUM] == 0 && b.k.pumpDuty == 0);
    Sim d; d.to(READY); d.in.humPlate = 87.9f; d.step(); no = !(d.c.alarms & A_OVERTEMP_GAS); d.in.humPlate = 88.0f; d.step();
    CHECK("OVERTEMP_GAS: humPlate 88 触发", no && (d.c.alarms & A_OVERTEMP_GAS));
    d.good(); d.run(3000);
    CHECK("OVERTEMP_GAS: 锁定,ack 清不掉", !d.cmd("ack") && (d.c.alarms & A_OVERTEMP_GAS) && !d.c.out.on[H_HUM] && !d.c.out.pumpOn);
  }
  // ---- IP_HIGH ----
  {
    Sim s; s.to(READY); s.in.ip2 = 43.4f; s.step(); bool no = !(s.c.alarms & A_IP_HIGH);
    s.in.ip2 = 43.5f; s.step();
    CHECK("IP_HIGH: ip2 43.5 触发,四路和泵全关", no && (s.c.alarms & A_IP_HIGH) && s.allOff());
    s.in.ip2 = 42.6f; s.step();
    CHECK("IP_HIGH: 42.6 时 ack 被拒", !s.cmd("ack") && (s.c.alarms & A_IP_HIGH));
    s.in.ip2 = 42.4f; s.run(5000);
    CHECK("IP_HIGH: 降到 42.4 但没 ack,仍全关", (s.c.alarms & A_IP_HIGH) && s.allOff());
    CHECK("IP_HIGH: 降到 42.4 后 ack 清除", s.cmd("ack") && !(s.c.alarms & A_IP_HIGH));
    s.step();
    CHECK("IP_HIGH: 清除后恢复加热和循环", s.anyHeat() && s.c.out.pumpOn);
    Sim t; t.to(EXPOSE); t.in.ip1 = 44.0f; t.step(); t.in.ip1 = t.in.ip2 = NAN; t.step();
    CHECK("IP_HIGH: 探头读不到时 ack 被拒(无法确认已降温)", !t.cmd("ack") && (t.c.alarms & A_IP_HIGH) && t.allOff());
    t.cmd("abort"); t.cmd("finish"); t.cmd("finish");
    CHECK("IP_HIGH: finish 回 IDLE 不会清掉", t.c.ph == IDLE && (t.c.alarms & A_IP_HIGH));
  }
  // ---- SENSOR ----
  {
    Sim s; s.to(READY); s.in.syr2 = 40.4f;                         // 相差 1.6
    s.run(9600);
    CHECK("SENSOR: syr 相差 1.6 持续不足 10 秒不报", !(s.c.alarms & A_SENSOR));
    s.run(600);
    CHECK("SENSOR: syr 相差 1.6 持续 10 秒触发,只关 SYR", (s.c.alarms & A_SENSOR) && !s.c.out.on[H_SYR] && s.c.out.on[H_NOZ] && s.c.out.on[H_HUM] && s.c.out.on[H_TUBE] && s.c.out.pumpOn);
    s.good(); s.run(3000);
    CHECK("SENSOR: 锁定,ack 清不掉", !s.cmd("ack") && (s.c.alarms & A_SENSOR) && !s.c.out.on[H_SYR]);
    Sim m; m.to(READY); m.in.noz1 = 43.4f; m.in.noz2 = 42.0f; m.run(12000);
    CHECK("SENSOR: 相差 1.4 不报", !(m.c.alarms & A_SENSOR));
    Sim n; n.to(READY); n.in.noz2 = 40.0f; n.run(5000); n.good(); n.run(1000); n.in.noz2 = 40.0f; n.run(6000);
    CHECK("SENSOR: 相差中断后重新计时", !(n.c.alarms & A_SENSOR));
    n.run(4200);
    CHECK("SENSOR: noz 相差持续 10 秒触发,只关 NOZ", (n.c.alarms & A_SENSOR) && !n.c.out.on[H_NOZ] && n.c.out.on[H_SYR]);

    Sim a; a.to(READY); a.in.syr1 = NAN; a.step();
    CHECK("SENSOR: 控制传感器 NAN 的当步占空比即为 0", a.k.duty[H_SYR] == 0.0f);
    a.run(1000);
    CHECK("SENSOR: syr1 NAN 触发并锁定,只关 SYR", (a.c.alarms & A_SENSOR) && (a.c.faults == F_SYR) && !a.c.out.on[H_SYR] && a.c.out.on[H_NOZ]);
    Sim b; b.to(READY); b.in.noz2 = NAN; b.run(1200);
    CHECK("SENSOR: noz2 NAN 触发,关 NOZ", (b.c.alarms & A_SENSOR) && !b.c.out.on[H_NOZ] && b.c.out.on[H_SYR]);
    Sim g; g.to(READY); g.in.gasEnd = NAN; g.step();
    CHECK("SENSOR: gasEnd NAN 的当步 TUBE 占空比即为 0", g.k.duty[H_TUBE] == 0.0f);
    g.run(1000);
    CHECK("SENSOR: gasEnd NAN 触发,HUM、TUBE、泵都关,SYR、NOZ 保持", (g.c.alarms & A_SENSOR) && !g.c.out.on[H_HUM] && !g.c.out.on[H_TUBE] && !g.c.out.pumpOn && g.c.out.on[H_SYR] && g.c.out.on[H_NOZ]);
    Sim h; h.to(EXPOSE); h.in.humOut = NAN; h.run(1200);
    CHECK("SENSOR: humOut NAN 触发,气体通路关", (h.c.alarms & A_SENSOR) && !h.c.out.on[H_HUM] && !h.c.out.on[H_TUBE]);
    Sim p; p.to(EXPOSE); p.in.humPlate = NAN; p.run(1200);
    CHECK("SENSOR: humPlate NAN 触发", (p.c.alarms & A_SENSOR) && p.k.duty[H_HUM] == 0.0f);
    Sim q; q.to(READY); q.in.press = NAN; q.run(1200);
    CHECK("SENSOR: 装了压力传感器却读不到 → 只停泵", (q.c.alarms & A_SENSOR) && !q.c.out.pumpOn && q.allHeat());
    Sim r; r.in.pressFitted = false; r.in.press = NAN; r.to(READY); r.run(3000);
    CHECK("SENSOR: 没装压力传感器时 press=NAN 不报,泵照常", !(r.c.alarms & A_SENSOR) && r.c.out.pumpOn);
    Sim i; i.in.syr1 = i.in.syr2 = i.in.noz1 = i.in.gasEnd = i.in.humOut = NAN; i.run(5000);
    CHECK("SENSOR: IDLE(不加热)时传感器读不到不报", i.c.alarms == 0);
    CHECK("SENSOR: 传感器坏着时 preheat 可发出,但 1 秒内锁定且从不出力", i.cmd("preheat"));
    bool never = true; for (int j = 0; j < 10; j++) { i.step(); if (i.k.duty[H_SYR] != 0 || i.k.duty[H_NOZ] != 0 || i.k.duty[H_HUM] != 0 || i.k.duty[H_TUBE] != 0) never = false; }
    CHECK("SENSOR: 上述情况下占空比始终为 0 且已锁定", never && (i.c.alarms & A_SENSOR) && !i.anyHeat());
    Sim e; e.to(EXPOSE); e.in.syr1 = e.in.noz1 = NAN; e.run(3000);
    CHECK("SENSOR: EXPOSE 中 SYR/NOZ 已关,其传感器 NAN 不报", !(e.c.alarms & A_SENSOR));
  }
  // ---- PRESS_HIGH ----
  {
    Sim s; s.to(READY); s.in.press = 18.0f; s.run(2800);
    CHECK("PRESS_HIGH: 18 mmHg 不足 3 秒不报", !(s.c.alarms & A_PRESS_HIGH) && s.c.out.pumpOn);
    s.run(400);
    CHECK("PRESS_HIGH: 持续 3 秒触发,泵关,加热不变", (s.c.alarms & A_PRESS_HIGH) && !s.c.out.pumpOn && s.k.pumpDuty == 0 && s.allHeat());
    CHECK("PRESS_HIGH: 压力还高时 ack 被拒", !s.cmd("ack"));
    s.in.press = 12.0f; s.run(3000);
    CHECK("PRESS_HIGH: 压力恢复但没 ack,泵仍关", (s.c.alarms & A_PRESS_HIGH) && !s.c.out.pumpOn);
    CHECK("PRESS_HIGH: 恢复后 ack 清除", s.cmd("ack") && !(s.c.alarms & A_PRESS_HIGH)); s.step();
    CHECK("PRESS_HIGH: 清除后泵恢复", s.c.out.pumpOn);
    Sim t; t.to(READY); t.in.press = 17.9f; t.run(10000);
    CHECK("PRESS_HIGH: 17.9 mmHg 不报", !(t.c.alarms & A_PRESS_HIGH));
    Sim u; u.to(READY); u.in.press = 20; u.run(2000); u.in.press = 12; u.step(); u.in.press = 20; u.run(2000);
    CHECK("PRESS_HIGH: 中断后重新计时", !(u.c.alarms & A_PRESS_HIGH));
  }
  // ---- PRESS_LOW ----
  {
    Sim s; s.to(READY); s.in.press = 6.0f; s.run(4800);
    CHECK("PRESS_LOW: 循环中 6 mmHg 不足 5 秒不报", !(s.c.alarms & A_PRESS_LOW) && s.c.out.pumpOn);
    s.run(400);
    CHECK("PRESS_LOW: 持续 5 秒触发,泵关,加热不变", (s.c.alarms & A_PRESS_LOW) && !s.c.out.pumpOn && s.allHeat());
    s.run(10000);
    CHECK("PRESS_LOW: 保持到 ack", (s.c.alarms & A_PRESS_LOW) && !s.c.out.pumpOn);
    s.in.press = 12; CHECK("PRESS_LOW: ack 清除", s.cmd("ack") && !(s.c.alarms & A_PRESS_LOW)); s.run(6000);
    CHECK("PRESS_LOW: 清除且压力正常后泵恢复并不再报", s.c.out.pumpOn && !(s.c.alarms & A_PRESS_LOW));
    Sim t; t.to(EXPOSE); t.in.press = 2.0f; t.run(20000);
    CHECK("PRESS_LOW: 泵没开(EXPOSE 默认)时低压不报", !(t.c.alarms & A_PRESS_LOW) && !t.c.out.pumpOn);
    Sim nb; nb.to(NEBULIZE); nb.in.press = 5.0f; nb.run(4800); bool nbNo = !(nb.c.alarms & A_PRESS_LOW) && nb.c.out.pumpOn; nb.run(400);
    CHECK("PRESS_LOW: NEBULIZE 中泵在转,低压 5 秒照样报并停泵", nbNo && (nb.c.alarms & A_PRESS_LOW) && !nb.c.out.pumpOn && nb.allHeat());
    Sim nh; nh.to(NEBULIZE); nh.in.press = 19.0f; nh.run(3400);
    CHECK("PRESS_HIGH: NEBULIZE 中照样报并停泵", (nh.c.alarms & A_PRESS_HIGH) && !nh.c.out.pumpOn);
    Sim u; u.in.press = 0; u.run(20000);
    CHECK("PRESS_LOW: IDLE 时低压不报", u.c.alarms == 0);
    Sim v; v.to(READY); v.in.press = 6.1f; v.run(20000);
    CHECK("PRESS_LOW: 6.1 mmHg 不报", !(v.c.alarms & A_PRESS_LOW));
  }
  // ---- WATER_LOW ----
  {
    Sim s; s.to(READY); s.run(120000); s.in.humPlate = 75.0f; s.in.humOut = 38.9f; s.run(119000);
    CHECK("WATER_LOW: 不足 120 秒不报", !(s.c.alarms & A_WATER_LOW) && s.c.out.on[H_HUM]);
    s.run(1400);
    CHECK("WATER_LOW: 持续 120 秒触发,只关 HUM", (s.c.alarms & A_WATER_LOW) && !s.c.out.on[H_HUM] && s.k.duty[H_HUM] == 0 && s.c.out.on[H_TUBE] && s.c.out.on[H_SYR] && s.c.out.pumpOn);
    CHECK("WATER_LOW: 是中级", !(A_HIGH & A_WATER_LOW));
    s.good(); s.run(5000);
    CHECK("WATER_LOW: 保持到 ack", (s.c.alarms & A_WATER_LOW) && !s.c.out.on[H_HUM]);
    CHECK("WATER_LOW: ack 清除", s.cmd("ack")); s.step();
    CHECK("WATER_LOW: 清除后 HUM 恢复", s.c.out.on[H_HUM]);
    Sim t; t.to(READY); t.in.humPlate = 74.9f; t.in.humOut = 30; t.run(260000);
    CHECK("WATER_LOW: 底座 74.9 不报", !(t.c.alarms & A_WATER_LOW));
    Sim u; u.to(READY); u.in.humPlate = 80; u.in.humOut = 39.0f; u.run(260000);
    CHECK("WATER_LOW: 出口气温只低 3.0 不报", !(u.c.alarms & A_WATER_LOW));
    // 泵运转时间的门槛
    Sim a; a.to(READY); a.in.humPlate = 80; a.in.humOut = 30; a.run(239000);
    CHECK("WATER_LOW: 泵刚开时条件就成立,泵转满 120 秒前不计时(239 秒不报)", !(a.c.alarms & A_WATER_LOW) && a.c.out.pumpOn);
    a.run(1600);
    CHECK("WATER_LOW: 泵转满 120 秒后再持续 120 秒才报", (a.c.alarms & A_WATER_LOW) && !a.c.out.on[H_HUM]);
    Sim n; n.to(NEBULIZE); n.in.humPlate = 80; n.in.humOut = 30; n.run(239000);
    bool nNo = !(n.c.alarms & A_WATER_LOW) && n.c.out.pumpOn; n.run(1600);
    CHECK("WATER_LOW: NEBULIZE 中泵在转,120+120 秒后照样报,只关 HUM", nNo && (n.c.alarms & A_WATER_LOW) && !n.c.out.on[H_HUM] && n.c.out.pumpOn && n.c.out.on[H_NOZ]);
    Sim nr; nr.to(READY); nr.run(100000); nr.cmd("nebulize"); nr.in.humPlate = 80; nr.in.humOut = 30; nr.run(139000);
    bool nrNo = !(nr.c.alarms & A_WATER_LOW); nr.run(1600);
    CHECK("WATER_LOW: 泵连续运转时间跨 READY→NEBULIZE 累计", nrNo && (nr.c.alarms & A_WATER_LOW));
    Sim e; e.to(EXPOSE); e.in.humPlate = 80; e.in.humOut = 30; e.run(600000);
    CHECK("WATER_LOW: EXPOSE 默认泵关 10 分钟不报", e.c.ph == EXPOSE && !(e.c.alarms & A_WATER_LOW) && !e.c.out.pumpOn);
    Sim ec; ec.cmd("circInExpose", 1); ec.to(EXPOSE); ec.in.humPlate = 80; ec.in.humOut = 30; ec.run(241000);
    CHECK("WATER_LOW: EXPOSE 且循环时照常判", (ec.c.alarms & A_WATER_LOW));
    Sim pp; pp.to(PREHEAT); pp.in.press = 0; pp.cmd("abort"); pp.cmd("finish"); pp.cmd("finish"); pp.cmd("preheat");
    pp.in.humPlate = 80; pp.in.humOut = 30; pp.run(600000);
    CHECK("WATER_LOW: PREHEAT 气腹未建立(泵不转)不报", pp.c.ph == PREHEAT && !(pp.c.alarms & A_WATER_LOW) && !pp.c.out.pumpOn);
    Sim st; st.to(READY); st.run(200000); st.in.humPlate = 80; st.in.humOut = 30; st.run(100000);
    st.in.press = 20; st.run(4000); bool stopped = !st.c.out.pumpOn; st.run(300000);
    CHECK("WATER_LOW: 计时中途泵停(压力报警)则不报", stopped && !(st.c.alarms & A_WATER_LOW));
    st.in.press = 12; st.run(400); st.cmd("ack"); st.run(239000);
    bool notYet = !(st.c.alarms & A_WATER_LOW) && st.c.out.pumpOn; st.run(1600);
    CHECK("WATER_LOW: 泵恢复后重新从头计 120+120 秒", notYet && (st.c.alarms & A_WATER_LOW));
  }
  // ---- PREHEAT_SLOW ----
  {
    Sim s; s.to(PREHEAT); s.run(3600000u - 2000u);
    CHECK("PREHEAT_SLOW: 不足 60 分钟不报", !(s.c.alarms & A_PREHEAT_SLOW));
    s.run(2000);
    CHECK("PREHEAT_SLOW: 满 60 分钟触发,仅提示(加热和泵照常)", (s.c.alarms & A_PREHEAT_SLOW) && s.c.ph == PREHEAT && s.allHeat() && s.c.out.pumpOn);
    CHECK("PREHEAT_SLOW: ack 清除且不再重复", s.cmd("ack")); s.run(5000);
    CHECK("PREHEAT_SLOW: ack 后本次预热不再提示", !(s.c.alarms & A_PREHEAT_SLOW));
    Sim t; t.to(PREHEAT); t.run(3600000u); t.good(); t.step();
    CHECK("PREHEAT_SLOW: 进入 READY 后自动消失", t.c.ph == READY && !(t.c.alarms & A_PREHEAT_SLOW));
  }
  // ---- IP_LOW ----
  {
    Sim s; s.to(EXPOSE); s.in.ip1 = s.in.ip2 = 39.9f; s.run(299000);
    CHECK("IP_LOW: 不足 5 分钟不报", !(s.c.alarms & A_IP_LOW));
    s.run(1400);
    CHECK("IP_LOW: 持续 5 分钟触发,仅提示", (s.c.alarms & A_IP_LOW) && s.c.ph == EXPOSE && s.c.out.on[H_HUM] && s.c.out.on[H_TUBE]);
    s.in.ip1 = s.in.ip2 = 41.0f; s.step();
    CHECK("IP_LOW: 温度回升后自动消失", !(s.c.alarms & A_IP_LOW));
    Sim t; t.to(EXPOSE); t.in.ip1 = t.in.ip2 = 40.0f; t.run(400000);
    CHECK("IP_LOW: 正好低 2.0 不报", !(t.c.alarms & A_IP_LOW));
    Sim u; u.to(READY); u.cmd("nebulize"); u.in.ip1 = u.in.ip2 = 38.0f; u.run(400000);
    CHECK("IP_LOW: 不在 EXPOSE 时不报", !(u.c.alarms & A_IP_LOW));
    Sim v; v.to(EXPOSE); v.in.ip1 = v.in.ip2 = NAN; v.run(400000);
    CHECK("IP_LOW: 探头读不到时不报", !(v.c.alarms & A_IP_LOW));
  }

  // ---- PREHEAT 中泵等气腹建立(press ≥ 8)----
  {
    Sim s; s.cold(); s.in.press = 0; s.cmd("preheat"); s.run(60000);
    CHECK("气腹: PREHEAT 压力 0 时泵不转,四路加热照常", s.c.ph == PREHEAT && !s.c.out.pumpOn && s.k.pumpDuty == 0 && s.allHeat());
    CHECK("气腹: 压力未建立不是报警(无 PRESS_LOW、无 SENSOR)", s.c.alarms == 0);
    s.in.press = 7.9f; s.run(10000);
    CHECK("气腹: 7.9 mmHg 泵仍不转", !s.c.out.pumpOn && s.c.alarms == 0);
    s.in.press = 8.0f; s.step();
    CHECK("气腹: 压力到 8.0 泵开始按设定流量循环", s.c.out.pumpOn && s.c.out.pumpFlow == 10.0f && s.k.pumpDuty > 0);
    s.in.press = 7.0f; s.run(20000);
    CHECK("气腹: 建立后压力回落到 7(高于 6)泵不停、不报警", s.c.out.pumpOn && s.c.alarms == 0);
    s.in.press = 5.0f; s.run(5200);
    CHECK("气腹: 运转中压力 ≤ 6 持续 5 秒报 PRESS_LOW 并停泵", (s.c.alarms & A_PRESS_LOW) && !s.c.out.pumpOn);
    CHECK("气腹: PRESS_LOW 可 ack", s.cmd("ack")); s.run(20000);
    CHECK("气腹: ack 后压力仍低,泵不转也不再报(等压力重新到 8)", !s.c.out.pumpOn && s.c.alarms == 0);
    s.in.press = 9.0f; s.step();
    CHECK("气腹: 压力重新到 8 以上泵恢复", s.c.out.pumpOn);
    Sim n; n.cold(); n.in.pressFitted = false; n.in.press = NAN; n.cmd("preheat"); n.step();
    CHECK("气腹: 没装压力传感器时 PREHEAT 泵直接转", n.c.out.pumpOn && n.c.alarms == 0);
    Sim f; f.cold(); f.in.press = NAN; f.cmd("preheat"); f.run(1200);
    CHECK("气腹: 装了却读不到 → SENSOR,泵不转(不会无声地一直等)", (f.c.alarms & A_SENSOR) && (f.c.faults & F_PRESS) && !f.c.out.pumpOn);
    Sim z; z.cold(); z.cmd("preheat"); z.step(); bool on1 = z.c.out.pumpOn;
    z.cmd("abort"); z.cmd("finish"); z.cmd("finish"); z.in.press = 0; z.cmd("preheat"); z.run(3000);
    CHECK("气腹: 下一次预热重新等压力建立", on1 && z.c.ph == PREHEAT && !z.c.out.pumpOn && z.c.alarms == 0);
    Sim r; r.in.press = 7.0f; r.cmd("preheat"); r.step();
    CHECK("气腹: 进入 READY 后按设定流量循环(READY 不再等 8)", r.c.ph == READY && r.c.out.pumpOn);
  }
  // ---- HUM 底座上限:泵转 85,泵不转 60 ----
  {
    Sim s; s.to(PREHEAT); s.in.humPlate = 70.0f; s.step();
    CHECK("底座: 泵在转,70 ℃ 时 HUM 满出力", s.c.out.pumpOn && s.k.duty[H_HUM] > 0.9f);
    s.in.humPlate = 84.9f; s.step(); bool some = s.k.duty[H_HUM] > 0; s.in.humPlate = 85.0f; s.step();
    CHECK("底座: 泵在转,上限是 85", some && s.k.duty[H_HUM] == 0.0f);
    Sim q; q.cold(); q.in.press = 0; q.cmd("preheat"); q.in.humPlate = 50.0f; q.step();
    CHECK("底座: 泵不转(气腹未建立),50 ℃ 时 HUM 仍出力", !q.c.out.pumpOn && q.k.duty[H_HUM] > 0.5f);
    q.in.humPlate = 57.5f; q.step();
    CHECK("底座: 泵不转,57.5 ℃ 时收小到一半以下", q.k.duty[H_HUM] > 0.0f && q.k.duty[H_HUM] <= 0.5f);
    q.in.humPlate = 60.0f; q.step();
    CHECK("底座: 泵不转,到 60 ℃ 输出归零", q.k.duty[H_HUM] == 0.0f && q.c.out.on[H_HUM]);
    q.in.press = 12.0f; q.step();
    CHECK("底座: 泵一转,60 ℃ 时恢复出力(上限回到 85)", q.c.out.pumpOn && q.k.duty[H_HUM] > 0.5f);
    Sim n; n.to(NEBULIZE); n.in.humOut = 30; n.in.humPlate = 70.0f; n.step(); bool nOn = n.c.out.pumpOn && n.k.duty[H_HUM] > 0.5f;
    n.in.humPlate = 85.0f; n.step();
    CHECK("底座: NEBULIZE(泵在转)上限 85", nOn && n.k.duty[H_HUM] == 0.0f);
    n.in.humPlate = 70.0f; n.in.nozP = 160; n.run(3400);
    CHECK("底座: NEBULIZE 中泵因 NOZ_BLOCK 停了,上限降到 60", !n.c.out.pumpOn && n.k.duty[H_HUM] == 0.0f && n.c.out.on[H_HUM]);
    Sim e; e.to(EXPOSE); e.in.humOut = 30; e.in.humPlate = 62.0f; e.step(); bool eOff = e.k.duty[H_HUM] == 0.0f;
    e.cmd("circInExpose", 1); e.step();
    CHECK("底座: EXPOSE 泵关上限 60,开循环后上限 85", eOff && e.c.out.pumpOn && e.k.duty[H_HUM] > 0.5f);
    Sim a; a.to(READY); a.in.humOut = 30; a.in.humPlate = 70; a.step(); bool before = a.k.duty[H_HUM] > 0.5f;
    a.in.press = 20; a.run(3400);
    CHECK("底座: 压力报警停泵后上限降到 60", before && (a.c.alarms & A_PRESS_HIGH) && !a.c.out.pumpOn && a.k.duty[H_HUM] == 0.0f);
    Sim m; m.step(); cmdManualHeat(m.c, m.in.now, H_HUM, 1.0f); m.in.humPlate = 61; m.step(); bool mOff = m.k.duty[H_HUM] == 0.0f;
    cmdManualPump(m.c, m.in.now, 0.5f); m.step();
    CHECK("底座: 手动测试同样适用(泵停 60,泵转 85)", mOff && m.k.duty[H_HUM] > 0.9f);
    Sim t; t.to(NEBULIZE); t.in.humPlate = 88.0f; t.step();
    CHECK("底座: OVERTEMP_GAS 的 88 ℃ 不随泵变", (t.c.alarms & A_OVERTEMP_GAS));
  }

  // ---- NOZ_BLOCK ----
  {
    Sim s; s.to(NEBULIZE); s.in.nozP = 150.0f; s.run(2800);
    CHECK("NOZ_BLOCK: 150 kPa 不足 3 秒不报", !(s.c.alarms & A_NOZ_BLOCK) && s.c.out.pumpOn);
    s.run(400);
    CHECK("NOZ_BLOCK: 持续 3 秒触发,泵关,四路加热不变", (s.c.alarms & A_NOZ_BLOCK) && !s.c.out.pumpOn && s.k.pumpDuty == 0 && s.allHeat());
    CHECK("NOZ_BLOCK: 气压还高时 ack 被拒", !s.cmd("ack") && (s.c.alarms & A_NOZ_BLOCK));
    s.in.nozP = 5.0f; s.run(5000);
    CHECK("NOZ_BLOCK: 气压降了但没 ack,泵仍关", (s.c.alarms & A_NOZ_BLOCK) && !s.c.out.pumpOn);
    CHECK("NOZ_BLOCK: 气压低于 150 后 ack 清除", s.cmd("ack") && !(s.c.alarms & A_NOZ_BLOCK)); s.step();
    CHECK("NOZ_BLOCK: 清除后泵恢复", s.c.out.pumpOn && s.c.out.pumpFlow == 12.0f);
    Sim t; t.to(NEBULIZE); t.in.nozP = 149.9f; t.run(20000);
    CHECK("NOZ_BLOCK: 149.9 kPa 不报", !(t.c.alarms & A_NOZ_BLOCK));
    Sim u; u.to(NEBULIZE); u.in.nozP = 180; u.run(2000); u.in.nozP = 60; u.step(); u.in.nozP = 180; u.run(2000);
    CHECK("NOZ_BLOCK: 中断后重新计时", !(u.c.alarms & A_NOZ_BLOCK));
    Sim r; r.to(READY); r.in.nozP = 160; r.run(3400);
    CHECK("NOZ_BLOCK: READY 中也判,并拒绝 nebulize", (r.c.alarms & A_NOZ_BLOCK) && !r.c.out.pumpOn && !r.cmd("nebulize"));
    Sim x; x.to(NEBULIZE); x.in.nozP = 160; x.run(3400); x.in.nozP = NAN; x.run(600);
    CHECK("NOZ_BLOCK: 传感器读不到时 ack 被拒", !x.cmd("ack") && (x.c.alarms & A_NOZ_BLOCK));
    Sim f; f.in.nozPFitted = false; f.in.nozP = NAN; f.to(NEBULIZE); f.run(60000);
    CHECK("NOZ: 没装雾化气压传感器时两个报警都不起作用,泵照常", f.c.alarms == 0 && f.c.out.pumpOn && f.c.ph == NEBULIZE);
    Sim g; g.to(NEBULIZE); g.in.nozP = NAN; g.step(); bool g0 = !(g.c.alarms & A_SENSOR); g.run(1000);
    CHECK("NOZ: 装了却读不到 → SENSOR(锁定),只停泵", g0 && (g.c.alarms & A_SENSOR) && (g.c.faults == F_NOZP) && !g.c.out.pumpOn && g.allHeat());
    Sim h; h.to(EXPOSE); h.in.nozP = NAN; h.run(5000);
    CHECK("NOZ: 泵不需要转时(EXPOSE 默认)读不到不报", h.c.alarms == 0);
  }
  // ---- NOZ_LOW ----
  {
    Sim s; s.to(NEBULIZE); s.in.nozP = 29.9f; s.run(19400);
    CHECK("NOZ_LOW: 进入 NEBULIZE 泵转满 10 秒 + 低压不足 10 秒不报", !(s.c.alarms & A_NOZ_LOW));
    s.run(1000);
    CHECK("NOZ_LOW: 泵转 10 秒后低压再持续 10 秒触发", (s.c.alarms & A_NOZ_LOW));
    CHECK("NOZ_LOW: 仅提示(泵和四路加热照常,阶段不变)", s.c.out.pumpOn && s.allHeat() && s.c.ph == NEBULIZE);
    CHECK("NOZ_LOW: 不能 ack(自己消失)", !s.cmd("ack") && (s.c.alarms & A_NOZ_LOW));
    s.in.nozP = 30.0f; s.step();
    CHECK("NOZ_LOW: 气压回到 30 自动消失", !(s.c.alarms & A_NOZ_LOW));
    s.in.nozP = 10.0f; s.run(9600);
    bool again = !(s.c.alarms & A_NOZ_LOW); s.run(600);
    CHECK("NOZ_LOW: 再次变低要重新持续 10 秒", again && (s.c.alarms & A_NOZ_LOW));
    s.cmd("expose"); s.step();
    CHECK("NOZ_LOW: 离开 NEBULIZE 自动消失", !(s.c.alarms & A_NOZ_LOW));
    Sim t; t.to(NEBULIZE); t.in.nozP = 30.0f; t.run(60000);
    CHECK("NOZ_LOW: 正好 30 kPa 不报", !(t.c.alarms & A_NOZ_LOW));
    Sim r; r.to(READY); r.in.nozP = 5; r.run(60000);
    CHECK("NOZ_LOW: READY 中不判", r.c.alarms == 0 && r.c.out.pumpOn);
    Sim p; p.to(PREHEAT); p.in.nozP = 0; p.run(60000);
    CHECK("NOZ_LOW: PREHEAT 中不判", !(p.c.alarms & A_NOZ_LOW));
    Sim e; e.cmd("circInExpose", 1); e.to(EXPOSE); e.in.nozP = 5; e.run(60000);
    CHECK("NOZ_LOW: EXPOSE 循环中不判", !(e.c.alarms & A_NOZ_LOW) && e.c.out.pumpOn);
    Sim q; q.to(NEBULIZE); q.in.press = 20; q.in.nozP = 0; q.run(60000);
    CHECK("NOZ_LOW: 泵停着(压力报警)时不判", (q.c.alarms & A_PRESS_HIGH) && !q.c.out.pumpOn && !(q.c.alarms & A_NOZ_LOW));
    q.in.press = 12; q.run(400); q.cmd("ack"); q.run(19000);
    bool qNo = !(q.c.alarms & A_NOZ_LOW); q.run(1600);
    CHECK("NOZ_LOW: 泵恢复后重新等 10 秒再计 10 秒", qNo && (q.c.alarms & A_NOZ_LOW));
  }

  // ================= 6. 消音 =================
  {
    Sim s; s.to(READY); s.in.press = 20; s.run(3400);
    CHECK("消音: 报警时有声", audible(s.c, s.in.now) & A_PRESS_HIGH);
    s.cmd("mute");
    CHECK("消音: mute 后无声且 muted=true", audible(s.c, s.in.now) == 0 && isMuted(s.c, s.in.now));
    s.in.ip1 = 44.0f; s.step();
    CHECK("消音: 新出现的报警照响", (audible(s.c, s.in.now) & A_IP_HIGH) && !(audible(s.c, s.in.now) & A_PRESS_HIGH));
    s.run(120000);
    CHECK("消音: 2 分钟后恢复有声", (audible(s.c, s.in.now) & A_PRESS_HIGH) && !isMuted(s.c, s.in.now));
  }

  // ================= 7. 串口手动测试 =================
  {
    Sim s; s.step();
    CHECK("手动: IDLE 中 heat syr 30% 被接受", cmdManualHeat(s.c, s.in.now, H_SYR, 0.3f)); s.step();
    CHECK("手动: 占空比按给定值输出", fabsf(s.k.duty[H_SYR] - 0.3f) < 1e-5f && s.k.duty[H_NOZ] == 0 && s.c.out.set[H_SYR] == 0);
    CHECK("手动: 占空比超范围拒绝", !cmdManualHeat(s.c, s.in.now, H_SYR, 1.1f) && !cmdManualHeat(s.c, s.in.now, 7, 0.5f) && !cmdManualPump(s.c, s.in.now, -0.1f));
    s.in.syr1 = 43.0f; s.step();
    CHECK("手动: 到 43.0 输出归零", s.k.duty[H_SYR] == 0.0f);
    s.in.syr1 = 43.8f; s.step();
    CHECK("手动: 43.8 照样触发 OVERTEMP_DRUG 并锁定", (s.c.alarms & A_OVERTEMP_DRUG) && !s.c.out.on[H_SYR]);
    CHECK("手动: 锁定后拒绝再开", !cmdManualHeat(s.c, s.in.now, H_NOZ, 0.2f));
    Sim t; t.step(); cmdManualHeat(t.c, t.in.now, H_HUM, 1.0f); t.in.humPlate = 86; t.step();
    CHECK("手动: 底座超 85 输出归零", t.k.duty[H_HUM] == 0.0f);
    t.in.humPlate = 88; t.step();
    CHECK("手动: 底座 88 触发 OVERTEMP_GAS", (t.c.alarms & A_OVERTEMP_GAS) && !t.c.out.on[H_HUM]);
    Sim u; u.step(); cmdManualHeat(u.c, u.in.now, H_TUBE, 0.5f); u.in.gasEnd = NAN; u.run(1200);
    CHECK("手动: 传感器读不到 → 输出为零并报 SENSOR", u.k.duty[H_TUBE] == 0.0f && (u.c.alarms & A_SENSOR));
    Sim v; v.to(PREHEAT);
    CHECK("手动: 非 IDLE 阶段拒绝 heat 和 pump", !cmdManualHeat(v.c, v.in.now, H_SYR, 0.3f) && !cmdManualPump(v.c, v.in.now, 0.3f));
    Sim w; w.step(); cmdManualPump(w.c, w.in.now, 0.4f); w.in.press = 0; w.run(8000);
    CHECK("手动: pump 40% 输出,台架上低压不报 PRESS_LOW", fabsf(w.k.pumpDuty - 0.4f) < 1e-4f && w.c.alarms == 0);
    cmdManualHeat(w.c, w.in.now, H_NOZ, 0.5f); w.step(); w.cmd("preheat"); w.cold(); w.step();
    CHECK("手动: preheat 后手动输出被清除,转入自动控制", w.c.manDuty[H_NOZ] == 0 && w.c.manPump == 0 && w.c.out.set[H_NOZ] == 42.0f);
    Sim x; x.step(); cmdManualHeat(x.c, x.in.now, H_SYR, 0.2f); cmdManualPump(x.c, x.in.now, 0.2f); x.in.syr1 = x.in.syr2 = 30; x.run(600200);
    CHECK("手动: 10 分钟后自动关", x.allOff() && !manualActive(x.c));
    Sim y; y.step(); cmdManualHeat(y.c, y.in.now, H_NOZ, 0.5f); y.in.noz1 = y.in.noz2 = 30; y.step();
    CHECK("手动: heat noz 50% 按给定值输出", fabsf(y.k.duty[H_NOZ] - 0.5f) < 1e-5f);
    y.in.noz2 = 43.0f; y.step();
    CHECK("手动: noz 保护传感器到 43.0 输出归零", y.k.duty[H_NOZ] == 0.0f);
    Sim mb; mb.step(); cmdManualPump(mb.c, mb.in.now, 1.0f); mb.in.nozP = 170; mb.run(3400);
    CHECK("手动: 测泵时 NOZ_BLOCK 照样起作用", (mb.c.alarms & A_NOZ_BLOCK) && mb.k.pumpDuty == 0.0f);
    Sim mn; mn.step(); cmdManualPump(mn.c, mn.in.now, 0.3f); mn.in.nozP = NAN; mn.in.press = NAN; mn.run(5000);
    CHECK("手动: 测泵时两只压力传感器没接不报 SENSOR", mn.c.alarms == 0 && mn.k.pumpDuty > 0);
  }

  // ================= 8. 其他 =================
  {
    CHECK("名称: 报警名与位一一对应", !strcmp(ALARM_NAME[0], "OVERTEMP_DRUG") && !strcmp(ALARM_NAME[3], "SENSOR") && !strcmp(ALARM_NAME[7], "NOZ_BLOCK") && !strcmp(ALARM_NAME[8], "NOZ_LOW") && !strcmp(ALARM_NAME[11], "EXPOSE_END") && A_EXPOSE_END == (1 << 11) && ALARM_COUNT == 12);
    CHECK("名称: 阶段名", !strcmp(PHASE_NAME[NEBULIZE], "NEBULIZE") && !strcmp(PHASE_NAME[DONE], "DONE"));
    CHECK("级别: 高级与锁定集合", A_HIGH == 0xBF && (A_HIGH & A_NOZ_BLOCK) && !(A_HIGH & A_NOZ_LOW) && !(A_LATCHED & (A_NOZ_BLOCK | A_NOZ_LOW)) && A_LATCHED == (A_OVERTEMP_DRUG | A_OVERTEMP_GAS | A_SENSOR));
    Sim s; s.to(READY); uint32_t t0 = s.in.now; s.run(10000);
    CHECK("phSec: 按进入阶段起算", phaseSec(s.c, s.in.now) >= 10 && phaseSec(s.c, s.in.now) <= 11 && s.in.now - t0 == 10000);
    Sim h; h.to(READY); h.in.ip1 = 44; h.step(); h.run(61000);
    CHECK("READY: 高级报警持续 60 秒也掉回 PREHEAT", h.c.ph == PREHEAT);
    h.in.ip1 = 41.5f; h.run(2000);
    CHECK("READY: 高级报警没清时不会重新进 READY", h.c.ph == PREHEAT && h.allOff());
  }

  if (fails) printf("%d FAILED (of %d)\n", fails, total); else printf("ALL PASS (%d checks)\n", total);
  return fails ? 1 : 0;
}
