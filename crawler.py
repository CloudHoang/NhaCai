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

def download_flag(url):
    """Tải logo đội bóng về thư mục local flags/ để tránh lỗi CORS khi chụp ảnh"""
    if not url:
        return ""
    if url.startswith("flags/") or url.startswith("/flags/"):
        return url
    try:
        parsed_url = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if not filename:
            import hashlib
            filename = hashlib.md5(url.encode('utf-8')).hexdigest() + ".png"

        flags_dir = "/home/cloud/00.Claude/Bet/flags"
        os.makedirs(flags_dir, exist_ok=True)
        local_path = os.path.join(flags_dir, filename)

        if not os.path.exists(local_path):
            print(f"  -> Đang tải cờ: {url} -> {local_path}")
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=10) as response:
                with open(local_path, "wb") as f:
                    f.write(response.read())
        return f"flags/{filename}"
    except Exception as e:
        print(f"  -> Lỗi tải cờ {url}: {e}")
        return url

def calculate_aos(correct_scores):
    """Tính toán tỷ lệ AOS dựa trên thuật toán v6 modified"""
    from collections import Counter
    if not correct_scores:
        return 20.0
    odds_matrix = {}
    for s in correct_scores:
        score_key = f"{s.get('homeScore')}-{s.get('awayScore')}"
        try:
            odds_matrix[score_key] = float(s.get("odds", 0))
        except (ValueError, TypeError):
            odds_matrix[score_key] = 0.0

    valid_odds = [o for o in odds_matrix.values() if o > 0]
    if not valid_odds:
        return 20.0

    # Step 1: Hard Ceiling Compression Check
    odds_counts = Counter(valid_odds)
    mode_value, mode_frequency = odds_counts.most_common(1)[0]
    if mode_frequency >= 5 and mode_value <= 50.0:
        odds_aos = mode_value * 0.9
    else:
        # Step 2: Open Market Multi-Tier Boundary Anchoring
        home_win_low = min(odds_matrix.get("1-0", 999), odds_matrix.get("2-0", 999))
        away_win_low = min(odds_matrix.get("0-1", 999), odds_matrix.get("0-2", 999))
        if home_win_low < away_win_low:
            # Home Team is Favorite
            odds_3_0 = odds_matrix.get("3-0", 10.0)
            if odds_3_0 >= 9.0:
                odds_base = odds_3_0
            else:
                odds_base = odds_matrix.get("4-0", 20.0)
        else:
            # Away Team is Favorite
            odds_base = odds_matrix.get("1-3", 12.0)

        # Step 3: Dynamic Shaving Filter
        if odds_base <= 10.0:
            odds_aos = odds_base
        elif odds_base <= 15.0:
            odds_aos = odds_base * 0.95
        else:
            odds_aos = odds_base * 0.90

    # Thuật toán calculate_aos nhận odds của correctScores đã được giảm 20% và áp trần 20.
    # Do đó ta tính toán dựa trên odds_matrix chứa các odds đã giảm này.

    # Bước điều chỉnh cho AOS theo yêu cầu mới:
    # Kết quả AOS sau khi tính toán xong:
    # - Nếu odds_aos >= 10.0 -> giảm thêm 20% (nhân với 0.8)
    # - Nếu odds_aos < 10.0 -> giảm thêm 10% (nhân với 0.9)
    if odds_aos >= 10.0:
        odds_aos = odds_aos * 0.80
    else:
        odds_aos = odds_aos * 0.90

    # Áp trần tối đa là 20 cho AOS
    if odds_aos > 20.0:
        odds_aos = 20.0

    return round(odds_aos, 1)

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
            h = f"{home_wins[i]['homeScore']}-{home_wins[i]['awayScore']} {home_wins[i]['odds']}" if i < len(home_wins) else ""
            d = f"{draws[i]['homeScore']}-{draws[i]['awayScore']} {draws[i]['odds']}" if i < len(draws) else ""
            a = f"{away_wins[i]['homeScore']}-{away_wins[i]['awayScore']} {away_wins[i]['odds']}" if i < len(away_wins) else ""

            # Format cột bằng cách padding space
            msg += f"<code>{h:<10}| {d:<9}| {a}</code>\n"

        msg += f"\n💡 <i>Tỷ số ngoài bảng (AOS): Tỉ lệ thắng là {m.get('aosOdds', 20)}</i>\n"

    # Tạo slug match url
    import re
    def remove_vietnamese_tones(text):
        if not text: return ""
        text = re.sub(r'[àáạảãâầấậẩẫăằắặẳẵ]', 'a', text)
        text = re.sub(r'[èéẹẻẽêềếệểễ]', 'e', text)
        text = re.sub(r'[ìíịỉĩ]', 'i', text)
        text = re.sub(r'[òóọỏõôồốộổỗơờớợởỡ]', 'o', text)
        text = re.sub(r'[ùúụủũưừứựửữ]', 'u', text)
        text = re.sub(r'[ỳýỵỷỹ]', 'y', text)
        text = re.sub(r'[đ]', 'd', text)
        text = re.sub(r'[ÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴ]', 'A', text)
        text = re.sub(r'[ÈÉẸẺẼÊỀẾỆỂỄ]', 'E', text)
        text = re.sub(r'[ÌÍỊỈĨ]', 'I', text)
        text = re.sub(r'[ÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠ]', 'O', text)
        text = re.sub(r'[ÙÚỤỦŨƯỪỨỰỬỮ]', 'U', text)
        text = re.sub(r'[ỲÝỴỶỸ]', 'Y', text)
        text = re.sub(r'[Đ]', 'D', text)
        text = re.sub(r'[̣̀́̉̃]', '', text)
        text = re.sub(r'[ˆ̛̆]', '', text)
        return text

    h = re.sub(r'[^a-z0-9]', '', remove_vietnamese_tones(m.get('homeName')).lower())
    a = re.sub(r'[^a-z0-9]', '', remove_vietnamese_tones(m.get('awayName')).lower())
    slug = f"{h}vs{a}"

    msg += f"\n🔗 <a href='https://cloudhoang.github.io/NhaCai/#{slug}'>Xem chi tiết trên Web</a>"
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

        # Tải cờ đội bóng về local để tránh CORS khi in/chụp ảnh
        if "homeTeam" in m and m["homeTeam"] and "logo" in m["homeTeam"]:
            m["homeTeam"]["logo"] = download_flag(m["homeTeam"]["logo"])
        if "awayTeam" in m and m["awayTeam"] and "logo" in m["awayTeam"]:
            m["awayTeam"]["logo"] = download_flag(m["awayTeam"]["logo"])

        detail_url = DETAIL_URL_TEMPLATE.format(id=match_id)
        print(f"Đang lấy tỷ số chính xác cho trận: {m.get('homeName')} vs {m.get('awayName')} ({match_id})")

        detail_html = fetch_html(detail_url)
        if detail_html:
            detail_payload = clean_rsc_payload(detail_html)
            m["correctScores"] = extract_correct_score(detail_payload)
            print(f"  -> Tìm thấy {len(m['correctScores'])} tỷ lệ tỷ số.")

        # Giới hạn odds của correct scores: giảm 20% trước, sau đó áp trần tối đa là 20
        if "correctScores" in m and m["correctScores"]:
            for score in m["correctScores"]:
                if "odds" in score:
                    try:
                        raw_odds = float(score["odds"])
                        reduced_odds = raw_odds * 0.80
                        if reduced_odds > 20.0:
                            score["odds"] = "20"
                        else:
                            # Làm tròn 2 chữ số thập phân cho gọn
                            score["odds"] = str(round(reduced_odds, 2))
                    except (ValueError, TypeError):
                        score["odds"] = clamp_odds(score["odds"])

        # Tính toán tỷ lệ AOS sau khi đã xử lý xong correctScores
        # Thuật toán calculate_aos lấy odds từ correctScores (đã được giảm 20% và áp trần 20)
        m["aosOdds"] = calculate_aos(m.get("correctScores", []))

        # Giới hạn odds của các kèo chính về tối đa 20
        if "odds" in m and m["odds"]:
            o = m["odds"]
            for market in ["handicap", "europe", "overUnder"]:
                if market in o and o[market]:
                    for key in list(o[market].keys()):
                        # Chỉ giới hạn odds, không giới hạn handicap tỉ lệ chấp (như instantHandicap hay initialHandicap)
                        if "Handicap" not in key:
                            o[market][key] = clamp_odds(o[market][key])

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
