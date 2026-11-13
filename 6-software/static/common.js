// 触摸屏本机界面和主机面板模拟两个页面共用的表和小函数。
// 阶段、报警、命令的含义以 1-design/interface-spec.md 为准,改约定时这里要同时改。
'use strict';

const PH_CN = {IDLE: '待机', PREHEAT: '预热', READY: '就绪', NEBULIZE: '喷雾', EXPOSE: '暴露', EVAC: '排气', DONE: '结束'};
const STEPS = ['PREHEAT', 'READY', 'NEBULIZE', 'EXPOSE', 'EVAC', 'DONE'];

// lv: high 高级 / mid 中级。did: 设备已经做了什么(一行)。steps: 处理步骤,最多三步,第一步最要紧,每步一行。
// ack: 这条报警要按“确认报警”才清除。顺序就是严重程度,越靠前越严重。
const ALARMS = {
  OVERTEMP_DRUG: {lv: 'high', cn: '药液通路过温', did: '注射筒和喷头歧管加热已关。', ack: false, steps: ['停用这一筒药液', '检查加热套和喷头歧管', '重新上电才能清除']},
  OVERTEMP_GAS: {lv: 'high', cn: '气体通路过温', did: '加湿、输气管加热和循环泵已关。', ack: false, steps: ['检查加湿罐和输气管', '重新上电才能清除']},
  IP_HIGH: {lv: 'high', cn: '腹腔温度过高', did: '四路加热和循环泵已全关。', ack: true, steps: ['等腹腔降到 42.5 ℃ 以下', '再按“确认报警”恢复']},
  NOZ_BLOCK: {lv: 'high', cn: '喷头堵塞', did: '循环泵已停,不成雾。', ack: true, steps: ['检查喷嘴是否堵塞', '检查输气管有没有打折', '排除后按“确认报警”']},
  PRESS_HIGH: {lv: 'high', cn: '腹腔压力过高', did: '循环泵已停。', ack: true, steps: ['检查气腹机设定和排气', '压力回落后按“确认报警”']},
  PRESS_LOW: {lv: 'high', cn: '腹腔压力过低', did: '循环泵已停,可能漏气。', ack: true, steps: ['检查穿刺器和回路漏气', '查明后按“确认报警”']},
  SENSOR: {lv: 'high', cn: '温度传感器故障', did: '对应的加热已关。', ack: false, steps: ['检查温度探头和插头', '重新上电才能清除']},
  WATER_LOW: {lv: 'mid', cn: '加湿罐可能缺水', did: '加湿底座加热已关。', ack: true, steps: ['给加湿罐加水', '加好后按“确认报警”']},
  NOZ_LOW: {lv: 'mid', cn: '雾化气压不足', did: '低于 30 kPa,雾滴会变粗。', ack: false, steps: ['检查喷头接口是否漏气', '在详情里调高雾化气流量']},
  IP_LOW: {lv: 'mid', cn: '腹腔温度偏低', did: '比目标低 2 ℃ 已 5 分钟。', ack: false, steps: ['检查腹腔探头位置', '可在详情里打开暴露循环']},
  EXPOSE_END: {lv: 'mid', cn: '暴露计时到', did: '已转入排气,加热和泵全关。', ack: true, steps: ['按“确认报警”', '然后经密闭系统排气']},
  PREHEAT_SLOW: {lv: 'mid', cn: '预热超过 60 分钟', did: '只是提示,设备没有动作。', ack: false, steps: ['检查气腹是否已建立', '检查各路是否在升温']},
};
const ALARM_ORDER = Object.keys(ALARMS);
function alarmInfo(a) { return ALARMS[a] || {lv: 'high', cn: a, did: '', ack: false, steps: []}; }
function alarmLevel(al) {
  if (!al || !al.length) return '';
  return al.some(a => alarmInfo(a).lv === 'high') ? 'high' : 'mid';
}
// 按严重程度排好的报警列表;不认识的报警当高级,排最前
function alarmsSorted(al) {
  const rank = a => { const i = ALARM_ORDER.indexOf(a); return i < 0 ? -1 : i; };
  return (al || []).slice().sort((x, y) => rank(x) - rank(y));
}

// 各阶段主屏写什么(1-design/touchscreen-ui.md 第 5 节)。step: 第几步(共 5 步)。
// kind/label: 唯一的主按钮;没有 kind 表示这一阶段不需要人做事。confirm: 按了还要再确认一次。
const ACTION = {
  IDLE: {step: 0, kind: 'preheat', label: '开始预热', next: '装好喷头和回路、建立气腹后开始预热。'},
  PREHEAT: {step: 1, kind: 'ready', label: '不等腹腔,直接就绪', next: '等待各项到温,到温后自动进入就绪。腹腔温度可以不等,手动确认。'},
  READY: {step: 2, kind: 'nebulize', label: '开始喷雾', next: '按“开始喷雾”,等雾化气压稳定后启动注射泵。'},
  NEBULIZE: {step: 3, kind: 'expose', label: '喷雾结束', next: '启动注射泵推药。推完后按下面的按钮。'},
  EXPOSE: {step: 4, next: '无需操作。药雾停留,剩余时间见右上角。', early: {kind: 'evac', label: '提前结束暴露', confirm: '提前结束暴露?', detail: '马上转入排气阶段,暴露计时停止,不能恢复。'}},
  EVAC: {step: 5, kind: 'finish', label: '排气完成', next: '经密闭排气系统排空气腹。排完后按下面的按钮。'},
  DONE: {step: 0, kind: 'finish', label: '回到待机', next: '本次记录已保存。'},
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}
function isNum(v) { return typeof v === 'number' && isFinite(v); }
function fx(v, n) { return isNum(v) ? v.toFixed(n === undefined ? 1 : n) : '--'; }
function mmss(sec) {
  if (!isNum(sec) || sec < 0) return '--:--';
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60, p = x => String(x).padStart(2, '0');
  return h ? h + ':' + p(m) + ':' + p(s) : p(m) + ':' + p(s);
}
function ipMean(t) {
  const v = [t && t.ip1, t && t.ip2].filter(isNum);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}
