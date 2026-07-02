"""
Client cho Google Apps Script BetTracker Web App.
Đọc/ghi dữ liệu picks/results/settled/summary từ Google Sheets.
"""
import json
import os
import urllib3
import urllib.parse
from urllib.parse import urlencode

GAS_WEB_APP_URL = os.environ.get(
    "GAS_WEB_APP_URL",
    "https://script.google.com/macros/s/AKfycbyInGhr8KGOdF3BCTTqv-xb7IBanOQ2xLRSqbYGrB-nEkFVC-nQv0Xl6wcLQJj6rY-C/exec",
)
GAS_TIMEOUT = 60  # seconds (GAS thường chậm 5-15s vì cold start)
GAS_CONNECT_TIMEOUT = 10.0

_http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=GAS_CONNECT_TIMEOUT, read=GAS_TIMEOUT))


def _normalize_value(v):
    """Chuyển Date/None/object về JSON-friendly."""
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def _normalize_row(row):
    return {k: _normalize_value(v) for k, v in row.items()}


# Phòng trường hợp GAS còn trả về selection bị Sheets tự parse thành ISO datetime
# cho data cũ (trước khi fix ensureSelectionColumnIsText_). Convert "YYYY-MM-DDTHH:MM:SS.000Z"
# → "M-D" để hiển thị đúng tỷ số. Không match nếu là "2-1" thuần (đã sạch).
_ISO_DATETIME_RE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _fix_corrupted_selection(selection):
    """Convert ISO datetime string (Google Sheets auto-parsed '2-1') → 'H-A'."""
    s = str(selection or "").strip()
    if not _ISO_DATETIME_RE.match(s):
        return s
    try:
        from datetime import datetime
        # Parse "2026-02-28T17:00:00.000Z"
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return f"{dt.month}-{dt.day}"
    except (ValueError, TypeError):
        return s


def _fix_picks_cs_selection(rows):
    """Apply _fix_corrupted_selection cho CS picks."""
    for r in rows:
        if str(r.get("bet_type", "")).strip() == "correct_score":
            r["selection"] = _fix_corrupted_selection(r.get("selection", ""))


def fetch_tracker_data(action="full"):
    """GET dữ liệu từ GAS. Trả về dict hoặc None nếu lỗi."""
    try:
        url = f"{GAS_WEB_APP_URL}?action={action}"
        # GAS redirect (302) → urllib3 không auto-follow khi allow_redirects=False.
        # Bật allow_redirects=True để theo redirect tới script.googleusercontent.com.
        resp = _http.request(
            "GET", url,
            retries=urllib3.Retry(total=3, backoff_factor=1.0, status_forcelist=[502, 503, 504]),
            redirect=True,
        )
        if resp.status != 200:
            return None
        return json.loads(resp.data.decode("utf-8"))
    except Exception as e:
        print(f"[tracker] fetch_tracker_data error: {e}")
        return None


