import json
import os
import re
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from app import load_matches_data

def remove_vietnamese_tones(text):
    if not text:
        return ""
    # Chuyển các ký tự tiếng Việt có dấu sang không dấu
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
    # Loại bỏ dấu phụ tổ hợp
    text = re.sub(r'[̣̀́̉̃]', '', text)
    text = re.sub(r'[ˆ̛̆]', '', text)
    return text

def get_match_slug(home, away):
    h = re.sub(r'[^a-z0-9]', '', remove_vietnamese_tones(home).lower())
    a = re.sub(r'[^a-z0-9]', '', remove_vietnamese_tones(away).lower())
    return f"{h}vs{a}"

def get_handicap_description(home, away, handicap_str):
    if not handicap_str or handicap_str == "-":
        return "Chưa cập nhật kèo chấp"
    try:
        val = float(handicap_str)
        if val < 0:
            abs_val = abs(val)
            abs_val_str = str(int(abs_val)) if abs_val == int(abs_val) else str(abs_val)
            return f"{home} chấp {away} {abs_val_str} trái"
        elif val > 0:
            val_str = str(int(val)) if val == int(val) else str(val)
            return f"{away} chấp {home} {val_str} trái"
        else:
            return "Kèo đồng banh (0)"
    except ValueError:
        return "Chưa cập nhật kèo chấp"

def generate_match_markdown(m):
    # Chuyển đổi epoch time sang GMT+7
    try:
        dt = datetime.fromtimestamp(m.get("matchTime", 0))
        time_str = dt.strftime("%Y-%m-%d %H:%M (GMT+7)")
    except Exception:
        time_str = "N/A"

    home = m.get("homeName", "")
    away = m.get("awayName", "")
    handicap_desc = m.get("handicap_desc", "")
    ou_desc = m.get("ou_desc", "")
    eu_desc = m.get("eu_desc", "")

    # Kèo chấp
    hc = m.get("odds", {}).get("handicap", {})
    hc_line = hc.get("instantHandicap", "-")
    hc_home = hc.get("instantHome", "-")
    hc_away = hc.get("instantAway", "-")

    # Kèo Châu Âu
    eu = m.get("odds", {}).get("europe", {})
    eu_home = eu.get("instantHome", "-")
    eu_draw = eu.get("instantDraw", "-")
    eu_away = eu.get("instantAway", "-")

    # Kèo Tài Xỉu
    ou = m.get("odds", {}).get("overUnder", {})
    ou_line = ou.get("instantHandicap", "-")
    ou_over = ou.get("instantOver", "-")
    ou_under = ou.get("instantUnder", "-")

    # Bảng tỷ số chính xác
    scores_table = "| Tỷ số (Nhà - Khách) | Tỷ lệ cược (Odds) |\n| :---: | :---: |\n"
    correct_scores = m.get("correctScores", [])
    if correct_scores:
        for item in correct_scores:
            h_score = item.get("homeScore", "")
            a_score = item.get("awayScore", "")
            odds_val = item.get("odds", "")
            scores_table += f"| {h_score} - {a_score} | {odds_val} |\n"
    else:
        scores_table += "| - | - |\n"

    md = f"""# THÔNG TIN TRẬN ĐẤU & TỶ LỆ CƯỢC: {home.upper()} VS {away.upper()}

## 1. Thông Tin Chung
- **Trận đấu:** {home} vs {away}
  - Đội nhà: {home}
  - Đội khách: {away}
- **Thời gian diễn ra:** {time_str}

## 2. Tỷ Lệ Kèo Hiện Tại
### Kèo Chấp (Handicap)
- Mức chấp: {hc_line} ({handicap_desc})
- Cược {home} thắng (Home): {hc_home}
- Cược {away} thắng (Away): {hc_away}

### Kèo Châu Âu (1x2)
- Mức cược: ({eu_desc})
  - {home} thắng (Home): {eu_home}
  - Hòa (Draw): {eu_draw}
  - {away} thắng (Away): {eu_away}

### Kèo Tài Xỉu (Over/Under)
- Tổng bàn thắng (Line): {ou_line} ({ou_desc})
- Cược Tài (Over): {ou_over}
- Cược Xỉu (Under): {ou_under}

## 3. Tỷ Lệ Tỷ Số Chính Xác (Correct Scores)
{scores_table}"""
    return md

def build_static():
    # Tải dữ liệu đã làm sạch qua logic của app.py
    matches = load_matches_data()

    # Tạo thư mục markdown nếu chưa có
    md_dir = "/home/cloud/00.Claude/Bet/markdown"
    os.makedirs(md_dir, exist_ok=True)

    rounds = {}
    for m in matches:
        home = m.get("homeName", "")
        away = m.get("awayName", "")

        # Tạo chú thích kèo chấp động
        hc_line = m.get("odds", {}).get("handicap", {}).get("instantHandicap", "-")
        m["handicap_desc"] = get_handicap_description(home, away, hc_line)

        # Tạo chú thích kèo tài xỉu động
        ou_line = m.get("odds", {}).get("overUnder", {}).get("instantHandicap", "-")
        m["ou_desc"] = f"Tài (Trên {ou_line} trái) / Xỉu (Dưới {ou_line} trái)" if ou_line != "-" else "Chưa cập nhật kèo tài xỉu"

        # Tạo chú thích kèo châu âu động
        m["eu_desc"] = f"{home} thắng (1), Hòa (X), {away} thắng (2)"

        # Tạo slug và gắn vào object trận đấu
        slug = get_match_slug(home, away)
        m["slug"] = slug

        # Sinh file Markdown cho trận đấu
        md_content = generate_match_markdown(m)
        md_path = os.path.join(md_dir, f"{slug}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        r_name = m.get("roundName", "Khác")
        if r_name not in rounds:
            rounds[r_name] = []
        rounds[r_name].append(m)

    for r in rounds:
        rounds[r].sort(key=lambda x: x.get("matchTime", 0))

    # Cấu hình Jinja2 để render template index.html tĩnh
    env = Environment(loader=FileSystemLoader('/home/cloud/00.Claude/Bet/templates'))
    template = env.get_template('index.html')

    output = template.render(rounds=rounds)

    # Ghi file index.html ra thư mục gốc để GitHub Pages đọc trực tiếp
    output_path = "/home/cloud/00.Claude/Bet/index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Build index.html thành công tại: {output_path}")
    print(f"Đã xuất {len(matches)} file Markdown vào thư mục {md_dir}")

if __name__ == "__main__":
    build_static()
