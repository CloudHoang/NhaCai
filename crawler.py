import urllib.request
import urllib.parse
import os
import json
import time
import calendar
from parser import clean_rsc_payload, extract_matches, extract_correct_score

# Tự động tải biến môi trường từ file .env nếu có
def load_dotenv():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")

load_dotenv()

# Telegram Config - Lấy từ biến môi trường
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Định nghĩa URL chính và các tham số header
TARGET_URL = "https://keobongvip.mom/giai-dau/fifa-world-cup?tab=ltd"
DETAIL_URL_TEMPLATE = "https://keobongvip.mom/tran-dau/{id}?tab=odds"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive"
}

DATA_DIR = "/home/cloud/00.Claude/Bet/data"
DATA_FILE = os.path.join(DATA_DIR, "matches.json")

def clamp_odds(val):
    """Giới hạn tỷ lệ odds tối đa là 20"""
    if not val:
        return val
    try:
        # Nếu là chuỗi số, chuyển sang float để so sánh
        f_val = float(val)
        if f_val > 20.0:
            return "20"
        return val
    except (ValueError, TypeError):
        return val

def invert_handicap(handicap_str):
    """Đảo ngược dấu của tỷ lệ chấp bóng đá"""
    if not handicap_str:
        return handicap_str
    try:
        val = float(handicap_str)
        inverted = -val
        if inverted == int(inverted):
            return str(int(inverted))
        return str(inverted)
    except (ValueError, TypeError):
        return handicap_str

def send_telegram_message(message):
    """Gửi tin nhắn qua Telegram Bot"""
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN" or not TELEGRAM_BOT_TOKEN:
        print("Telegram Bot Token chưa được cấu hình.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")
        return None

def format_match_message(m):
    """Format tin nhắn trận đấu cho Telegram"""
    ts = m.get("matchTime", 0)
    # Convert timestamp to GMT+7 string
    local_time = time.strftime('%H:%M %d/%m', time.gmtime(ts + 7 * 3600))

    msg = f"⚽ <b>{m.get('homeName')} vs {m.get('awayName')}</b>\n"
    msg += f"⏰ <i>{local_time} (GMT+7)</i>\n"
    msg += f"🏆 {m.get('roundName', 'World Cup')} | Bảng {m.get('group', '-')}\n\n"

    odds = m.get("odds", {})

    # Handicap
    hdp = odds.get("handicap", {})
    if hdp:
        msg += f"🔹 <b>Kèo Chấp:</b> {invert_handicap(hdp.get('instantHandicap'))}\n"
        msg += f"   └ Home: <code>{clamp_odds(hdp.get('instantHome'))}</code> | Away: <code>{clamp_odds(hdp.get('instantAway'))}</code>\n"

    # Over/Under
    ou = odds.get("overUnder", {})
    if ou:
        msg += f"🔹 <b>Tài Xỉu:</b> {ou.get('instantHandicap')}\n"
        msg += f"   └ Tài: <code>{clamp_odds(ou.get('instantOver'))}</code> | Xỉu: <code>{clamp_odds(ou.get('instantUnder'))}</code>\n"

    # Europe 1X2
    eu = odds.get("europe", {})
    if eu:
        msg += f"🔹 <b>Châu Âu:</b>\n"
        msg += f"   └ 1: <code>{clamp_odds(eu.get('instantHome'))}</code> | X: <code>{clamp_odds(eu.get('instantDraw'))}</code> | 2: <code>{clamp_odds(eu.get('instantAway'))}</code>\n"

    # Correct Score (Chia 3 cột)
    cs_list = m.get("correctScores", [])
    if cs_list:
        msg += f"\n🔢 <b>TỶ SỐ CHÍNH XÁC (FT):</b>\n"

        home_wins = [c for c in cs_list if int(c['homeScore']) > int(c['awayScore'])]
        draws = [c for c in cs_list if int(c['homeScore']) == int(c['awayScore'])]
        away_wins = [c for c in cs_list if int(c['homeScore']) < int(c['awayScore'])]

        # Lấy số hàng lớn nhất để loop
        max_rows = max(len(home_wins), len(draws), len(away_wins))

        msg += "<code>CHỦ      | HÒA      | KHÁCH</code>\n"
        for i in range(max_rows):
            h = f"{home_wins[i]['homeScore']}-{home_wins[i]['awayScore']} {clamp_odds(home_wins[i]['odds'])}" if i < len(home_wins) else ""
            d = f"{draws[i]['homeScore']}-{draws[i]['awayScore']} {clamp_odds(draws[i]['odds'])}" if i < len(draws) else ""
            a = f"{away_wins[i]['homeScore']}-{away_wins[i]['awayScore']} {clamp_odds(away_wins[i]['odds'])}" if i < len(away_wins) else ""

            # Format cột bằng cách padding space
            msg += f"<code>{h:<10}| {d:<9}| {a}</code>\n"

        msg += "\n💡 <i>Tỷ số ngoài bảng (AOS): Tỉ lệ thắng là 20</i>\n"

    msg += f"\n🔗 <a href='http://localhost:5000/#match-{m.get('id')}'>Xem chi tiết trên Web</a>"
    return msg

