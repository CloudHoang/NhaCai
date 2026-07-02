"""
Tách các trận knockout (round != 'Vòng bảng') từ data/matches.json
ra file mới data/matches32.json. Sau khi tách, file matches.json
chỉ còn vòng bảng (hoặc cả 2 tuỳ tham số --keep-group).
"""
import json
import os
import sys
import argparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "data", "matches.json")
OUT_FILE = os.path.join(ROOT, "data", "matches32.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep-group",
        action="store_true",
        help="Giữ vòng bảng trong matches.json (mặc định: xoá vòng bảng khỏi matches.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Chỉ in số liệu, không ghi file.",
    )
    args = parser.parse_args()

    if not os.path.exists(DATA_FILE):
        print(f"Không tìm thấy {DATA_FILE}")
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        matches = json.load(f)

    group = [m for m in matches if m.get("round") == "Vòng bảng"]
    knockout = [m for m in matches if m.get("round") != "Vòng bảng"]

    # Sắp xếp theo time
    knockout.sort(key=lambda m: m.get("time", 0))
    group.sort(key=lambda m: m.get("time", 0))

    print(f"Tổng: {len(matches)} trận")
    print(f"  Vòng bảng: {len(group)}")
    print(f"  Knockout: {len(knockout)}")
    rounds = {}
    for m in knockout:
        r = m.get("round") or "?"
        rounds[r] = rounds.get(r, 0) + 1
    for r, n in sorted(rounds.items()):
        print(f"    {r}: {n}")

    if args.dry_run:
        print("[dry-run] Không ghi file.")
        return

    # Ghi matches32.json
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(knockout, f, ensure_ascii=False, indent=2)
    print(f"Đã ghi {len(knockout)} trận knockout → {OUT_FILE}")

    if not args.keep_group:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(group, f, ensure_ascii=False, indent=2)
        print(f"Đã ghi {len(group)} trận vòng bảng → {DATA_FILE}")
    else:
        print(f"Giữ nguyên matches.json (vẫn chứa cả {len(matches)} trận).")


if __name__ == "__main__":
    main()
