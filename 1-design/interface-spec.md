[← 设计方案](README.md) · [总览](../README.md)

# 接口约定(固件、服务器、页面共用)

这份文件是固件、服务器和控制台页面之间的约定。改了一处,另外两处要同时改。

## 1. 系统组成

hPIPAC 前端加热系统由一台主机和四路加热组成。主机不控制高压注射器和气腹机,这两台是独立的成品设备。

| 代号 | 名称 | 加热什么 | 控制目标 | 硬上限 |
| --- | --- | --- | --- | --- |
| SYR | 注射筒加热套 | 高压注射器针筒里的药液 | 套温 = 目标温度 | 套温 43.0 ℃ |
| LINE | 高压管保温板 | 注射器到喷头之间的高压管 | 板温 = 目标温度 | 板温 43.0 ℃ |
| HUM | 加湿加热底座 | 加湿罐里的水,使 CO₂ 加热加湿 | 罐出口气温 = 目标温度 + 1 ℃ | 底座 85 ℃,出口气温 45 ℃ |
| TUBE | 加热输气管 | 加湿罐到穿刺器的输气管 | 病人端气温 = 目标温度 | 病人端气温 43.5 ℃ |

另有一台循环泵 PUMP,把腹腔里的 CO₂ 经过滤器抽出、加热加湿后送回,流量 0–15 L/min。

目标温度 `target`:37.0–43.0 ℃,默认 42.0 ℃。药液通路上任何加热面的设定值都不超过 43.0 ℃。

## 2. 传感器

| 字段 | 含义 | 单位 |
| --- | --- | --- |
| `syr1`, `syr2` | 注射筒加热套温度(控制、保护各一只) | ℃ |
| `line1`, `line2` | 高压管保温板温度(控制、保护各一只) | ℃ |
| `lineOut` | 高压管出保温板处的管壁温度 | ℃ |
| `humPlate` | 加湿底座温度 | ℃ |
| `humOut` | 加湿罐出口气温 | ℃ |
| `gasEnd` | 输气管病人端气温 | ℃ |
| `ip1`, `ip2` | 腹腔内温度探头 1、2 | ℃ |
| `press` | 腹腔压力(循环回路上测) | mmHg |
| `flow` | 循环流量 | L/min |

传感器开路或短路时固件上报 `null`。

## 3. 阶段

```
IDLE → PREHEAT → READY → NEBULIZE → EXPOSE → EVAC → DONE → IDLE
```

| 阶段 | 含义 | 加热 | 循环泵 |
| --- | --- | --- | --- |
| IDLE | 待机 | 全关 | 关 |
| PREHEAT | 预热:药液、高压管、加湿器升温;气腹建立后循环 CO₂ 给腹腔升温 | 四路全开 | `press` ≥ 8 mmHg(气腹已建立)后按设定流量,之前不转 |
| READY | 就绪:四路都到温,腹腔温度到目标 − 1 ℃ 以内(或操作者手动确认) | 保持 | 按设定流量 |
| NEBULIZE | 喷雾:操作者启动高压注射器 | SYR、LINE 保持;HUM、TUBE 保持 | 关(不把气溶胶抽走) |
| EXPOSE | 暴露计时(默认 30 分钟) | SYR 关;LINE 关;HUM、TUBE 保持 | 由 `circInExpose` 决定,默认关 |
| EVAC | 排气:提示操作者经密闭排气系统排空气腹 | 全关 | 关 |
| DONE | 结束,等待确认 | 全关 | 关 |

转换:
- `preheat` 命令:IDLE → PREHEAT。
- PREHEAT → READY:自动。条件是 SYR、LINE 的两只传感器都在目标 ±0.5 ℃ 内,`gasEnd` ≥ 目标 − 1 ℃,并且 `ip1`、`ip2` 的平均值 ≥ 目标 − 1 ℃。腹腔条件可用 `ready` 命令手动跳过。
- READY 掉回 PREHEAT:任一条件失去超过 60 秒。
- `nebulize` 命令:READY → NEBULIZE。只允许从 READY 进入。
- `expose` 命令:NEBULIZE → EXPOSE,开始计时。
- EXPOSE → EVAC:计时到 `exposeMin` 自动转,或 `evac` 命令提前转。
- `finish` 命令要发两次:第一次 EVAC → DONE,第二次 DONE → IDLE。
- 循环泵不转的时候(气腹未建立、喷雾、暴露默认、压力报警后),HUM 的底座温度上限从 85 ℃ 降到 60 ℃ 待机,避免没有气流时把底座烧到很高。
- `abort` 命令:任何阶段 → EVAC(加热和泵立即全关)。

## 4. 报警

高级报警立即把相关加热和循环泵关掉。带“锁定”的只有重新上电才能清除。

