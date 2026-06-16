# World Cup Betting Odds Crawler & Monitor

> **LƯU Ý QUAN TRỌNG:** TÀI LIỆU VÀ MÃ NGUỒN NÀY CHỈ LƯU HÀNH NỘI BỘ VÀ DÙNG CHO MỤC ĐÍCH THAM KHẢO, HỌC TẬP NGHIÊN CỨU CÔNG NGHỆ CÀO DỮ LIỆU (WEB CRAWLER). 

---

## ⚖️ Tuyên Bố Miễn Trừ Trách Nhiệm (Disclaimer)
* **Mục đích:** Dự án này được phát triển hoàn toàn vì mục đích học tập, nghiên cứu kỹ thuật phân tích Next.js RSC (React Server Components) payload và Flask framework.
* **Không khuyến khích cá cược:** Chúng tôi không khuyến khích, cổ suy hay chịu trách nhiệm cho bất kỳ hành vi cá cược trực tuyến hoặc sử dụng thông tin từ hệ thống này vào mục đích cá cược bất hợp pháp dưới mọi hình thức.
* **Độ chính xác:** Dữ liệu cào từ bên thứ ba chỉ mang tính chất tham khảo tại thời điểm cào. Chúng tôi không đảm bảo tính chính xác, kịp thời hoặc độ tin cậy của dữ liệu hiển thị.
* **Bảo mật:** Không chia sẻ hoặc công khai thông tin cấu hình (`.env`) chứa API Token của Telegram hoặc bất kỳ dữ liệu nhạy cảm nào khác ra bên ngoài.

---

## 🚀 Tính Năng Chính
1. **Cào dữ liệu tự động:** Cào thông tin lịch thi đấu và các tỷ lệ kèo (Chấp, Tài Xỉu, Châu Âu 1X2) từ nguồn keobongvip.
2. **Lọc thời gian thông minh:** Chỉ quét các trận đấu diễn ra từ **17:00 hôm nay đến 15:00 ngày hôm sau (múi giờ GMT+7)**.
3. **Cào chi tiết Tỷ Số Chính Xác (Correct Score):** Lấy chi tiết toàn bộ tỷ lệ tỷ số của từng trận đấu.
4. **Phân loại 3 cột:** Tự động chia tỷ số chính xác theo 3 nhóm trực quan: **CHỦ THẮNG** | **HÒA** | **KHÁCH THẮNG** trên cả giao diện Web và thông báo Telegram.
5. **Gửi thông báo Telegram:** Tự động gửi cập nhật dạng bảng cột có căn lề monospaced qua Telegram Bot sau mỗi phiên quét.

---

## 🛠️ Yêu Cầu Hệ Thống
* Python 3.8+
* Thư viện Flask (cho Web giao diện)
* Cron (dành cho Linux tự động chạy)

---

## ⚙️ Hướng Dẫn Cài Đặt

### 1. Cấu hình biến môi trường
Tạo file `.env` tại thư mục gốc của dự án:
```env
TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
TELEGRAM_CHAT_ID="YOUR_CHAT_ID"
```

### 2. Khởi chạy Web Server
```bash
python3 app.py
```
*Giao diện hiển thị tại địa chỉ: `http://localhost:5000`*

### 3. Chạy Crawler thủ công
```bash
python3 crawler.py
```

### 4. Cấu hình tự động quét (Cronjob)
Chạy script cấu hình tự động quét lúc 16:30 hàng ngày (GMT+7):
```bash
bash cron_setup.sh
```

---

## 📁 Cấu trúc thư mục dự án
* `app.py`: Flask Web Server hiển thị bảng tỷ lệ.
* `crawler.py`: Module chính thực hiện cào dữ liệu và gửi Telegram.
* `parser.py`: Xử lý bóc tách RSC payload và regex.
* `templates/index.html`: Giao diện Web hiển thị bảng odds 3 cột.
* `cron_setup.sh`: Cấu hình crontab tự động hóa.
* `.env`: Lưu trữ Token bí mật (được ignore khỏi git).
