import re
import json

def clean_rsc_payload(html_content):
    """
    Trích xuất và liên kết các Next.js RSC payload pushes từ HTML.
    """
    pushes = re.findall(r'self\.__next_f\.push\(\[\d+,\"(.*?)\"\]\)', html_content)
    full_payload = ""
    for p in pushes:
        decoded = p.replace('\\"', '"').replace('\\/', '/').replace('\\n', '\n')
        full_payload += decoded
    return full_payload

def extract_matches(payload):
    """
    Trích xuất toàn bộ danh sách trận đấu và tỷ lệ odds từ RSC payload.
    """
    matches = []

    parts = payload.split('{"id":')
    for p in parts[1:]:
        match_data = p.split(',{"id":')[0]
        json_str = '{"id":' + match_data

        if json_str.endswith(','):
            json_str = json_str[:-1]

        brace_count = 0
        end_idx = 0
        for i, c in enumerate(json_str):
            if c == '{':
                brace_count += 1
            elif c == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = i
                    break
        if end_idx > 0:
            json_str = json_str[:end_idx+1]

        try:
            data = json.loads(json_str)
            if "homeName" in data and "awayName" in data:
                matches.append(data)
        except Exception:
            pass

    unique_matches = {}
    for m in matches:
        unique_matches[m["id"]] = m

    return list(unique_matches.values())

def extract_correct_score(payload):
    """
    Trích xuất tỷ số chính xác từ RSC payload của trang odds.
    """
    # Tìm đoạn correctScoresOdds\":[...]
    match = re.search(r'\"correctScoresOdds\":(\[.*?\])', payload)
    if not match:
        return []

    try:
        # Làm sạch chuỗi JSON (đôi khi có ký tự đặc biệt từ RSC)
        json_str = match.group(1)
        # Loại bỏ các escape không cần thiết nếu có
        return json.loads(json_str)
    except Exception as e:
        print(f"Lỗi parse correct score: {e}")
        return []

if __name__ == "__main__":
    # Test thử nghiệm với file cached HTML có sẵn
    cached_file = "/home/cloud/.claude/projects/-home-cloud-00-Claude-Bet/84129d25-83c5-4f3b-b515-b21a585423e1/tool-results/ba08xxd75.txt"
    try:
        with open(cached_file, 'r', encoding='utf-8') as f:
            html = f.read()
        payload = clean_rsc_payload(html)
        matches = extract_matches(payload)
        print(f"Tổng số trận đấu tìm thấy: {len(matches)}")
        if matches:
            print("Trận đấu đầu tiên:")
            print(json.dumps(matches[0], indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Lỗi chạy thử nghiệm: {e}")
