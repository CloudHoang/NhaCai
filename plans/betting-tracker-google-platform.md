# Plan: Betting Tracker trên Google Platform

## Context

User có flow email: khi có kèo được chọn, email gửi qua và được chuyển thành file Excel trên OneDrive công ty (bị giới hạn chia sẻ). User muốn:

1. Tổng hợp thông tin các kèo cược từ file Markdown (odds từ crawler) + thông tin chọn kèo từ Excel.
2. Cập nhật tỷ số sau mỗi trận; hệ thống tự tính thắng/thua theo tỷ lệ odds trong MD.
3. Có trang tổng hợp thắng/thua của từng ngườichơi và tổng toàn bộ.

**Quyết định kiến trúc:**
- Không dùng local runtime để xử lý. Chỉ dùng GitHub lưu trữ.
- Dùng **Google Sheets** làm free data store cho picks, kết quả trận đấu, tổng hợp.
- Dùng **Google Apps Script (GAS)** làm backend: nhận upload Excel, parse, ghi Sheets, tính toán settlement.
- Web UI hiện tại trong project (Flask/GitHub Pages) đọc data từ Google Sheets qua **GAS Web App API** (JSONP/CORS) hoặc qua **Google Sheets published CSV/JSON**.
- Có thể tự động push `tracker_summary.json` từ GAS lên GitHub qua GitHub API nếu muốn static GitHub Pages render nhanh.

## Ví dụ data từ email

```
NHPhuc | Nam Phi - Canada | Nam Phi 0 - 0 Canada | 2 điểm | Active
```

Map:
- `person` = NHPhuc
- `match` = Nam Phi - Canada
- `selection` = dự đoán tỷ số chính xác: Nam Phi 0 - 0 Canada
- `stake` = 2 điểm
- `status` = Active (Cancelled = bỏ qua)

## Loại kèo hỗ trợ

1. **Tỷ số chính xác (correct_score)** — chính là ví dụ trên.
2. **Châu Á (handicap)** — ví dụ: "Nam Phi -0.5" hoặc "Canada +0.25".
3. **Tài Xỉu (over_under)** — ví dụ: "Tài 2.5" hoặc "Xỉu 2.75".

Không có 1X2.

## Kiến trúc tổng thể

```
┌────────────────────────────────────────────────────────────────────┐
│                         User Workflow                              │
│  Email → OneDrive Excel → Copy/paste/upload Excel → GAS Web App    │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Google Apps Script (GAS)                        │
│  1. Web App doPost() nhận upload Excel (.xlsx)                     │
│  2. Parse Excel → rows                                            │
│  3. Ghi vào Google Sheets (Picks sheet)                           │
│  4. doGet() trả về JSON dữ liệu picks + results + summary         │
│  5. Scheduled trigger: tính toán settlement mỗi khi có results    │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│                       Google Sheets                                │
│  Sheet "Picks"      — các pick từ email/Excel                      │
│  Sheet "Results"    — tỷ số thực tế các trận                       │
│  Sheet "Summary"    — tổng hợp thắng/thua theo ngườichơi           │
│  Sheet "Settled"    — chi tiết từng pick sau settlement            │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│                  Web UI (Flask local / GitHub Pages)               │
│  - Đọc data từ GAS doGet() JSON hoặc Sheets published CSV          │
│  - Hiển thị bảng tổng hợp và chi tiết                              │
│  - Cho phép nhập tỷ số trận đấu (POST lên GAS)                     │
└────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼ (optional)
┌────────────────────────────────────────────────────────────────────┐
│              GitHub Pages static (via GitHub API from GAS)         │
│  GAS tự động push tracker_summary.json lên repo mỗi khi thay đổi  │
│  → GitHub Pages render hoàn toàn static, không cần GAS online     │
└────────────────────────────────────────────────────────────────────┘
```

## Google Sheets Schema

### Sheet `Picks`

| A | B | C | D | E | F | G | H | I | J | K |
|---|---|---|---|---|---|---|---|---|---|---|
| pick_id | timestamp | person | match | bet_type | selection | line | odds | stake | status | source |
| p1 | 2026-06-28 | NHPhuc | Nam Phi - Canada | correct_score | 0-0 | - | 8.5 | 2 | Active | upload_20260628 |

- `bet_type`: `correct_score`, `handicap`, `over_under`
- `selection`:
  - correct_score: `H-A` e.g. `0-0`, `2-1`
  - handicap: `home` hoặc `away`
  - over_under: `over` hoặc `under`
- `line`: dùng cho handicap và over_under (e.g. `-0.5`, `2.75`)
- `odds`: tỷ lệ cược (lấy từ MD nếu match + selection khớp; nếu không khớp thì để trống hoặc nhập tay)
- `status`: `Active` hoặc `Cancelled`

### Sheet `Results`

| A | B | C | D | E |
|---|---|---|---|---|
| match_id | match | home_score | away_score | updated_at |
| 98484933 | Nam Phi - Canada | 1 | 2 | 2026-06-29 02:00 |

### Sheet `Settled`

