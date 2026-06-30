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

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "matches.json")

TEAM_FLAG_MAP = {
    "algeria": "algeria.png",
    "argentina": "argentina.png",
    "úc": "australia.png",
    "áo": "austria.png",
    "bỉ": "belgium.png",
    "bosnia": "bosnia.png",
    "brazil": "brazil.png",
    "canada": "canada.png",
    "cape verde": "cape_verde.png",
    "colombia": "colombia.png",
    "chdc công gô": "congo_dr.png",
    "croatia": "croatia.png",
    "curacao": "curacao.png",
    "curaçao": "curacao.png",
    "cộng hòa séc": "czechia.png",
    "ecuador": "ecuador.png",
    "ai cập": "egypt.png",
    "anh": "england.png",
    "pháp": "france.png",
    "đức": "germany.png",
    "ghana": "ghana.png",
    "haiti": "haiti.png",
    "iran": "iran.png",
    "iraq": "iraq.png",
    "bờ biển ngà": "ivory_coast.png",
    "nhật bản": "japan.png",
    "jordan": "jordan.png",
    "mexico": "mexico.png",
    "maroc": "morocco.png",
    "hà lan": "netherlands.png",
    "new zealand": "new_zealand.png",
    "na uy": "norway.png",
    "panama": "panama.png",
    "paraguay": "paraguay.png",
    "bồ đào nha": "portugal.png",
    "qatar": "qatar.png",
    "ả rập xê út": "saudi_arabia.png",
    "scotland": "scotland.png",
    "senegal": "senegal.png",
    "nam phi": "south_africa.png",
    "hàn quốc": "south_korea.png",
    "tây ban nha": "spain.png",
    "thụy điển": "sweden.png",
    "thụy sĩ": "switzerland.png",
    "tunisia": "tunisia.png",
    "thổ nhĩ kỳ": "turkiye.png",
    "uruguay": "uruguay.png",
    "mỹ": "usa.png",
    "uzbekistan": "uzbekistan.png",
}

def get_local_flag(team_name):
    """Lấy đường dẫn cờ nội bộ từ tên đội bóng"""
    if not team_name:
        return ""
    name_lower = team_name.lower().strip()
    if name_lower in TEAM_FLAG_MAP:
        return f"flags/{TEAM_FLAG_MAP[name_lower]}"
    return ""

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

def to_compact(m):
    """Chuyển 1 match từ shape đầy đủ sang shape compact để lưu JSON
    Hỗ trợ cả raw (homeName/correctScores) và compact (home/cs) format vì merge hay re-read."""
    home = m.get("homeName") or m.get("home") or ""
    away = m.get("awayName") or m.get("away") or ""

    raw_cs = m.get("correctScores", m.get("cs", []))
    if raw_cs and isinstance(raw_cs[0], str):
        cs = raw_cs  # đã compact
    else:
        cs = [
            f"{cs.get('homeScore', 0)}:{cs.get('awayScore', 0)}:{cs.get('odds', '')}"
            for cs in raw_cs
        ]

    nm = {
        "id": m.get("id"),
        "home": home,
        "away": away,
        "time": m.get("matchTime") or m.get("time") or 0,
        "round": m.get("roundName") or m.get("round") or "",
        "odds": m.get("odds", {}),
        "aos": m.get("aosOdds") if m.get("aosOdds") is not None else (m.get("aos") or 0),
        "cs": cs,
    }
    ht = m.get("homeTeam") or {}
    at = m.get("awayTeam") or {}
    logo_home = ht.get("logo") or m.get("hl") or ""
    logo_away = at.get("logo") or m.get("al") or ""
    if logo_home:
        nm["hl"] = logo_home
    if logo_away:
        nm["al"] = logo_away

    pred = m.get("predictions") or m.get("pred") or None
    if isinstance(pred, dict):
        nm["pred"] = f"{pred.get('homeWin', 0)}|{pred.get('draw', 0)}|{pred.get('awayWin', 0)}"
    elif isinstance(pred, str):
        nm["pred"] = pred

    return nm

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

        flags_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flags")
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

