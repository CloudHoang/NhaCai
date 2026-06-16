from flask import Flask, render_template, jsonify, send_from_directory
import json
import os

app = Flask(__name__)
DATA_FILE = "/home/cloud/00.Claude/Bet/data/matches.json"

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
    matches = load_matches_data()
    # Nhóm trận đấu theo vòng đấu (roundName) hoặc bảng đấu (group)
    rounds = {}
    for m in matches:
        r_name = m.get("roundName", "Khác")
        if r_name not in rounds:
            rounds[r_name] = []
        rounds[r_name].append(m)

    # Sắp xếp các trận đấu trong mỗi vòng đấu theo thời gian
    for r in rounds:
        rounds[r].sort(key=lambda x: x.get("matchTime", 0))

    return render_template("index.html", rounds=rounds)

@app.route("/api/matches")
def api_matches():
    """
    API endpoint trả về dữ liệu trận đấu và odds dạng JSON.
    """
    return jsonify(load_matches_data())

@app.route("/flags/<path:filename>")
def serve_flag(filename):
    """Serve local team flag images"""
    return send_from_directory("/home/cloud/00.Claude/Bet/flags", filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
