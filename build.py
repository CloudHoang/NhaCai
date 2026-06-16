import json
import os
from jinja2 import Environment, FileSystemLoader
from app import load_matches_data

def build_static():
    # Tải dữ liệu đã làm sạch qua logic của app.py
    matches = load_matches_data()

    rounds = {}
    for m in matches:
        r_name = m.get("roundName", "Khác")
        if r_name not in rounds:
            rounds[r_name] = []
        rounds[r_name].append(m)

    for r in rounds:
        rounds[r].sort(key=lambda x: x.get("matchTime", 0))

    # Cấu hình Jinja2 để render template index.html tĩnh
    env = Environment(loader=FileSystemLoader('/home/cloud/00.Claude/Bet/templates'))
    template = env.get_template('index.html')

    output = template.render(rounds=rounds)

    # Ghi file index.html ra thư mục gốc để GitHub Pages đọc trực tiếp
    output_path = "/home/cloud/00.Claude/Bet/index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"Build index.html thành công tại: {output_path}")

if __name__ == "__main__":
    build_static()
