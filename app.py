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

def get_logical_date_label(ts):
    """
    Tính toán tên loạt trận dựa trên timestamp trận đấu (GMT+7)
    Khung giờ một loạt trận: 15:00 hôm nay -> 14:59 hôm sau (GMT+7)
    """
    import datetime
    # Quy đổi về logical date (lùi lại 28 tiếng từ GMT+7 để trận ngày 16/06 -> logical date 15/06)
    dt_logical = datetime.datetime.utcfromtimestamp(ts - 21 * 3600)

    # Ngày bắt đầu (hôm nay) và ngày kết thúc (ngày mai) theo GMT+7 của loạt trận
    date1_str = dt_logical.strftime("%d/%m")
    date2_str = (dt_logical + datetime.timedelta(days=1)).strftime("%d/%m")

    # Kiểm tra xem có phải Hôm nay, Hôm qua, hay Ngày mai không
    # Lấy thời gian hiện tại theo GMT+7
    now_gmt7 = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    today_logical = datetime.datetime.utcfromtimestamp((datetime.datetime.utcnow() + datetime.timedelta(hours=7)).timestamp() - 21 * 3600)

    label = f"({date1_str} - {date2_str})"

    # So sánh ngày
    diff_days = (dt_logical.date() - today_logical.date()).days
    if diff_days == 0:
        return "🔥 Hôm nay"

    return f"{date1_str} - {date2_str}"

@app.route("/")
def index():
    """
    Trang chính hiển thị giao diện danh sách trận đấu và tỷ lệ kèo.
    """
    matches = load_matches_data()
    # Nhóm trận đấu theo loạt trận
    rounds = {}
    for m in matches:
        ts = m.get("matchTime", 0)
        r_name = get_logical_date_label(ts)

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
