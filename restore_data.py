"""Restore 54 broken matches entries from pre-compact git history."""
import json, sys
sys.path.insert(0, '/home/cloud/00.Claude/Bet')
from crawler import to_compact

# 1) Read pre-compact data (full format with homeName/correctScores)
old_raw = __import__('subprocess').check_output(
    ['git', 'show', '82feab0:data/matches.json']
)
old_full = json.loads(old_raw)
print(f"Pre-compact: {len(old_full)} matches")

# 2) Apply fixed to_compact on pre-compact data
old_compact = [to_compact(m) for m in old_full]
old_by_id = {m["id"]: m for m in old_compact}
print(f"After compact: {len(old_compact)} matches")

# 3) Read current data
with open('data/matches.json') as f:
    current = json.load(f)
print(f"Current: {len(current)} matches")
empty = [m for m in current if not m.get('home') and not m.get('away')]
good = [m for m in current if m.get('home')]
print(f"Current empty: {len(empty)}, good: {len(good)}")

# 4) Merge: old data + any new matches from current
merged_by_id = dict(old_by_id)
for m in current:
    mid = m.get("id")
    if mid and mid not in old_by_id:
        merged_by_id[mid] = m

merged = list(merged_by_id.values())
merged.sort(key=lambda x: x.get("time", 0) or 0)

with open('data/matches.json', 'w', encoding='utf-8') as f:
    json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))

print(f"Written {len(merged)} matches")
good_final = [m for m in merged if m.get('home')]
print(f"With names: {len(good_final)}")
if good_final:
    for m in good_final:
        print(f"  {m.get('home')} vs {m.get('away')} | cs:{len(m.get('cs',[]))}")
