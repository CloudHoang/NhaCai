from flask import Flask, render_template, jsonify
import json
import os

app = Flask(__name__)
DATA_FILE = "/home/cloud/00.Claude/Bet/data/matches.json"

def load_matches_data():
    """
    Đọc dữ liệu trận đấu đã cào từ file JSON.
    """
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
