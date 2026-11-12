[← 上一步:固件](../5-firmware/README.md) · [总览](../README.md) · [下一步:测试 →](../7-testing/README.md)

# 第 6 步 · 架服务器、设置触摸屏

这一步不需要硬件也能做,可以最先做,先看到整套软件的效果。

任意一台装了 Python 3.9 以上的电脑,和设备在同一个 Wi-Fi 下。不需要安装任何依赖。

```
cd 6-software
python server.py
```

- 配液端:`http://电脑IP:8080/pharmacy`
- 护士站大屏:`http://电脑IP:8080/ward`
- 床旁屏(主机触摸屏上显示的就是这一页):`http://电脑IP:8080/bedside?dev=IW-001`
- 主机面板模拟(不用硬件看触摸屏、指示灯、按键的样子):`http://电脑IP:8080/panel?dev=IW-001`
- 没有硬件时先看效果:另开一个窗口运行 `python simulator.py http://127.0.0.1:8080 4 20`,会出现 4 台模拟设备,时间加速 20 倍。
- 自测:`python test_flow.py`,最后一行应为 ALL PASS。

设备第一次上线会出现在大屏上显示“未绑定”,在那里填床号绑定。药品加温上限表在 `server.py` 顶部的 `DRUGS`,现在是演示数值,必须由药剂科审核后替换。

> 样机服务器没有登录和加密,页面也没有对输入做转义。只能在单独的测试网络里用,不要接入医院业务网,不要录入真实病人信息。

## 设置触摸屏

主控盒里的树莓派负责驱动触摸屏。给树莓派装好带桌面的 Raspberry Pi OS、连上同一个 Wi-Fi 后,把 [kiosk/setup-kiosk.sh](kiosk/setup-kiosk.sh) 拷过去运行一次:

```
sh setup-kiosk.sh http://电脑IP:8080 IW-001
```

重启后会自动全屏打开床旁页面。这个脚本没有在树莓派上运行过。

## 文件说明

| 文件 | 内容 | 验证情况 |
| --- | --- | --- |
| [server.py](server.py) | 服务器,Python 标准库,无依赖 | `test_flow.py` 27 项通过 |
| [static/](static/) | 配液端、护士站大屏、床旁屏、主机面板模拟四个页面 | 已在浏览器中用模拟设备操作过 |
| [simulator.py](simulator.py) | 设备模拟器 | 已运行 |
| [test_flow.py](test_flow.py) | 全流程自测 | — |
| [kiosk/](kiosk/) | 树莓派开机全屏脚本 | 没有在真机上运行过 |

---

[← 上一步:固件](../5-firmware/README.md) · [总览](../README.md) · [下一步:测试 →](../7-testing/README.md)
