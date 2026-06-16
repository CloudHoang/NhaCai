#!/bin/bash

# Thiết lập cron job chạy crawler hàng ngày lúc 16:30 (GMT+7)
# 16:30 GMT+7 tương ứng với 09:30 UTC
# Kiểm tra múi giờ hiện tại của hệ thống:
TIMEZONE=$(cat /etc/timezone 2>/dev/null || echo "UTC")
echo "System timezone: $TIMEZONE"

# Tạo script thực thi crawler
CRAWLER_RUNNER="/home/cloud/00.Claude/Bet/run_crawler.sh"

cat << 'EOF' > "$CRAWLER_RUNNER"
#!/bin/bash
export PATH="/usr/local/bin:/usr/bin:/bin"
cd /home/cloud/00.Claude/Bet
/usr/bin/python3 crawler.py >> crawler.log 2>&1
EOF

chmod +x "$CRAWLER_RUNNER"

# Xác định biểu thức cron phù hợp dựa vào múi giờ hệ thống
# Nếu là GMT+7 (Asia/Ho_Chi_Minh) -> phút 30, giờ 16
# Nếu là UTC -> phút 30, giờ 9
if [[ "$TIMEZONE" == "Asia/Ho_Chi_Minh" ]]; then
    CRON_TIME="30 16 * * *"
else
    CRON_TIME="30 9 * * *"
fi

echo "Adding cronjob: $CRON_TIME $CRAWLER_RUNNER"

# Đọc cronjob hiện tại, thêm dòng mới nếu chưa tồn tại, và ghi lại vào crontab
(crontab -l 2>/dev/null | grep -v "run_crawler.sh"; echo "$CRON_TIME $CRAWLER_RUNNER") | crontab -

echo "Cron job đã được cấu hình thành công!"
crontab -l | grep "run_crawler.sh"
