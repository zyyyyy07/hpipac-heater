// 触摸屏本机界面和主机面板模拟两个页面共用的表和小函数。
// 阶段、报警、命令的含义以 1-design/interface-spec.md 为准,改约定时这里要同时改。
'use strict';

const PH_CN = {IDLE: '待机', PREHEAT: '预热', READY: '就绪', NEBULIZE: '喷雾', EXPOSE: '暴露', EVAC: '排气', DONE: '结束'};
const STEPS = ['PREHEAT', 'READY', 'NEBULIZE', 'EXPOSE', 'EVAC', 'DONE'];

// lv: high 高级 / mid 中级。did: 设备已经做了什么。fix: 怎样才能清除。
const ALARMS = {
  OVERTEMP_DRUG: {lv: 'high', cn: '药液通路过温', did: '已关闭注射筒加热套和喷头歧管加热。', fix: '锁定,重新上电才能清除。'},
  OVERTEMP_GAS: {lv: 'high', cn: '气体通路过温', did: '已关闭加湿底座、输气管加热和循环泵。', fix: '锁定,重新上电才能清除。'},
  IP_HIGH: {lv: 'high', cn: '腹腔温度过高', did: '四路加热和循环泵已全部关闭。', fix: '降到 42.5 ℃ 以下后点“确认报警”才恢复。'},
  SENSOR: {lv: 'high', cn: '温度传感器故障', did: '已关闭对应的加热通路。', fix: '锁定,重新上电才能清除。'},
  PRESS_HIGH: {lv: 'high', cn: '腹腔压力过高', did: '已关闭循环泵。', fix: '压力回落后点“确认报警”。'},
  PRESS_LOW: {lv: 'high', cn: '腹腔压力过低,可能漏气', did: '已关闭循环泵。', fix: '查明原因后点“确认报警”,循环泵才恢复。'},
  WATER_LOW: {lv: 'mid', cn: '加湿罐可能缺水', did: '已关闭加湿底座加热。', fix: '加水后点“确认报警”,加热才恢复。'},
  NOZ_BLOCK: {lv: 'high', cn: '喷头堵塞', did: '雾化气压超过 150 kPa,已关闭循环泵,现在不成雾。', fix: '检查喷嘴有没有堵、输气管有没有打折,排除后点“确认报警”,循环泵才恢复。'},
  NOZ_LOW: {lv: 'mid', cn: '雾化气压不足', did: '雾化气压低于 30 kPa,雾滴会变粗。只是提示,设备没有做任何动作。', fix: '检查输气管和喷头接口有没有漏气、雾化气流量是不是设得太低。气压回升后自动消失。'},
  PREHEAT_SLOW: {lv: 'mid', cn: '预热超过 60 分钟', did: '只是提示,设备没有做任何动作。', fix: ''},
  IP_LOW: {lv: 'mid', cn: '腹腔温度偏低', did: '比目标低 2 ℃ 以上已持续 5 分钟。只是提示,设备没有做任何动作。', fix: ''},
  EXPOSE_END: {lv: 'mid', cn: '暴露计时到', did: '已转入排气阶段,加热和循环泵全关。', fix: '点“确认报警”清除。'},
};
function alarmInfo(a) { return ALARMS[a] || {lv: 'high', cn: a, did: '', fix: ''}; }
function alarmLevel(al) {
  if (!al || !al.length) return '';
  return al.some(a => alarmInfo(a).lv === 'high') ? 'high' : 'mid';
}

// 每个阶段只有一个主操作。confirm: 点了以后还要再确认一次。
const ACTION = {
  IDLE: {kind: 'preheat', label: '开始预热', hint: '四路加热和循环泵会同时启动。'},
  PREHEAT: {kind: 'ready', label: '手动确认就绪', hint: '气腹建立(压力到 8 mmHg)后循环泵才转。条件都满足时会自动转入就绪。腹腔温度迟迟不到时,可以在四路到温后手动确认。'},
  READY: {kind: 'nebulize', label: '开始喷雾', hint: '点了以后循环泵改按雾化气流量送气。等雾化气压稳定,再启动注射泵推药。', short: '点后循环泵改送雾化气,气压稳定后再启动注射泵。'},
  NEBULIZE: {kind: 'expose', label: '喷雾结束,开始计时', hint: '循环泵正在送雾化气,泵一停就不成雾。注射泵推完药后点这里,开始暴露计时,注射筒和喷头歧管加热会关闭。', short: '循环泵正在送雾化气。注射泵推完药后点下面的按钮。'},
  EXPOSE: {kind: 'evac', label: '提前结束', hint: '计时到了会自动转入排气。', confirm: '提前结束暴露,转入排气?'},
  EVAC: {kind: 'finish', label: '结束手术', hint: '经密闭排气系统把气腹排空之后再点。'},
  DONE: {kind: 'finish', label: '确认,回到待机', hint: '本次手术已结束,记录已自动保存。'},
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

if (typeof module !== 'undefined') module.exports = {PH_CN, STEPS, ALARMS, ACTION, alarmInfo, alarmLevel, esc, fx, mmss, ipMean, readiness, channelOn, pumpSet, ledState, PUMP_STOP_ALARMS, nebStopped, nebStopWhy};