def post_action(action, payload=None, raw_body=None):
    """POST tới GAS. Apps Script trả 302 cho POST — đã verify body VẪN ĐƯỢC
    XỬ LÝ trước khi redirect (upload test: picks 147 → 148 sau POST uploadCsv).
    Nhưng: (a) re-POST tới echo endpoint = 405, (b) browser follow redirect với
    GET sẽ về echo endpoint trả `{}` (echo service, không phải response từ doPost).
    → POST 1 lần rồi return. Nếu 302 → success, echo service trả body echo (thường
    rỗng cho POST). Caller check sheet state sau vài giây để xác nhận.
    """
    try:
        url = f"{GAS_WEB_APP_URL}?action={action}"
        if raw_body is not None:
            body = raw_body
            headers = {"Content-Type": "text/plain; charset=utf-8"}
        else:
            body = json.dumps(payload or {})
            headers = {"Content-Type": "application/json; charset=utf-8"}

        # redirect=False: 302 có nghĩa GAS đã xử lý. KHÔNG follow redirect (echo endpoint trả 405).
        resp = _http.request(
            "POST", url, body=body.encode("utf-8"), headers=headers,
            retries=urllib3.Retry(total=3, backoff_factor=1.0, status_forcelist=[502, 503, 504]),
            redirect=False,
        )
        if resp.status == 302:
            # GAS đã xử lý body. Echo location trả 405, không follow.
            return {"success": True, "note": "GAS đã xử lý (302 redirect, không đọc được response body)."}
        if resp.status != 200:
            return {"error": f"HTTP {resp.status}", "body": resp.data[:200].decode("utf-8", errors="replace")}
        try:
            return json.loads(resp.data.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return {"raw": resp.data[:500].decode("utf-8", errors="replace")}
    except Exception as e:
        return {"error": str(e)}


def build_summary_html():
    """Tổng hợp dữ liệu tracker cho template rendering."""
    data = fetch_tracker_data("full")
    if not data:
        return {
            "ok": False,
            "error": "Không kết nối được GAS. Kiểm tra GAS_WEB_APP_URL.",
            "summary": [],
            "picks": [],
            "settled": [],
            "results": [],
        }

    def _is_header_shift(r):
        """Phát hiện row header bị lệch xuống data (GAS ghi nhầm): có key 'Column 1' hoặc
        value là tên cột (person/pick_id/...)."""
        if not isinstance(r, dict):
            return True
        if "Column 1" in r:  # header shift rõ ràng
            return True
        # backup: value rỗng + 1 vài field quen thuộc = header row
        if str(r.get("person", "")).lower() in ("column 1", "person", "người chơi", ""):
            if str(r.get("pick_id", "")).lower() in ("column 1", "pick_id", ""):
                return True
            if str(r.get("match", "")).lower() in ("column 3", "match", "trận", ""):
                return True
        return False

    summary_rows = [r for r in (_normalize_row(x) for x in (data.get("summary") or [])) if not _is_header_shift(r)]
    pick_rows    = [r for r in (_normalize_row(x) for x in (data.get("picks")    or [])) if not _is_header_shift(r)]
    settled_rows = [r for r in (_normalize_row(x) for x in (data.get("settled") or [])) if not _is_header_shift(r)]
    result_rows  = [r for r in (_normalize_row(x) for x in (data.get("results")  or [])) if not _is_header_shift(r)]

    # Phòng trường hợp data cũ trong Sheets còn bị auto-parse thành ISO datetime
    _fix_picks_cs_selection(pick_rows)
    _fix_picks_cs_selection(settled_rows)

    # Sort summary theo total_profit giảm dần
    summary_rows.sort(key=lambda r: float(r.get("total_profit") or 0), reverse=True)

    # Tổng toàn bộ
    total_stake = sum(float(r.get("total_stake") or 0) for r in summary_rows)
    total_profit = sum(float(r.get("total_profit") or 0) for r in summary_rows)
    total_wins = sum(int(r.get("win_count") or 0) for r in summary_rows)
    total_loses = sum(int(r.get("lose_count") or 0) for r in summary_rows)

    # Sort picks/settled theo timestamp desc
    pick_rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    settled_rows.sort(key=lambda r: str(r.get("pick_id") or ""), reverse=True)

    return {
        "ok": True,
        "summary": summary_rows,
        "picks": pick_rows,
        "settled": settled_rows,
        "results": result_rows,
        "total_stake": total_stake,
        "total_profit": total_profit,
        "total_wins": total_wins,
        "total_loses": total_loses,
        "active_picks": [p for p in pick_rows if str(p.get("status", "")).lower() == "active"],
    }


def _resolve_match_name(match_id):
    """Tra tên trận từ data/matches.json theo match_id. Trả về None nếu không tìm."""
    data_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "matches.json")
    if not os.path.exists(data_file):
        return None
    try:
        with open(data_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for m in raw:
            if str(m.get("id")) == str(match_id):
                home = m.get("home") or m.get("homeName") or ""
                away = m.get("away") or m.get("awayName") or ""
                if home or away:
                    return f"{home} - {away}".strip(" -")
        return None
    except Exception:
        return None


def submit_result(match_id, home_score, away_score, match_name=None):
    """POST updateResult lên GAS. Trả về dict response từ GAS."""
    if not match_name:
        match_name = _resolve_match_name(match_id) or ""
    return post_action("updateResult", {
        "match_id": str(match_id),
        "match_name": match_name,
        "home_score": int(home_score),
        "away_score": int(away_score),
    })


def upload_csv_text(csv_text):
    """POST raw CSV (tab-separated) lên GAS `uploadCsv`. Trả về dict response."""
    return post_action("uploadCsv", raw_body=csv_text)


def fetch_recent_picks(limit=20):
    """Lấy N picks gần nhất (dùng để kiểm tra pick vừa upload)."""
    data = fetch_tracker_data("picks")
    if not data or "picks" not in data:
        return []
    picks = data.get("picks") or []
    return picks[:limit]
