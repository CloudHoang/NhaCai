from flask import Flask, render_template, jsonify, send_from_directory, request, redirect, url_for, flash, session
from tracker import build_summary_html, submit_result, fetch_tracker_data, upload_csv_text
import json
import os
import time

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(32).hex())
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "matches.json")
KNOCKOUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "matches32.json")

# Cache GAS summary data trong 30s để tránh gọi GAS 3 lần mỗi lần load /admin
_GAS_CACHE = {"data": None, "ts": 0.0}
GAS_CACHE_TTL = 30  # seconds


def _get_tracker_ctx(force=False):
    """Lấy dữ liệu tracker từ GAS, có cache 30s. Trả về dict context."""
    now = time.time()
    if not force and _GAS_CACHE["data"] and (now - _GAS_CACHE["ts"]) < GAS_CACHE_TTL:
        return _GAS_CACHE["data"]
    data = build_summary_html()
    _GAS_CACHE["data"] = data
    _GAS_CACHE["ts"] = now
    return data

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

def from_compact(m):
    """Mở rộng 1 match từ shape compact (lưu JSON) sang shape đầy đủ (dùng cho render)"""
    out = {
        "id": m.get("id"),
        "homeName": m.get("home", ""),
        "awayName": m.get("away", ""),
        "matchTime": m.get("time", 0),
        "roundName": m.get("round", ""),
        "odds": m.get("odds", {}),
        "aosOdds": m.get("aos", 0),
        "homeTeam": {"logo": m.get("hl", "")},
        "awayTeam": {"logo": m.get("al", "")},
        "correctScores": [],
    }
    for s in m.get("cs", []):
        parts = s.split(":")
        if len(parts) >= 3:
            try:
                hs = int(parts[0])
                ass = int(parts[1])
            except ValueError:
                continue
            out["correctScores"].append({
                "homeScore": hs,
                "awayScore": ass,
                "odds": ":".join(parts[2:]),
            })
    pred_str = m.get("pred")
    if pred_str:
        parts = pred_str.split("|")
        if len(parts) >= 3:
            out["predictions"] = {
                "homeWin": int(parts[0]),
                "draw": int(parts[1]),
                "awayWin": int(parts[2]),
            }
    return out

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

