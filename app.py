from flask import Flask, render_template, jsonify, send_from_directory
import json
import os

app = Flask(__name__)
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "matches.json")

def clamp_odds(val):
    """Giới hạn tỷ lệ odds tối đa là 20"""
    if not val:
        return val
    try:
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

def load_matches_data():
    """
    Đọc dữ liệu trận đấu đã cào từ file JSON và giới hạn odds tối đa là 20.
    """
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            matches = json.load(f)

        for m in matches:
            if "odds" in m and m["odds"]:
                o = m["odds"]
                for market in ["handicap", "europe", "overUnder"]:
                    if market in o and o[market]:
                        for key in list(o[market].keys()):
                            if "Handicap" in key and market == "handicap":
                                # Đảo ngược dấu của Handicap tỷ lệ chấp bóng đá
                                o[market][key] = invert_handicap(o[market][key])
                            else:
                                o[market][key] = clamp_odds(o[market][key])

        return matches
    except Exception as e:
        print(f"Lỗi đọc file JSON: {e}")
        return []

@app.route("/")
def index():
    """
    Trang chính hiển thị giao diện danh sách trận đấu và tỷ lệ kèo.
    """
    import datetime
    matches = load_matches_data()
    # Nhóm trận đấu theo ngày (khung 15:00 hôm nay đến 14:59 hôm sau GMT+7)
    rounds = {}
    for m in matches:
        ts = m.get("matchTime", 0)
        # Giờ GMT+7 trừ đi 15 tiếng (ts + 7h - 15h = ts - 8h) để gom nhóm 1 loạt trận
        dt_logical = datetime.datetime.utcfromtimestamp(ts - 8 * 3600)
        date1 = dt_logical.strftime("%d/%m")
        date2 = (dt_logical + datetime.timedelta(days=1)).strftime("%d/%m")
        r_name = f"Loạt trận ngày {date1} - {date2}"

        if r_name not in rounds:
            rounds[r_name] = []
        rounds[r_name].append(m)

    # Sắp xếp các trận đấu trong mỗi vòng đấu theo thời gian
    for r in rounds:
        rounds[r].sort(key=lambda x: x.get("matchTime", 0))

    # Sắp xếp rounds theo ngày mới nhất lên đầu (dựa vào trận đầu tiên của loạt trận)
    sorted_rounds = {}
    for r_name in sorted(rounds.keys(), key=lambda k: rounds[k][0].get("matchTime", 0), reverse=True):
        sorted_rounds[r_name] = rounds[r_name]

    return render_template("index.html", rounds=sorted_rounds)

@app.route("/api/matches")
def api_matches():
    """
    API endpoint trả về dữ liệu trận đấu và odds dạng JSON.
    """
    return jsonify(load_matches_data())

@app.route("/flags/<path:filename>")
def serve_flag(filename):
    """Serve local team flag images"""
    flags_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flags")
    return send_from_directory(flags_dir, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
