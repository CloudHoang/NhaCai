# Google Apps Script: BetTracker

File này chứa toàn bộ backend cho **Betting Tracker**, chạy trên Google Apps Script (GAS) bound với Google Sheets.

## Tổng quan
- **Data store**: Google Sheets (4 tab: `Picks`, `Results`, `Settled`, `Summary`).
- **API**: GAS Web App endpoint `https://script.google.com/macros/s/<DEPLOY_ID>/exec`.
- **CORS**: `Access-Control-Allow-Origin: *` (mọi origin đều gọi được).
- **Match odds lookup**: cache `data/matches.json` từ GitHub vào Script Property `MATCHES_CACHE`.

## Setup nhanh

1. **Tạo Google Sheets** [sheets.new](https://sheets.new) với 4 tab + header:
   - `Picks`: `pick_id	timestamp	person	match	bet_type	selection	line	odds	stake	status	source`
   - `Results`: `match_id	match	home_score	away_score	updated_at`
   - `Settled`: `pick_id	person	match	bet_type	selection	stake	odds	result	profit`
   - `Summary`: `person	total_stake	total_profit	win_count	lose_count`

2. **Mở Apps Script**: `Extensions` → `Apps Script` → đổi tên project `BetTracker-Backend`.

3. **Paste code**: Xóa `function myFunction() {}` mặc định, paste toàn bộ nội dung file `BetTracker.gs`.

4. **Cấp quyền lần đầu**: dropdown function chọn `readSheet` → `▶ Run` → cho phép Sheets access.

5. **Script Properties** (Project Settings ⚙️ → Script Properties):
   - `GITHUB_RAW_URL` = `https://raw.githubusercontent.com/CloudHoang/NhaCai/main/data/matches.json`

6. **Refresh cache lần đầu**: chạy function `refreshMatchCache` trong editor.

7. **Trigger tự động** (Triggers ⏰):
   - `refreshMatchCache` → Day timer → 09:00 hàng ngày.

8. **Deploy Web App**:
   - `Deploy` → `New deployment` → type **Web App**.
   - Execute as: **Me**, Who has access: **Anyone**.
   - Copy URL (dạng `https://script.google.com/macros/s/<DEPLOY_ID>/exec`).
   - Paste URL vào biến `GAS_WEB_APP_URL` trong `app.py` (hoặc env var `GAS_WEB_APP_URL`).

9. **Re-deploy khi sửa code**:
   - `Deploy` → `Manage deployments` → ✏️ Edit → chọn version mới → `Deploy`.
   - URL giữ nguyên.

## API endpoints

| Method | Query / Body | Mô tả |
|--------|--------------|-------|
| GET    | `?action=full` | Trả về tất cả (picks, results, settled, summary) |
| GET    | `?action=picks` | Danh sách picks |
| GET    | `?action=results` | Kết quả các trận |
| GET    | `?action=settled` | Picks đã settle |
| GET    | `?action=summary` | Thống kê theo người chơi |
| POST   | `?action=uploadCsv` body=`csv` | Import picks từ CSV/TSV |
| POST   | `?action=updateResult` body=`{match_id, home_score, away_score}` | Cập nhật tỷ số + auto settle |
| POST   | `?action=settle` | Re-settle thủ công |

## CSV format cho `uploadCsv`

Tab-separated, header optional. Mỗi dòng: `person\tmatch\tselection\tstake\tstatus`.

```
NHPhuc	Nam Phi - Canada	Nam Phi 0 - 0 Canada	2	Active
NHPhuc	Pháp - Senegal	Pháp -0.5	1	Active
NHPhuc	Anh - Croatia	Tai 2.5	1	Active
```

Selection parser tự nhận:
- **Correct score**: `Nam Phi 0 - 0 Canada` → `bet_type=correct_score, selection=0-0`.
- **Handicap**: `Pháp -0.5` / `Canada +0.25` → `bet_type=handicap, line=±N`.
- **Over/Under**: `Tai 2.5` / `Xiu 2.75` → `bet_type=over_under, line=N`.

Sau khi upload, GAS tự lookup `odds` từ `MATCHES_CACHE` (nếu match name match).