def load_matches_data():
    """
    Đọc dữ liệu trận đấu đã cào từ file JSON và giới hạn odds tối đa là 20.
    Hỗ trợ cả 2 format: compact (mới) và shape đầy đủ (cũ, để tương thích ngược).
    Gộp từ 2 file: matches.json (vòng bảng) + matches32.json (knockout).
    """
    raw_all = []
    for path in (DATA_FILE, KNOCKOUT_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                raw_all.extend(data)
        except Exception as e:
            print(f"Lỗi đọc file JSON ({path}): {e}")

    if not raw_all:
        return []

    try:
        raw = raw_all
        # Phát hiện format: compact nếu có key "home" thay vì "homeName"
        is_compact = bool(raw) and isinstance(raw[0], dict) and "home" in raw[0] and "homeName" not in raw[0]
        matches = [from_compact(m) for m in raw] if is_compact else raw

        for m in matches:
            home = m.get("homeName", "")
            away = m.get("awayName", "")

            # Normalize handicap signs based on Europe 1x2 odds
            if "odds" in m and m["odds"]:
                o = m["odds"]
                eu = o.get("europe", {})
                eu_home = eu.get("instantHome")
                eu_away = eu.get("instantAway")

                hdp = o.get("handicap", {})
                if hdp:
                    for key in ["instantHandicap", "initialHandicap"]:
                        if key in hdp:
                            hdp[key] = normalize_handicap(hdp[key], eu_home, eu_away)

            if "odds" in m and m["odds"]:
                o = m["odds"]
                for market in ["handicap", "europe", "overUnder"]:
                    if market in o and o[market]:
                        for key in list(o[market].keys()):
                            if "Handicap" not in key:
                                o[market][key] = clamp_odds(o[market][key])

            # Tạo các thuộc tính chú thích cho template giống build.py
            hc_line = m.get("odds", {}).get("handicap", {}).get("instantHandicap", "-")
            m["handicap_desc"] = get_handicap_description(home, away, hc_line)

            ou_line = m.get("odds", {}).get("overUnder", {}).get("instantHandicap", "-")
            m["ou_desc"] = f"Tài (Trên {ou_line} trái) / Xỉu (Dưới {ou_line} trái)" if ou_line != "-" else "Chưa cập nhật kèo tài xỉu"

            m["eu_desc"] = f"{home} thắng (1), Hòa (X), {away} thắng (2)"

        return matches
    except Exception as e:
        print(f"Lỗi xử lý dữ liệu: {e}")
        return []

def get_logical_date_label(ts):
    """
    Tính toán tên loạt trận dựa trên timestamp trận đấu (GMT+7)
    Khung giờ một loạt trận: 15:00 hôm nay -> 14:59 hôm sau (GMT+7)
    """
    import datetime
    # Trận đấu GMT+7
    dt_gmt7 = datetime.datetime.utcfromtimestamp(ts + 7 * 3600)
    # Tính ngày logic
    if dt_gmt7.hour >= 15:
        logical_date = dt_gmt7.date()
    else:
        logical_date = (dt_gmt7 - datetime.timedelta(days=1)).date()

    # Nhãn hiển thị dạng dd/mm - dd/mm
    date1_str = logical_date.strftime("%d/%m")
    date2_str = (logical_date + datetime.timedelta(days=1)).strftime("%d/%m")
    label = f"{date1_str} - {date2_str}"

    # Lấy ngày logic của "hiện tại" theo GMT+7
    now_gmt7 = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    today_date = now_gmt7.date()

    if logical_date == today_date:
        return "🔥 Hôm nay"

    return label

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


# ─── Admin: login + dashboard (Tracker + Upload CSV + Cập nhật tỷ số) ────────

def _is_admin():
    return session.get("is_admin") is True


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if _is_admin():
        return redirect(url_for("admin"))
    error = None
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if pwd == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin"))
        error = "Sai mật khẩu."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout", methods=["POST", "GET"])
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


def _filter_knockout(matches):
    """Lọc bỏ vòng bảng — chỉ giữ vòng knockout (Vòng 32 đội trở đi)."""
    return [m for m in matches if (m.get("roundName") or "") != "Vòng bảng"]


@app.route("/admin", methods=["GET"])
def admin():
    if not _is_admin():
        return redirect(url_for("admin_login"))

    matches = _filter_knockout(load_matches_data())
    matches.sort(key=lambda m: m.get("matchTime", 0))
    # Gọi GAS 1 lần duy nhất — _get_tracker_ctx() trả summary + picks + settled + results
    # Từ đó suy ra recent_picks + existing_match_ids
    tracker_ctx = _get_tracker_ctx()
    recent_picks = (tracker_ctx.get("picks") or [])[:10]
    existing_match_ids = {
        str(r.get("match_id", "")).strip()
        for r in (tracker_ctx.get("results") or [])
        if r.get("match_id") is not None
    }
    return render_template(
        "admin.html",
        matches=matches,
        recent_picks=recent_picks,
        existing_match_ids=existing_match_ids,
        tracker=tracker_ctx,
    )


@app.route("/admin/upload", methods=["POST"])
def admin_upload():
    """Upload CSV từ form admin → GAS uploadCsv."""
    if not _is_admin():
        return jsonify({"error": "unauthorized"}), 401
    csv_text = request.form.get("csv_text", "").strip()
    if not csv_text:
        flash("Vui lòng dán nội dung CSV trước khi upload.", "warning")
        return redirect(url_for("admin", tab="upload"))
    result = upload_csv_text(csv_text)
    if result.get("success"):
        flash(f"Upload OK · inserted={result.get('inserted')}.", "success")
    else:
        flash(f"Lỗi: {result.get('error', 'unknown')}", "danger")
    _GAS_CACHE["data"] = None  # invalidate cache sau khi mutate
    return redirect(url_for("admin", tab="upload"))


@app.route("/admin/result", methods=["POST"], endpoint="admin_result")
def admin_result():
    """POST nhập tỷ số → GAS updateResult, redirect về admin tab result."""
    if not _is_admin():
        return jsonify({"error": "unauthorized"}), 401

    match_id = request.form.get("match_id", "").strip()
    match_name = request.form.get("match_name", "").strip()
    try:
        home_score = int(request.form.get("home_score", "-1"))
        away_score = int(request.form.get("away_score", "-1"))
    except (TypeError, ValueError):
        home_score = away_score = -1

    if not match_id or home_score < 0 or away_score < 0:
        flash("Vui lòng chọn trận và nhập tỷ số hợp lệ (>= 0).", "danger")
        return redirect(url_for("admin", tab="result"))

    result = submit_result(match_id, home_score, away_score, match_name=match_name)
    if result.get("success"):
        flash(
            f"✓ Đã settle match_id={match_id} (settled={result.get('settled')}).",
            "success",
        )
        _GAS_CACHE["data"] = None  # invalidate cache
    else:
        flash(f"Lỗi từ GAS: {result.get('error', 'unknown')}", "danger")
    return redirect(url_for("admin", tab="result"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
