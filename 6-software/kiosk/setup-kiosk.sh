#!/bin/sh
# 让主机里驱动 7 英寸触摸屏的小电脑(树莓派)开机后自动全屏打开本机页面 /local。
# 在树莓派上运行一次:  sh setup-kiosk.sh http://服务器地址:8080 HP-001
# 适用于带桌面的 Raspberry Pi OS。这个脚本没有在真机上运行过,第一次用请对照输出检查。
set -e
SERVER="${1:?用法: sh setup-kiosk.sh http://服务器地址:8080 设备编号}"
DEV="${2:?用法: sh setup-kiosk.sh http://服务器地址:8080 设备编号}"
URL="$SERVER/local?dev=$DEV"
BROWSER="$(command -v chromium-browser || command -v chromium || true)"
[ -n "$BROWSER" ] || { echo "没有找到 Chromium,请先执行: sudo apt install chromium-browser"; exit 1; }

cat > "$HOME/hp-kiosk.sh" <<RUN
#!/bin/sh
# 等服务器能连上再打开页面,连不上就一直等
until curl -s -o /dev/null --max-time 3 "$SERVER/api/state"; do sleep 3; done
exec "$BROWSER" --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
  --check-for-update-interval=31536000 --overscroll-history-navigation=0 "$URL"
RUN
chmod +x "$HOME/hp-kiosk.sh"

# 传统桌面(X11)和多数桌面环境读这里
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/hp-kiosk.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=hPIPAC local screen kiosk
Exec=$HOME/hp-kiosk.sh
DESK

# 新版 Raspberry Pi OS 的 labwc 桌面读这里
if [ -d "$HOME/.config/labwc" ] && ! grep -qs hp-kiosk "$HOME/.config/labwc/autostart"; then
  echo "$HOME/hp-kiosk.sh &" >> "$HOME/.config/labwc/autostart"
fi

echo "已设置。重启后会自动全屏打开: $URL"
echo "退出全屏: 接键盘按 Alt+F4。取消自启: 删除 ~/.config/autostart/hp-kiosk.desktop"