// 预热转就绪的四个条件,和固件的判断一致
function readiness(L) {
  const t = (L && L.t) || {}, tg = L && L.target, near = k => isNum(t[k]) && isNum(tg) && Math.abs(t[k] - tg) <= 0.5, m = ipMean(t);
  const r = {syr: near('syr1') && near('syr2'), noz: near('noz1') && near('noz2'),
    gas: isNum(t.gasEnd) && isNum(tg) && t.gasEnd >= tg - 1, ip: isNum(m) && isNum(tg) && m >= tg - 1};
  r.heat = r.syr && r.noz && r.gas;
  return r;
}
// 某一路在当前阶段是否应该在加热(只用来决定显示“设定值”还是“关”)
function channelOn(L, ch) {
  const ph = L && L.ph;
  if (ch === 'syr' || ch === 'noz') return ph === 'PREHEAT' || ph === 'READY' || ph === 'NEBULIZE';
  if (ch === 'hum' || ch === 'tube') return ph === 'PREHEAT' || ph === 'READY' || ph === 'NEBULIZE' || ph === 'EXPOSE';
  return (ph === 'PREHEAT' && isNum(L.press) && L.press >= 8) || ph === 'READY' || ph === 'NEBULIZE' || (ph === 'EXPOSE' && !!L.circInExpose);
}
// 喷雾阶段雾化气停了:这些报警会把循环泵关掉,而推药的注射泵是独立设备,还在推。
// 这时药液不成雾、直接滴进腹腔,页面必须用最醒目的方式叫人立即停注射泵。
const PUMP_STOP_ALARMS = ['PRESS_HIGH', 'PRESS_LOW', 'NOZ_BLOCK', 'SENSOR', 'IP_HIGH', 'OVERTEMP_GAS'];
function nebStopped(L) {
  if (!L || L.ph !== 'NEBULIZE') return false;
  return !(L.duty && L.duty.pump > 0) || (L.al || []).some(a => PUMP_STOP_ALARMS.includes(a));
}
// 给“立即停止注射泵”配的一行原因
function nebStopWhy(L) {
  const why = ((L && L.al) || []).filter(a => PUMP_STOP_ALARMS.includes(a)).map(a => alarmInfo(a).cn);
  return why.length ? '原因:' + why.join('、') + '。' : '原因:循环泵没有在转。';
}
// 泵现在该按哪个流量转:喷雾阶段是雾化气流量,其余阶段是循环流量
function pumpSet(L) { return L && L.ph === 'NEBULIZE' ? L.nebFlow : L && L.flowSet; }
// 主机上的指示灯和蜂鸣器,按面板规则用服务器收到的数据重画
function ledState(L, nowMs) {
  // 喷雾中雾化气停了也按高级报警处理:红灯快闪、蜂鸣器急响
  const al = (L && L.al) || [], lv = nebStopped(L) ? 'high' : alarmLevel(al), ph = L && L.ph, fast = Math.floor(nowMs / 200) % 2 === 1;
  return {
    red: lv === 'high' && fast,
    yellow: al.some(a => alarmInfo(a).lv === 'mid'),
    green: ph === 'READY' || ph === 'NEBULIZE' || ph === 'EXPOSE' || (ph === 'PREHEAT' && Math.floor(nowMs / 1000) % 2 === 1),
    buzz: !(L && L.muted) && (lv === 'high' ? fast : lv === 'mid' && nowMs % 2000 < 200),
  };
}
async function getJSON(url) {
  const r = await fetch(url, {cache: 'no-store'});
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
}
// 返回 {ok, err, ...服务器的回答}。网络断了也不抛异常。
async function postJSON(url, body) {
  try {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const j = await r.json().catch(() => ({}));
    return Object.assign({}, j, {ok: r.ok, err: r.ok ? '' : (j.err || '操作没有成功(HTTP ' + r.status + ')')});
  } catch (e) {
    return {ok: false, err: '连不上盒内服务程序,命令没有发出'};
  }
}

if (typeof module !== 'undefined') module.exports = {PH_CN, STEPS, ALARMS, ACTION, alarmInfo, alarmLevel, alarmsSorted, esc, fx, mmss, ipMean, readiness, channelOn, pumpSet, ledState, PUMP_STOP_ALARMS, nebStopped, nebStopWhy};