def normalize_handicap(handicap_str, eu_home_str, eu_away_str):
    if not handicap_str or handicap_str == "-":
        return handicap_str
    try:
        val = abs(float(handicap_str))
        if eu_home_str and eu_away_str:
            eu_home = float(eu_home_str)
            eu_away = float(eu_away_str)
            if eu_home < eu_away:
                # Home favorite -> negative
                normalized = -val
            elif eu_home > eu_away:
                # Away favorite -> positive
                normalized = val
            else:
                raw_val = float(handicap_str)
                normalized = -raw_val
        else:
            raw_val = float(handicap_str)
            normalized = -raw_val

        if normalized == int(normalized):
            return str(int(normalized))
        return str(normalized)
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
    eu = odds.get("europe", {})

    # Handicap
    hdp = odds.get("handicap", {})
    if hdp:
        norm_hdp = normalize_handicap(hdp.get('instantHandicap'), eu.get('instantHome'), eu.get('instantAway'))
        msg += f"🔹 <b>Kèo Chấp:</b> {norm_hdp}\n"
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

def generate_oddsrate_json(matches):
    """
    Tạo file data/oddsrate.json từ 4 trận đấu mới nhất dựa vào codename.md.
    """
    try:
        import unicodedata
        def clean_team_name(name):
            if not name:
                return ""
            return unicodedata.normalize('NFC', name.strip().replace("\xa0", " "))

        # Load codename mapping
        codename_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codename.md")
        name_to_code = {}
        if os.path.exists(codename_path):
            with open(codename_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 4:
                        en = clean_team_name(parts[1])
                        vi = clean_team_name(parts[2])
                        code = parts[3].strip()
                        if en and vi and code and code != "Code" and not code.startswith(":-"):
                            name_to_code[en.lower()] = code
                            name_to_code[vi.lower()] = code

        # Lấy 4 trận đấu mới nhất (ở cuối danh sách đã sắp xếp theo thời gian tăng dần)
        latest_4 = matches[-4:] if len(matches) >= 4 else matches

        oddsrate_data = []
        for m in latest_4:
            home = m.get("homeName", "")
            away = m.get("awayName", "")

            home_clean = clean_team_name(home)
            away_clean = clean_team_name(away)

            home_code = name_to_code.get(home_clean.lower(), home)
            away_code = name_to_code.get(away_clean.lower(), away)
            match_code = f"{home_code}{away_code}".upper()

            odds = m.get("odds", {})
            handicap = odds.get("handicap", {})
            europe = odds.get("europe", {})
            over_under = odds.get("overUnder", {})

            norm_hdp = normalize_handicap(handicap.get("instantHandicap", ""), europe.get("instantHome"), europe.get("instantAway"))

            oddsrate_data.append({
                "homeName": home,
                "awayName": away,
                "matchCode": match_code,
                "odds": {
                    "handicap": {
                        "instantHandicap": norm_hdp,
                        "instantHome": handicap.get("instantHome", ""),
                        "instantAway": handicap.get("instantAway", "")
                    },
                    "overUnder": {
                        "instantHandicap": over_under.get("instantHandicap", ""),
                        "instantOver": over_under.get("instantOver", ""),
                        "instantUnder": over_under.get("instantUnder", "")
                    }
                }
            })

        oddsrate_file = os.path.join(DATA_DIR, "oddsrate.json")
        with open(oddsrate_file, "w", encoding="utf-8") as f:
            json.dump(oddsrate_data, f, indent=2, ensure_ascii=False)
        print(f"Ghi file oddsrate thành công vào: {oddsrate_file}")
    except Exception as e:
        print(f"Lỗi ghi file oddsrate.json: {e}")

def load_codename_mapping():
    """
    Tải bản đồ tên đội bóng sang Code quốc gia từ codename.md.
    """
    import unicodedata
    def clean_name(name):
        if not name:
            return ""
        nfkd_form = unicodedata.normalize('NFKD', name.strip().replace("\xa0", " "))
        cleaned = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
        return cleaned.lower()

    codename_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codename.md")
    name_to_code = {}
    if os.path.exists(codename_path):
        try:
            with open(codename_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 4:
                        en = clean_name(parts[1])
                        vi = clean_name(parts[2])
                        code = parts[3].strip()
                        if en and vi and code and code != "Code" and not code.startswith(":-"):
                            name_to_code[en] = code
                            name_to_code[vi] = code
        except Exception as e:
            print(f"Lỗi tải codename mapping: {e}")
    return name_to_code

def fetch_cup26_predictions():
    """
    Cào dự đoán tỷ lệ thắng từ cup26matches.com/en
    """
    import re
    url = "https://cup26matches.com/en/"
    print(f"Đang cào tỷ lệ thắng từ: {url}")
    html = fetch_html(url)
    if not html:
        print("Không thể lấy dữ liệu từ cup26matches.com.")
        return {}

    name_to_code = load_codename_mapping()

    import unicodedata
    def clean_name(name):
        if not name:
            return ""
        nfkd_form = unicodedata.normalize('NFKD', name.strip().replace("\xa0", " "))
        cleaned = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
        return cleaned.lower()

    predictions = {}

    match_blocks = []
    start_idx = 0
    while True:
        start_idx = html.find("<a href=\"/en/match/", start_idx)
        if start_idx == -1:
            break
        end_idx = html.find("</a>", start_idx)
        if end_idx == -1:
            break
        block = html[start_idx:end_idx+4]
        match_blocks.append(block)
        start_idx = end_idx + 4

    print(f"Tìm thấy {len(match_blocks)} trận đấu trên cup26matches.com")

    for block in match_blocks:
        teams = re.findall(r"class=\"truncate font-display text-sm md:text-lg\">([^<]+)</span>", block)
        if len(teams) < 2:
            continue

        home_en = teams[0].strip()
        away_en = teams[1].strip()

        widths = re.findall(r"style=\"width:([0-9.]+)%\"", block)
        if len(widths) < 3:
            continue

        try:
            home_win = int(round(float(widths[0])))
            draw = int(round(float(widths[1])))
            away_win = int(round(float(widths[2])))
        except (ValueError, TypeError):
            continue

        home_code = name_to_code.get(clean_name(home_en), "")
        away_code = name_to_code.get(clean_name(away_en), "")

        if home_code and away_code:
            key = (home_code, away_code)
            predictions[key] = {
                "homeWin": home_win,
                "draw": draw,
                "awayWin": away_win
            }
            print(f"  -> Trích xuất: {home_en} ({home_code}) vs {away_en} ({away_code}) | {home_win}% - {draw}% - {away_win}%")
        else:
            print(f"  -> Không khớp Code cho: {home_en} vs {away_en}")

    return predictions

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

    # Lấy mapping mã quốc gia và cào dự đoán tỷ lệ thắng từ cup26matches.com/en
    name_to_code = load_codename_mapping()
    predictions_map = fetch_cup26_predictions()

    # Lọc trận đấu từ 15:00 hôm nay đến 14:00 hôm sau (GMT+7)
    # Tính toán timezone-independent để tránh lỗi lệch múi giờ trên máy chủ
    now = time.time()
    gmt7_struct = time.gmtime(now + 7 * 3600)
    year, month, day = gmt7_struct.tm_year, gmt7_struct.tm_mon, gmt7_struct.tm_mday

    # 15:00 hôm nay GMT+7 đổi sang epoch timestamp thực tế
    start_today = calendar.timegm((year, month, day, 15, 0, 0, 0, 0, 0)) - 7 * 3600

    # 14:00 hôm sau GMT+7 đổi sang epoch timestamp thực tế
    gmt7_tomorrow_struct = time.gmtime(now + 7 * 3600 + 24 * 3600)
    ty, tm, td = gmt7_tomorrow_struct.tm_year, gmt7_tomorrow_struct.tm_mon, gmt7_tomorrow_struct.tm_mday
    end_tomorrow = calendar.timegm((ty, tm, td, 14, 0, 0, 0, 0, 0)) - 7 * 3600

    filtered_matches = [m for m in matches if start_today <= m.get("matchTime", 0) <= end_tomorrow]

    print(f"Đã trích xuất {len(matches)} trận đấu. Sau khi lọc còn {len(filtered_matches)} trận.")

    # Cào thêm tỷ số chính xác cho từng trận đã lọc
    for m in filtered_matches:
        match_id = m.get("id")
        if not match_id:
            continue

        # Lấy cờ đội bóng từ thư mục local theo tên đội
        if "homeTeam" in m and m["homeTeam"]:
            m["homeTeam"]["logo"] = get_local_flag(m.get("homeName", ""))
        if "awayTeam" in m and m["awayTeam"]:
            m["awayTeam"]["logo"] = get_local_flag(m.get("awayName", ""))

        # Thêm tỷ lệ dự đoán thắng từ cup26matches.com
        import unicodedata
        def clean_name(name):
            if not name:
                return ""
            nfkd_form = unicodedata.normalize('NFKD', name.strip().replace("\xa0", " "))
            cleaned = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
            return cleaned.lower()

        home_code = name_to_code.get(clean_name(m.get("homeName")), "")
        away_code = name_to_code.get(clean_name(m.get("awayName")), "")

        m["predictions"] = None
        if home_code and away_code:
            key = (home_code, away_code)
            if key in predictions_map:
                m["predictions"] = predictions_map[key]
                print(f"  -> Khớp dự đoán: {m.get('homeName')} vs {m.get('awayName')} -> {m['predictions']}")
            else:
                inv_key = (away_code, home_code)
                if inv_key in predictions_map:
                    pred = predictions_map[inv_key]
                    m["predictions"] = {
                        "homeWin": pred["awayWin"],
                        "draw": pred["draw"],
                        "awayWin": pred["homeWin"]
                    }
                    print(f"  -> Khớp dự đoán (ngược): {m.get('homeName')} vs {m.get('awayName')} -> {m['predictions']}")

        detail_url = DETAIL_URL_TEMPLATE.format(id=match_id)
        print(f"Đang lấy tỷ số chính xác cho trận: {m.get('homeName')} vs {m.get('awayName')} ({match_id})")

        detail_html = fetch_html(detail_url)
        if detail_html:
            detail_payload = clean_rsc_payload(detail_html)
            m["correctScores"] = extract_correct_score(detail_payload)
            print(f"  -> Tìm thấy {len(m['correctScores'])} tỷ lệ tỷ số.")

        # Tính toán tỷ lệ AOS trước khi áp trần 20 cho correctScores
        # Tạo bản sao correctScores chỉ giảm 20% (không áp trần) để tính toán AOS
        temp_scores = []
        if "correctScores" in m and m["correctScores"]:
            for score in m["correctScores"]:
                if "odds" in score:
                    try:
                        raw_odds = float(score["odds"])
                        reduced_odds = raw_odds * 0.80
                        temp_scores.append({
                            "homeScore": score.get("homeScore"),
                            "awayScore": score.get("awayScore"),
                            "odds": str(reduced_odds)
                        })
                    except (ValueError, TypeError):
                        temp_scores.append(score)
        m["aosOdds"] = calculate_aos(temp_scores)

        # Giới hạn odds của correct scores: giảm 20% trước, sau đó áp trần tối đa là 20 để hiển thị
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

    # Tạo thư mục lưu trữ nếu chưa tồn tại
    os.makedirs(DATA_DIR, exist_ok=True)

    # Đọc dữ liệu cũ nếu có
    existing_matches = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                existing_matches = json.load(f)
        except Exception as e:
            print(f"Lỗi đọc file data cũ: {e}")

    # Gộp dữ liệu mới vào dữ liệu cũ (ghi đè nếu trùng id trận đấu)
    matches_dict = {str(m.get("id")): m for m in existing_matches if m.get("id")}
    for m in filtered_matches:
        if m.get("id"):
            matches_dict[str(m.get("id"))] = m

    # Chuyển lại thành list và sắp xếp theo thời gian
    final_matches = list(matches_dict.values())
    final_matches.sort(key=lambda x: x.get("matchTime", 0))

    # Chuyển sang format compact trước khi ghi
    compact_matches = [to_compact(m) for m in final_matches]

    # Ghi dữ liệu JSON dạng compact (không indent, separators gọn)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(compact_matches, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Ghi file dữ liệu thành công vào: {DATA_FILE}")

    # Ghi file oddsrate.json
    generate_oddsrate_json(final_matches)

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
