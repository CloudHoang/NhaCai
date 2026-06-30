# CLAUDE.md

## Mục tiêu dự án
* Cào dữ liệu tỷ lệ kèo World Cup từ nguồn keobongvip và tự động gửi thông báo trực quan qua Telegram.
* Hiển thị bảng tỷ lệ kèo (Chấp, Tài Xỉu, Châu Âu, Tỷ số chính xác) lên giao diện Web (hỗ trợ Flask và GitHub Pages trang tĩnh).
* Hỗ trợ tải ảnh thẻ kèo (Card Match) định dạng đẹp, nằm ngang không bị lỗi CORS cờ/logo.

## Kiến trúc & Cách vận hành
1. **Crawler (`crawler.py`)**:
   * Định kỳ chạy (qua cronjob) cào dữ liệu trận đấu và chi tiết tỷ số chính xác.
   * Lọc trận đấu theo múi giờ GMT+7 (từ 17:00 hôm nay đến 15:00 ngày tiếp theo).
   * Tải cờ quốc gia của hai đội về thư mục `flags/` để cache và tránh lỗi CORS.
   * Tính toán tỷ số AOS (Any Other Score) dựa trên thuật toán `AOS.md` (`calculate_aos` trong `crawler.py`).
   * Lưu dữ liệu vào `data/matches.json` và gửi thông báo qua Telegram.
2. **Parser (`parser.py`)**: Bóc tách dữ liệu RSC payload thô từ HTTP response.
3. **Web Server (`app.py`)**:
   * Đọc `data/matches.json`, phục vụ API và render HTML động qua `templates/index.html`.
   * Phục vụ static file `/flags/<filename>` từ thư mục local.
   * Routes bổ sung: `/tracker`, `/admin/result`, `/api/tracker` (xem mục Betting Tracker).
4. **Static Builder (`build.py`)**: Tạo trang `index.html` tĩnh từ template để deploy GitHub Pages. Đồng thời build `tracker/index.html` + `result/index.html` (load data qua fetch từ GAS).
5. **Betting Tracker (`tracker.py` + `gas/BetTracker.gs`)**:
   * Backend: **Google Apps Script** bound với Google Sheets (4 tab: Picks/Results/Settled/Summary).
   * Client Python (`tracker.py`): wrapper gọi GAS Web App endpoint (urllib3).
   * Cấu hình URL qua env `GAS_WEB_APP_URL` hoặc default trong `tracker.py`.

## Môi trường & Dependencies
* Python 3.8+
* Flask (Web app)
* Jinja2 (HTML templating)
* urllib3 (HTTP requests — dùng cho cả crawler và tracker client)
* Cấu hình cron chạy qua file `cron_setup.sh` sinh file bash chạy ngầm `run_crawler.sh` lúc 16:30 hàng ngày.

## Commands

### Setup & Run
* Run local web server: `python3 app.py` (runs on `http://localhost:5000`)
* Run static builder (GitHub Pages): `python3 build.py` (generates `index.html`, `tracker/index.html`, `result/index.html`)
* Run crawler: `python3 crawler.py`
* Setup daily cronjob: `bash cron_setup.sh`

### Betting Tracker
* Flask local: `http://localhost:5000/tracker` (tổng hợp) · `/admin/result` (nhập tỷ số).
* Static GitHub Pages: `/tracker/` · `/result/` (load trực tiếp từ GAS).
* Setup Google Sheets + GAS: xem `gas/README.md` (tạo 4 tab, paste code, deploy Web App, set Script Properties).

### Testing
* Verify static server: Python HTTP server on port 8000
* Fetch odds data manually: `python3 crawler.py`
* Test GAS endpoint: `curl "https://script.google.com/macros/s/<DEPLOY_ID>/exec?action=full"`

## Code Guidelines

### Layout & Design
* Matches table cards must match horizontally for 3 main markets (Handicap, Over/Under, Europe 1X2).
* Export image width must be exactly 1024px to preserve horizontal layout (`windowWidth: 1024` inside html2canvas settings in [templates/index.html](templates/index.html)).

### CORS & Images
* Remote logos (team/national flags) must be downloaded locally to avoid CORS errors when generating canvas images.
* All logo downloads are handled by `download_flag(url)` in [crawler.py](crawler.py) and saved in [flags/](flags/).
* Flask route `/flags/<filename>` serves these assets via `send_from_directory` in [app.py](app.py).

### Data Restrictions
* Max odds ceiling is capped at 20.0 (`clamp_odds` in [app.py](app.py) and [crawler.py](crawler.py)).
* Football handicap signs must be inverted via `invert_handicap` to align with local display standards.
* Daily matches filtered from 17:00 today to 15:00 tomorrow (GMT+7 timezone).

## Recent Changes
* **Tích hợp cup26matches.com**:
  * Tự động crawl tỷ lệ dự đoán thắng (Win Probabilities / AI Predictions) từ `https://cup26matches.com/en/` hàng ngày.
  * So khớp các trận đấu dựa trên mã quốc gia (Code) từ file `codename.md`.
  * Lưu kết quả vào trường `predictions` (`homeWin`, `draw`, `awayWin`) trong `data/matches.json` và cập nhật thông tin trong file markdown chi tiết.
* **Giao diện Web & Bố cục**:
  * Hiển thị tỷ lệ dự đoán thắng ngay dưới tên đội bóng dạng thanh Progress Bar 3 màu cực kỳ nhỏ gọn (Xanh lá - Xám - Đỏ).
  * Di chuyển cờ quốc gia của hai đội vào giữa, hiển thị sát hai bên chữ `vs` (định dạng `Tên Đội 1 [Cờ] vs [Cờ] Tên Đội 2`).
  * Tích hợp tính năng **Dark Mode** với nút chuyển đổi ở góc trên bên phải, lưu trạng thái bằng `localStorage` và tự động điều chỉnh màu nền của `html2canvas` khi chụp ảnh kèo.
* **Môi trường vận hành hiện tại**:
  * Localhost server Flask chạy trên cổng 5000 (`app.py`).
  * Build tĩnh index.html và các file markdown thành công.
  * Đã commit và push tất cả thay đổi lên branch `main`.
* **Betting Tracker (Google Apps Script)**:
  * Tổng hợp thắng/thua picks từ email → Google Sheets qua GAS.
  * Hỗ trợ 3 loại kèo: `correct_score`, `handicap`, `over_under`.
  * Routes Flask: `/tracker` (tổng hợp), `/admin/result` (nhập tỷ số), `/api/tracker` (JSON).
  * Static pages GitHub Pages: `tracker/index.html` + `result/index.html` (fetch trực tiếp GAS).
  * Backend GAS: xem `gas/BetTracker.gs` (code) + `gas/README.md` (setup).
  * Client Python: `tracker.py` (GAS_WEB_APP_URL qua env hoặc default).

