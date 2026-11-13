#!/bin/sh
# 把主控盒里的树莓派设置成“盒内服务程序 + 触摸屏本机界面”。
#
# !!! 这个脚本从来没有在树莓派上运行过。第一次用请接显示器和键盘,对照每一步的输出检查。!!!
#
# 它做三件事:
#   1. 装一个 systemd 服务,开机自动运行 server.py(盒内服务程序,端口 8080);
#   2. 用 NetworkManager(nmcli)把 wlan0 设成只供盒内使用的 Wi-Fi 热点,树莓派地址固定为 10.42.0.1,
#      安全主控 ESP32 连这个热点,服务程序地址是 http://10.42.0.1:8080;
#   3. 桌面登录后自动等服务程序能连上,再全屏打开 http://127.0.0.1:8080/local?dev=设备编号。
#
# 用法(在树莓派上,把整个 6-software 文件夹拷过去,在里面运行):
#   sh kiosk/setup-kiosk.sh HP-001 HP-001-box 热点密码至少8位
# 前提:带桌面的 Raspberry Pi OS(Bookworm 或更新,网络由 NetworkManager 管),已装 python3 和 chromium。
# 热点只给 ESP32 用,不要把树莓派的网口或 Wi-Fi 接到医院网络。
set -e
USAGE="用法: sh kiosk/setup-kiosk.sh 设备编号 热点名称 热点密码(至少 8 位)"
DEV="${1:?$USAGE}"
SSID="${2:?$USAGE}"
PSK="${3:?$USAGE}"
[ "${#PSK}" -ge 8 ] || { echo "热点密码至少要 8 位"; exit 1; }
case "$DEV" in *[!A-Za-z0-9_-]*) echo "设备编号只能用字母、数字、横线和下划线"; exit 1;; esac

APPDIR="$(cd "$(dirname "$0")/.." && pwd)"
DATADIR="$HOME/hp-data"          # 手术记录 CSV 和操作日志放在这里,手术后从这里拷出来
PORT=8080
AP_ADDR=10.42.0.1
URL="http://127.0.0.1:$PORT/local?dev=$DEV"
[ -f "$APPDIR/server.py" ] || { echo "在 $APPDIR 下没有找到 server.py。请在 6-software 文件夹里运行这个脚本。"; exit 1; }
PY="$(command -v python3 || true)"
[ -n "$PY" ] || { echo "没有找到 python3"; exit 1; }
BROWSER="$(command -v chromium-browser || command -v chromium || true)"
[ -n "$BROWSER" ] || { echo "没有找到 Chromium,请先执行: sudo apt install chromium-browser"; exit 1; }
command -v nmcli >/dev/null || { echo "没有找到 nmcli。这个脚本要求网络由 NetworkManager 管理。"; exit 1; }
mkdir -p "$DATADIR"

# ---------- 1. 开机运行盒内服务程序 ----------
echo "[1/3] 安装 systemd 服务 hp-server"
sudo tee /etc/systemd/system/hp-server.service >/dev/null <<UNIT
[Unit]
Description=hPIPAC 加热系统 盒内服务程序
After=network.target

[Service]
User=$(id -un)
WorkingDirectory=$APPDIR
Environment=PORT=$PORT
Environment=HP_DATA_DIR=$DATADIR
Environment=PYTHONIOENCODING=utf-8
ExecStart=$PY $APPDIR/server.py
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now hp-server.service

# ---------- 2. 盒内 Wi-Fi 热点 ----------
echo "[2/3] 设置热点 $SSID(地址 $AP_ADDR)"
sudo nmcli connection delete hp-box >/dev/null 2>&1 || true
sudo nmcli connection add type wifi ifname wlan0 con-name hp-box autoconnect yes ssid "$SSID" \
  802-11-wireless.mode ap 802-11-wireless.band bg \
  ipv4.method shared ipv4.addresses "$AP_ADDR/24" ipv6.method disabled \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
  connection.autoconnect-priority 100
sudo nmcli connection up hp-box

# ---------- 3. 桌面登录后全屏打开本机界面 ----------
echo "[3/3] 设置开机全屏打开 $URL"
cat > "$HOME/hp-kiosk.sh" <<RUN
#!/bin/sh
# 等盒内服务程序能连上再打开页面,连不上就一直等
until curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/api/state"; do sleep 2; done
exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \\
  --check-for-update-interval=31536000 --overscroll-history-navigation=0 --disable-pinch "$URL"
RUN
chmod +x "$HOME/hp-kiosk.sh"

# 传统桌面(X11)和多数桌面环境读这里
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/hp-kiosk.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=hPIPAC local screen
Exec=$HOME/hp-kiosk.sh
DESK

# 新版 Raspberry Pi OS 的 labwc 桌面读这里
if [ -d "$HOME/.config/labwc" ] && ! grep -qs hp-kiosk "$HOME/.config/labwc/autostart"; then
  echo "$HOME/hp-kiosk.sh &" >> "$HOME/.config/labwc/autostart"
fi

echo
echo "已设置。请重启树莓派检查:"
echo "  - 触摸屏应全屏显示本机界面,主控没连上时显示“等待主控连接”;"
echo "  - ESP32 连热点 $SSID,服务程序地址 http://$AP_ADDR:$PORT;"
echo "  - 手术记录在 $DATADIR/cases/ 下。"
echo "查看服务程序: systemctl status hp-server    退出全屏: 接键盘按 Alt+F4"
echo "撤销: sudo systemctl disable --now hp-server; sudo nmcli connection delete hp-box; rm ~/.config/autostart/hp-kiosk.desktop"
