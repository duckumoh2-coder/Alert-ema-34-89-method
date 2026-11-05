# -*- coding: utf-8 -*-
"""
Bot cảnh báo giá chạm EMA 34 / EMA 89 khung H1 và H4 (Binance) -> gửi Telegram.
Chạy miễn phí bằng GitHub Actions, mỗi 5 phút một lần. Không cần cài thêm thư viện.

Cấu hình qua biến môi trường (đặt trong GitHub: Settings -> Secrets and variables -> Actions):
  TELEGRAM_TOKEN   (Secret)   token bot lấy từ @BotFather
  TELEGRAM_CHAT_ID (Secret)   chat id của bạn
  SYMBOLS          (Variable) danh sách cặp, cách nhau bằng dấu phẩy, ví dụ: BTCUSDT,ETHUSDT,SOLUSDT
  TOL_PCT          (Variable) dung sai chạm, % (mặc định 0.05)
  REARM_PCT        (Variable) giá phải rời EMA bao nhiêu % thì mới báo lại lần chạm sau (mặc định 0.3)
"""
import json, os, sys, urllib.request, urllib.parse

SYMBOLS   = [s.strip().upper() for s in (os.environ.get("SYMBOLS") or "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,PAXGUSDT").split(",") if s.strip()]
TFS       = [("H1", "1h"), ("H4", "4h")]
EMAS      = [34, 89]
TOL_PCT   = float(os.environ.get("TOL_PCT") or 0.05)
REARM_PCT = float(os.environ.get("REARM_PCT") or 0.3)
LOOK_5M   = 3          # số nến 5m gần nhất dùng để kiểm tra chạm (bù cho việc lịch chạy bị trễ)
BASES     = ["https://data-api.binance.vision", "https://api.binance.com"]
STATE     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
TOKEN     = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")


def http_json(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "ema-touch-bot/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def klines(sym, interval, limit):
    last_err = None
    for base in BASES:
        try:
            q = urllib.parse.urlencode({"symbol": sym, "interval": interval, "limit": limit})
            return http_json(f"{base}/api/v3/klines?{q}")
        except Exception as e:  # thử máy chủ dữ liệu tiếp theo
            last_err = e
    raise last_err


def ema(values, period):
    """EMA giống TradingView: khởi tạo bằng SMA, sau đó làm mượt hàm mũ. Trả về giá trị cuối."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e


def fmt(p):
    p = float(p)
    d = 2 if p >= 1000 else 3 if p >= 10 else 4 if p >= 1 else 6
    return f"{p:,.{d}f}"


def send(text):
    if not TOKEN or not CHAT_ID:
        print("[Thiếu TELEGRAM_TOKEN hoặc TELEGRAM_CHAT_ID] Nội dung:\n" + text)
        return
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"}).encode()
    http_json(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data)


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f), False
    except FileNotFoundError:
        return {"armed": {}}, True


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1, sort_keys=True)


def check_symbol(sym, st, alerts):
    m5 = klines(sym, "5m", LOOK_5M + 1)
    recent = m5[-LOOK_5M:]
    hi = max(float(k[2]) for k in recent)
    lo = min(float(k[3]) for k in recent)
    start = float(recent[0][1])     # giá mở cửa đầu đoạn, để biết giá đi từ trên hay dưới tới
    price = float(m5[-1][4])
    for tf_name, iv in TFS:
        closes = [float(k[4]) for k in klines(sym, iv, 400)]  # nến cuối đang chạy = giá hiện tại
        for p in EMAS:
            e = ema(closes, p)
            if e is None:
                continue
            key = f"{sym}|{tf_name}|{p}"
            armed = st["armed"].get(key, True)
            touched = lo <= e * (1 + TOL_PCT / 100) and hi >= e * (1 - TOL_PCT / 100)
            if touched and armed:
                side = "từ trên xuống → hỗ trợ động" if start >= e else "từ dưới lên → kháng cự động"
                dist = (price - e) / e * 100
                alerts.append(f"• {sym} chạm EMA{p} {tf_name} ({fmt(e)})\n   Giá {fmt(price)} ({dist:+.2f}%), {side}")
                st["armed"][key] = False
            elif not touched and abs(price - e) / e * 100 > REARM_PCT and not armed:
                st["armed"][key] = True


def main():
    st, first_run = load_state()
    st.setdefault("armed", {})
    alerts, errors = [], []
    for sym in SYMBOLS:
        try:
            check_symbol(sym, st, alerts)
        except Exception as e:
            errors.append(f"{sym}: {e}")
            print(f"Lỗi {sym}: {e}", file=sys.stderr)
    if first_run:
        send("✅ Bot cảnh báo EMA 34/89 (H1, H4) đã chạy.\nĐang theo dõi: " + ", ".join(SYMBOLS)
             + (("\n⚠️ Lỗi: " + "; ".join(errors)) if errors else ""))
    if alerts:
        send("📈 Giá chạm EMA\n" + "\n".join(alerts))
    save_state(st)
    print(f"Xong. {len(alerts)} cảnh báo, {len(errors)} lỗi.")
    if errors and len(errors) == len(SYMBOLS):
        sys.exit(1)  # tất cả đều lỗi -> báo đỏ trên GitHub để bạn biết


if __name__ == "__main__":
    main()