| A | B | C | D | E | F | G | H | I |
|---|---|---|---|---|---|---|---|---|
| pick_id | person | match | bet_type | selection | stake | odds | result | profit |
| p1 | NHPhuc | Nam Phi - Canada | correct_score | 0-0 | 2 | 8.5 | lose | -2 |

### Sheet `Summary`

| A | B | C | D | E |
|---|---|---|---|---|
| person | total_stake | total_profit | win_count | lose_count |
| NHPhuc | 10 | 15 | 2 | 3 |

## Luật tính thắng thua

### 1. Correct Score
- `selection` = `H-A` (vd `0-0`).
- Thắng nếu `home_score == H` và `away_score == A`.
- **Profit = stake × odds** (user convention, không cộng gốc).
- Thua = `-stake`.

### 2. Handicap (Châu Á)
- `selection` = `home` hoặc `away`.
- Với `home`: margin = `home_score - away_score + line`.
  - margin > 0 → thắng, profit = stake × odds
  - margin < 0 → thua, profit = -stake
  - margin = 0 → push, profit = 0
  - quarter-ball (±0.25, ±0.75, ±1.25, ...): chia nửa win/lose.
- Với `away`: margin = `away_score - home_score + line`.

### 3. Over/Under (Tài Xỉu)
- `selection` = `over` hoặc `under`.
- `total = home_score + away_score`.
- `over`:
  - total > line → thắng
  - total < line → thua
  - total == line → push (nếu line là whole number)
- `under` ngược lại.
- Quarter-ball line (2.25, 2.75): chia nửa.
- **Profit = stake × odds** nếu thắng.

## Apps Script Functions

### `doPost(e)`
- Nhận upload Excel dưới dạng base64.
- Parse Excel thành rows.
- Ghi vào sheet `Picks` (append, hoặc upsert nếu muốn idempotent).
- Trả về JSON `{success, inserted_count}`.

### `doGet(e)`
- Query param `action`:
  - `action=picks` → trả về tất cả Active picks.
  - `action=results` → trả về tất cả results.
  - `action=summary` → trả về summary by person.
  - `action=settled` → trả về chi tiết settled picks.
  - `action=full` → trả về tất cả.

### `importFromExcel(base64Blob)`
- Dùng thư viện SheetJS hoặc xlsx-parser trong GAS để parse .xlsx.
- Hoặc yêu cầu user upload CSV thay vì Excel để đơn giản.

### `settlePicks()`
- Triggered mỗi khi `Results` thay đổi hoặc theo schedule.
- Lấy tất cả Active picks + results.
- Tính profit cho từng pick.
- Ghi sheet `Settled` và `Summary`.

### `updateResult(match_id, home_score, away_score)`
- Nhập tỷ số từ web UI.
- Sau đó chạy `settlePicks()`.

### `pushToGitHub()` (optional)
- Gọi GitHub API để commit `data/tracker_summary.json` lên repo.
- Cần GitHub personal access token lưu trong GAS Script Properties.

## Web UI trong project hiện tại

### Route `/tracker`
- Fetch JSON từ GAS Web App.
- Hiển thị:
  - Tổng stake / tổng profit toàn bộ
  - Bảng theo ngườichơi
  - Bảng chi tiết từng pick

### Route `/admin/result`
- Form chọn trận từ `matches.json`.
- Nhập home_score, away_score.
- POST lên GAS Web App `doPost` với action `updateResult`.
- (Nếu làm static GitHub Pages thì form POST phải qua GAS, không thể POST qua Pages static.)

## Các bước triển khai

1. **Tạo Google Sheets** với 4 sheet: Picks, Results, Settled, Summary.
2. **Tạo Google Apps Script** bound với Sheet.
3. **Viết GAS code**:
   - doPost/doGet
   - Parse Excel (hoặc CSV)
   - Settlement logic
   - Summary update
4. **Test GAS** bằng curl/Postman:
   - Upload test data
   - Nhập tỷ số
   - Kiểm tra summary
5. **Cập nhật project Python**:
   - Thêm route `/tracker` trong `app.py` đọc từ GAS.
   - Template `templates/tracker.html` hiển thị bảng.
   - Template `templates/result_form.html` nhập tỷ số.
6. **(Optional) GitHub sync** từ GAS.
7. **Cập nhật `CLAUDE.md`** hướng dẫn setup Google Sheets + GAS.

## Rủi ro & Lưu ý

- **GAS execution limit**: 6 phút/script. Với số lượng pick hàng trăm/tháng thì thoải mái.
- **Excel parsing trong GAS**: không hỗ trợ native .xlsx parse. Cần dùng thư viện như `SheetJS` hoặc convert Excel → CSV trước khi upload.
- **CORS**: GAS Web App phải deploy với access "Anyone" để web UI gọi được.
- **GitHub API token**: nếu dùng auto-push, token phải lưu an toàn trong GAS Properties.
- **Match linking**: cần fuzzy match tên trận từ Excel với `matches.json` để lấy odds.

## Quyết định đã confirmed

- **Upload format**: CSV upload/paste. GAS parse đơn giản.
- **Web UI nhập tỷ số**: Flask form local → POST lên GAS Web App.
- **GitHub sync**: Không. Web UI đọc trực tiếp từ GAS doGet() mỗi lần load.
