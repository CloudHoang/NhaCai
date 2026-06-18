import os
import glob
import re
import json
from datetime import datetime

MD_DIR = "markdown"
DATA_FILE = "data/matches.json"

def parse_md(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    match = {}

    # 1. Thông Tin Chung
    home_match = re.search(r'- Đội nhà: (.*)', content)
    away_match = re.search(r'- Đội khách: (.*)', content)
    time_match = re.search(r'- \*\*Thời gian diễn ra:\*\* (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \(GMT\+7\)', content)

    if not (home_match and away_match and time_match):
        return None

    home = home_match.group(1).strip()
    away = away_match.group(1).strip()
    time_str = time_match.group(1).strip()

    match['id'] = abs(hash(home + away)) % (10 ** 8)
    match['homeName'] = home
    match['awayName'] = away

    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    # Convert local GMT+7 back to epoch
    epoch = int(dt.timestamp()) - 7 * 3600
    match['matchTime'] = epoch

    match['roundName'] = f"Vòng bảng" # Set default

    # Flags will be reconstructed dynamically by app.py or we can set them
    match['homeTeam'] = {'logo': ''}
    match['awayTeam'] = {'logo': ''}

    odds = {
        'handicap': {},
        'europe': {},
        'overUnder': {}
    }

    # Handicap
    hc_line = re.search(r'- Mức chấp: ([\-\d\.]+) \(', content)
    hc_home = re.search(r'- Cược .* thắng \(Home\): ([\d\.]+)', content)
    hc_away = re.search(r'- Cược .* thắng \(Away\): ([\d\.]+)', content)

    if hc_line:
        odds['handicap']['instantHandicap'] = hc_line.group(1)
        odds['handicap']['instantHome'] = hc_home.group(1) if hc_home else ""
        odds['handicap']['instantAway'] = hc_away.group(1) if hc_away else ""

    # Europe
    eu_home_re = re.search(r'  - .* thắng \(Home\): ([\d\.]+)', content)
    eu_draw_re = re.search(r'  - Hòa \(Draw\): ([\d\.]+)', content)
    eu_away_re = re.search(r'  - .* thắng \(Away\): ([\d\.]+)', content)

    if eu_home_re and eu_draw_re and eu_away_re:
        odds['europe']['instantHome'] = eu_home_re.group(1)
        odds['europe']['instantDraw'] = eu_draw_re.group(1)
        odds['europe']['instantAway'] = eu_away_re.group(1)

    # OverUnder
    ou_line = re.search(r'- Tổng bàn thắng \(Line\): ([\d\.]+) \(', content)
    ou_over = re.search(r'- Cược Tài \(Over\): ([\d\.]+)', content)
    ou_under = re.search(r'- Cược Xỉu \(Under\): ([\d\.]+)', content)

    if ou_line:
        odds['overUnder']['instantHandicap'] = ou_line.group(1)
        odds['overUnder']['instantOver'] = ou_over.group(1) if ou_over else ""
        odds['overUnder']['instantUnder'] = ou_under.group(1) if ou_under else ""

    match['odds'] = odds

    # AOS
    aos = re.search(r'- \*\*Tỷ số ngoài bảng \(AOS\):\*\* ([\d\.]+)', content)
    if aos:
        match['aosOdds'] = float(aos.group(1))

    # Correct Scores
    correct_scores = []
    # Find table
    table_lines = re.findall(r'\| (\d+) - (\d+) \| ([\d\.]+) \|', content)
    for h, a, o in table_lines:
        correct_scores.append({
            'homeScore': int(h),
            'awayScore': int(a),
            'odds': o
        })
    match['correctScores'] = correct_scores

    return match

def main():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            try:
                matches = json.load(f)
            except Exception:
                matches = []
    else:
        matches = []

    existing_pairs = set(f"{m.get('homeName')}-{m.get('awayName')}" for m in matches)

    md_files = glob.glob(os.path.join(MD_DIR, "*.md"))
    restored_count = 0
    for file in md_files:
        m = parse_md(file)
        if m:
            pair = f"{m.get('homeName')}-{m.get('awayName')}"
            if pair in existing_pairs:
                # Remove old match to update
                matches = [match for match in matches if f"{match.get('homeName')}-{match.get('awayName')}" != pair]

            matches.append(m)
            existing_pairs.add(pair)
            restored_count += 1

    # Sort by time
    matches.sort(key=lambda x: x.get('matchTime', 0))

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(matches, f, ensure_ascii=False, indent=2)

    print(f"Đã khôi phục {restored_count} trận đấu từ markdown.")

if __name__ == "__main__":
    main()