def fetch_html(url):
    """
    Gửi HTTP GET Request để lấy HTML payload.
    """
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.read().decode('utf-8')
    except Exception as e:
        print(f"Lỗi truy cập URL {url}: {e}")
        return None

def run_crawler():
    """
    Điều phối cào dữ liệu và ghi vào file matches.json.
    """
    print(f"Bắt đầu crawl dữ liệu lúc: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    html = fetch_html(TARGET_URL)
    if not html:
        print("Không thể lấy HTML từ trang đích.")
        return False

    payload = clean_rsc_payload(html)
    matches = extract_matches(payload)

    # Lọc trận đấu từ 17:00 hôm nay đến 15:00 hôm sau (GMT+7)
    # Tính toán timezone-independent để tránh lỗi lệch múi giờ trên máy chủ
    now = time.time()
    gmt7_struct = time.gmtime(now + 7 * 3600)
    year, month, day = gmt7_struct.tm_year, gmt7_struct.tm_mon, gmt7_struct.tm_mday

    # 17:00 hôm nay GMT+7 đổi sang epoch timestamp thực tế
    start_today = calendar.timegm((year, month, day, 17, 0, 0, 0, 0, 0)) - 7 * 3600

    # 15:00 hôm sau GMT+7 đổi sang epoch timestamp thực tế
    gmt7_tomorrow_struct = time.gmtime(now + 7 * 3600 + 24 * 3600)
    ty, tm, td = gmt7_tomorrow_struct.tm_year, gmt7_tomorrow_struct.tm_mon, gmt7_tomorrow_struct.tm_mday
    end_tomorrow = calendar.timegm((ty, tm, td, 15, 0, 0, 0, 0, 0)) - 7 * 3600

    filtered_matches = [m for m in matches if start_today <= m.get("matchTime", 0) <= end_tomorrow]

    print(f"Đã trích xuất {len(matches)} trận đấu. Sau khi lọc còn {len(filtered_matches)} trận.")

    # Cào thêm tỷ số chính xác cho từng trận đã lọc
    for m in filtered_matches:
        match_id = m.get("id")
        if not match_id:
            continue

        detail_url = DETAIL_URL_TEMPLATE.format(id=match_id)
        print(f"Đang lấy tỷ số chính xác cho trận: {m.get('homeName')} vs {m.get('awayName')} ({match_id})")

        detail_html = fetch_html(detail_url)
        if detail_html:
            detail_payload = clean_rsc_payload(detail_html)
            m["correctScores"] = extract_correct_score(detail_payload)
            print(f"  -> Tìm thấy {len(m['correctScores'])} tỷ lệ tỷ số.")

        # Giới hạn odds của các kèo chính về tối đa 20
        if "odds" in m and m["odds"]:
            o = m["odds"]
            for market in ["handicap", "europe", "overUnder"]:
                if market in o and o[market]:
                    for key in list(o[market].keys()):
                        # Chỉ giới hạn odds, không giới hạn handicap tỉ lệ chấp (như instantHandicap hay initialHandicap)
                        if "Handicap" not in key:
                            o[market][key] = clamp_odds(o[market][key])

        # Giới hạn odds của correct scores về tối đa 20
        if "correctScores" in m and m["correctScores"]:
            for score in m["correctScores"]:
                if "odds" in score:
                    score["odds"] = clamp_odds(score["odds"])

        # Nghỉ ngắn 1s tránh bị chặn
        time.sleep(1)

    if not filtered_matches:
        print("Không tìm thấy trận đấu nào trong khung giờ yêu cầu.")
        # Vẫn ghi mảng rỗng để xóa dữ liệu cũ

    # Tạo thư mục lưu trữ nếu chưa tồn tại
    os.makedirs(DATA_DIR, exist_ok=True)

    # Ghi dữ liệu JSON
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(filtered_matches, f, indent=2, ensure_ascii=False)

    print(f"Ghi file dữ liệu thành công vào: {DATA_FILE}")

    # Gửi thông báo Telegram cho từng trận đấu mới cập nhật
    if filtered_matches:
        print(f"Bắt đầu gửi {len(filtered_matches)} tin nhắn Telegram...")
        for m in filtered_matches:
            message = format_match_message(m)
            send_telegram_message(message)
            time.sleep(1) # Tránh Telegram spam limit
        print("Đã gửi xong thông báo Telegram.")

    return True

if __name__ == "__main__":
    run_crawler()