| 名称 | 条件 | 级别 | 动作 |
| --- | --- | --- | --- |
| `OVERTEMP_DRUG` | `syr1/2` 或 `line1/2` ≥ 43.8 ℃ | 高,锁定 | SYR、LINE 关 |
| `OVERTEMP_GAS` | `gasEnd` ≥ 44.5 ℃,或 `humOut` ≥ 46 ℃,或 `humPlate` ≥ 88 ℃ | 高,锁定 | HUM、TUBE、PUMP 关 |
| `IP_HIGH` | `ip1` 或 `ip2` ≥ 43.5 ℃ | 高 | 四路全关,PUMP 关;降到 42.5 ℃ 以下并经 `ack` 才恢复 |
| `SENSOR` | 成对传感器相差 > 1.5 ℃ 持续 10 秒,或任一控制用传感器为 `null` | 高,锁定 | 对应通路关 |
| `PRESS_HIGH` | `press` ≥ 18 mmHg 持续 3 秒 | 高 | PUMP 关 |
| `PRESS_LOW` | 循环泵运转中 `press` ≤ 6 mmHg 持续 5 秒。泵没转时不判 | 高 | PUMP 关(可能漏气),`ack` 后恢复 |
| `WATER_LOW` | 循环泵已连续运转 ≥ 120 秒,`humPlate` ≥ 75 ℃ 而 `humOut` 低于目标 3 ℃ 以上,持续 120 秒。泵没转时不判 | 中 | HUM 关,`ack` 后恢复 |
| `LID` | 高压管保温板没合上 | 中 | LINE 关 |
| `PREHEAT_SLOW` | PREHEAT 超过 60 分钟 | 中 | 仅提示 |
| `IP_LOW` | EXPOSE 中 `ip` 平均值低于目标 2 ℃ 以上,持续 5 分钟 | 中 | 仅提示 |
| `EXPOSE_END` | 暴露计时到 | 中 | 仅提示 |

## 5. 遥测(固件 → 服务器)

固件每 2 秒 `POST /api/device/telemetry`,JSON:

```json
{"id":"HP-001","ph":"PREHEAT","target":42.0,"exposeMin":30,"flowSet":10.0,"circInExpose":false,
 "t":{"syr1":41.8,"syr2":41.7,"line1":42.0,"line2":41.9,"lineOut":40.6,"humPlate":61.2,"humOut":43.0,"gasEnd":41.6,"ip1":40.2,"ip2":39.8},
 "press":12.1,"flow":9.8,
 "duty":{"syr":35,"line":20,"hum":60,"tube":40,"pump":65},
 "phSec":412,"exposeLeft":-1,"al":["IP_LOW"],"muted":false}
```

- `ph`:阶段名。`phSec`:进入当前阶段的秒数。`exposeLeft`:暴露剩余秒数,不在 EXPOSE 时为 −1。
- `duty`:各路输出占空比,0–100。
- 服务器的响应体:`{"cmds":[...]}`,每条命令形如 `{"kind":"preheat"}` 或 `{"kind":"target","value":41.5}`。

## 6. 命令

| `kind` | `value` | 说明 |
| --- | --- | --- |
| `preheat` | — | 开始预热 |
| `ready` | — | 手动确认就绪(跳过腹腔温度条件) |
| `nebulize` | — | 标记喷雾开始 |
| `expose` | — | 标记喷雾结束,开始暴露计时 |
| `evac` | — | 提前结束暴露 |
| `finish` | — | 结束本次手术 |
| `abort` | — | 中止:加热和泵全关,进入 EVAC |
| `target` | 37.0–43.0 | 改目标温度 |
| `flow` | 0–15 | 改循环流量 L/min |
| `exposeMin` | 1–60 | 改暴露时间 |
| `circInExpose` | true/false | 暴露阶段是否循环 |
| `ack` | — | 确认可恢复的报警 |
| `mute` | — | 消音 2 分钟 |

固件拒绝超范围的值和当前阶段不允许的命令。

## 7. 服务器接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/device/telemetry` | 设备上报,返回待执行命令 |
| GET | `/api/state` | 返回 `{now, devices:[{id, online, last, case}], }` |
| POST | `/api/cmd` | `{dev, kind, value, by}`,排入该设备的命令队列。`by`(操作人)必填 |
| POST | `/api/case/start` | `{dev, label, by}`,开始记录一次手术。`label` 是手术编号,不要填病人姓名 |
| POST | `/api/case/end` | `{dev, by}` |
| GET | `/api/case/log?dev=&case=` | 返回该次手术的全部遥测记录(CSV) |
| GET | `/api/history?dev=&sec=` | 最近若干秒的遥测点,供页面画曲线 |
| GET | `/`、`/console` | 手术控制台页面 |
| GET | `/panel` | 主机面板模拟页面 |

设备 5 秒没有上报视为离线。
