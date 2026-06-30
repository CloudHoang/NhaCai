# Môi Trường Google Platform - Setup Guide

## Tổng quan

Dùng Google Sheets làm data store free, Google Apps Script (GAS) làm backend. Web UI Flask local gọi GET/POST tới GAS Web App.

---

## Bước 1: Tạo Google Sheets

### 1.1 Tạo file mới
- Vào [sheets.new](https://sheets.new) → tự động tạo sheet trắng.
- Đổi tên: `BetTracker` (hoặc tùy ý).

### 1.2 Tạo các sheet (tab)

Click dấu `+` ở góc dưới trái để thêm tab. Cần **4 tab**:

```
[Picks] [Results] [Settled] [Summary]
```

### 1.3 Nhập header các tab

Copy từng dòng header dưới đây paste vào dòng 1 của mỗi tab.

**Sheet `Picks`**
```
pick_id	timestamp	person	match	bet_type	selection	line	odds	stake	status	source
```

**Sheet `Results`**
```
match_id	match	home_score	away_score	updated_at
```

**Sheet `Settled`**
```
pick_id	person	match	bet_type	selection	stake	odds	result	profit
```

**Sheet `Summary`**
```
person	total_stake	total_profit	win_count	lose_count
```

### 1.4 Lưu ý

- Để nguyên dòng 1 là header.
- Dòng 2 trở đi để trống (GAS sẽ append data).
- Tab separator dùng **tab thực** (paste vào Sheets sẽ tự chia cột).

---

## Bước 2: Tạo Google Apps Script

### 2.1 Mở editor
- Trong Sheets: `Extensions` → `Apps Script`.
- Tab mới mở ra ở [script.google.com](https://script.google.com).
- Đổi tên project: `BetTracker-Backend`.

### 2.2 Dán code

Xóa code mặc định (`function myFunction() {}`), paste toàn bộ code dưới đây.

```javascript
// ─── Constants ───────────────────────────────────────────────────────────────
const SHEET_PICKS   = 'Picks';
const SHEET_RESULTS = 'Results';
const SHEET_SETTLED = 'Settled';
const SHEET_SUMMARY = 'Summary';

const SPREADSHEET = SpreadsheetApp.getActiveSpreadsheet();

// ─── CORS helper ─────────────────────────────────────────────────────────────
function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Content-Type': 'application/json; charset=utf-8'
  };
}

// ─── Web App entry ───────────────────────────────────────────────────────────
function doGet(e) {
  const params = e ? (e.parameter || {}) : {};
  const action = params.action || 'full';

  const out = {};
  if (action === 'picks'   || action === 'full') out.picks   = readSheet(SHEET_PICKS);
  if (action === 'results' || action === 'full') out.results = readSheet(SHEET_RESULTS);
  if (action === 'settled' || action === 'full') out.settled = readSheet(SHEET_SETTLED);
  if (action === 'summary' || action === 'full') out.summary = readSheet(SHEET_SUMMARY);

  return ContentService.createTextOutput(JSON.stringify(out))
    .setMimeType(ContentService.MimeType.JSON)
    .setHeaders(corsHeaders());
}

function doPost(e) {
  const params = e ? (e.parameter || {}) : {};
  const action = params.action || '';

  try {
    if (action === 'uploadCsv') {
      const csv = e.postData ? e.postData.contents : '';
      const result = importCsv(csv);
      return jsonResponse(result);
    }
    if (action === 'updateResult') {
      const body = JSON.parse(e.postData ? e.postData.contents : '{}');
      const result = updateResult(body.match_id, body.home_score, body.away_score);
      return jsonResponse(result);
    }
    if (action === 'settle') {
      const result = settlePicks();
      return jsonResponse(result);
    }
    return jsonResponse({ error: 'Unknown action: ' + action });
  } catch (err) {
    return jsonResponse({ error: err.toString() });
  }
}

// ─── Upload CSV → Picks sheet ────────────────────────────────────────────────
function importCsv(csvText) {
  const rows = Utilities.parseCsv(csvText, '\t');       // tab-separated
  // bỏ header nếu có
  if (rows.length && rows[0][0] === 'person') rows.shift();

  const sheet = SPREADSHEET.getSheetByName(SHEET_PICKS);
  let inserted = 0;
  const ts = new Date().toISOString();

  for (const row of rows) {
    // row: [person, match, selection_raw, stake_raw, status]
    const person    = (row[0] || '').trim();
    const match     = (row[1] || '').trim();
    const selection = (row[2] || '').trim();
    const stake     = parseFloat((row[3] || '').replace(/[^0-9.]/g, ''));
    const status    = (row[4] || 'Active').trim();

    if (!person || !match || isNaN(stake)) continue;

    // Parse selection để suy bet_type, line, odds
    const parsed = parseSelection(selection, match);

    const pickId = 'p' + (Date.now().toString(36) + Math.random().toString(36).slice(2, 6));
    sheet.appendRow([
      pickId, ts, person, match,
      parsed.bet_type, parsed.selection_val, parsed.line, parsed.odds,
      stake, status, 'upload'
    ]);
    inserted++;
  }

  // Sau khi import, clean up odds bằng cách lookup từ matches.json
  // (nếu match có trong danh sách)
  fillOddsFromMatches();

  return { success: true, inserted: inserted };
}

// ─── Parse selection string ───────────────────────────────────────────────────
function parseSelection(raw, match) {
  // raw examples:
  //   "Nam Phi 0 - 0 Canada"    → correct_score, 0-0
  //   "Nam Phi -0.5"            → handicap, home, line=-0.5
  //   "Canada +0.5"             → handicap, away, line=+0.5
  //   "Tai 2.5"                 → over_under, over, line=2.5
  //   "Xiu 2.75"                → over_under, under, line=2.75

  const s = raw.trim();

  // Correct score: <team> <H> - <A> <team>
  const csMatch = s.match(/(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)/);
  if (csMatch) {
    return {
      bet_type: 'correct_score',
      selection_val: csMatch[2] + '-' + csMatch[3],
      line: '',
      odds: ''
    };
  }

  // Over/Under: "Tai" hoặc "Xiu" + số
  const ouMatch = s.match(/(tai|xỉu|Tài|Xỉu|Xỉu|Xiu)\s*([\d.]+)/i);
  if (ouMatch) {
    const side = ouMatch[1].toLowerCase().startsWith('tai') || ouMatch[1].toLowerCase().startsWith('tài') ? 'over' : 'under';
    return {
      bet_type: 'over_under',
      selection_val: side,
      line: ouMatch[2],
      odds: ''
    };
  }

  // Handicap: <team> +-<number>
  const hdpMatch = s.match(/(.+?)\s+([+\-][\d.]+)/);
  if (hdpMatch) {
    const team  = hdpMatch[1].trim();
    const line  = parseFloat(hdpMatch[2]);
    // Xác định home/away dựa trên tên team trong match
    const parts  = match.split(/\s*-\s*/);
    const home   = parts[0] ? parts[0].trim() : '';
    const away   = parts[1] ? parts[1].trim() : '';
    const isHome = team.toLowerCase().includes(home.toLowerCase().slice(0, 3)) || home.toLowerCase().includes(team.toLowerCase().slice(0, 3));
    return {
      bet_type: 'handicap',
      selection_val: isHome ? 'home' : 'away',
      line: String(line),
      odds: ''
    };
  }

  // fallback: đánh dấu unknown
  return { bet_type: 'unknown', selection_val: s, line: '', odds: '' };
}

// ─── Fill odds từ matches data (lookup bằng match name) ───────────────────────
function fillOddsFromMatches() {
  // Nếu có data matches trong Script Properties (cache từ GitHub)
  const matchesJson = PropertiesService.getScriptProperties().getProperty('MATCHES_CACHE');
  if (!matchesJson) return;

  const matches = JSON.parse(matchesJson);
  const sheet   = SPREADSHEET.getSheetByName(SHEET_PICKS);
  const data    = sheet.getDataRange().getValues();

  for (let i = 1; i < data.length; i++) {
    const row      = data[i];
    const matchName = row[3];   // cột D
    const betType   = row[4];   // cột E
    const selection = row[5];   // cột F
    const line      = row[6];   // cột G
    const existingOdds = row[7]; // cột H

    if (existingOdds) continue; // đã có odds

    const m = findMatch(matches, matchName);
    if (!m || !m.odds) continue;

    let odds = '';
    if (betType === 'correct_score') {
      const csList = m.cs || [];
      const found = csList.find(function(s) { return s.startsWith(selection + ':'); });
      if (found) odds = found.split(':')[2] || '';
    } else if (betType === 'handicap') {
      const hc = m.odds.handicap || {};
      if (selection === 'home') odds = hc.instantHome || '';
      else if (selection === 'away') odds = hc.instantAway || '';
    } else if (betType === 'over_under') {
      const ou = m.odds.overUnder || {};
      if (selection === 'over') odds = ou.instantOver || '';
      else if (selection === 'under') odds = ou.instantUnder || '';
    }

    if (odds) sheet.getRange(i + 1, 8).setValue(odds); // cột H
  }
}

// ─── Find match trong matches cache ───────────────────────────────────────────
function findMatch(matches, name) {
  const n = name.trim().toLowerCase();
  for (const m of matches) {
    const hn = (m.home || '').toLowerCase();
    const an = (m.away || '').toLowerCase();
    if (n.includes(hn) && n.includes(an)) return m;
  }
  return null;
}

// ─── Update match result ──────────────────────────────────────────────────────
function updateResult(matchId, homeScore, awayScore) {
  const sheet = SPREADSHEET.getSheetByName(SHEET_RESULTS);
  const data  = sheet.getDataRange().getValues();

  // Tìm xem đã có match_id chưa → update; nếu chưa → append
  let found = false;
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]) === String(matchId)) {
      sheet.getRange(i + 1, 3).setValue(homeScore);
      sheet.getRange(i + 1, 4).setValue(awayScore);
      sheet.getRange(i + 1, 5).setValue(new Date().toISOString());
      found = true;
      break;
    }
  }
  if (!found) {
    sheet.appendRow([String(matchId), '', homeScore, awayScore, new Date().toISOString()]);
  }

  // Tự động settle sau khi update result
  settlePicks();
  return { success: true, match_id: matchId, settled: true };
}

// ─── Settlement logic ─────────────────────────────────────────────────────────
function settlePicks() {
  const picks   = readSheet(SHEET_PICKS);
  const results = readSheet(SHEET_RESULTS);
  const resultMap = {};
  results.forEach(function(r) { resultMap[String(r.match_id)] = r; });

  const settled    = SPREADSHEET.getSheetByName(SHEET_SETTLED);
  const summary    = SPREADSHEET.getSheetByName(SHEET_SUMMARY);

  // Clear cũ
  settled.clearContents();
  summary.clearContents();

  // Header
  settled.appendRow(['pick_id', 'person', 'match', 'bet_type', 'selection', 'stake', 'odds', 'result', 'profit']);
  summary.appendRow(['person', 'total_stake', 'total_profit', 'win_count', 'lose_count']);

  const personStats = {}; // { person: { total_stake, total_profit, win, lose } }

  let settledCount = 0;
  for (const p of picks) {
    if (p.status === 'Cancelled') continue;

    const res = resultMap[String(p.match_id)];
    if (!res) continue; // chưa có kết quả

    const outcome = calculateProfit(p, res);

    settled.appendRow([
      p.pick_id, p.person, p.match, p.bet_type, p.selection,
      p.stake, p.odds, outcome.result, outcome.profit
    ]);
    settledCount++;

    if (!personStats[p.person]) {
      personStats[p.person] = { total_stake: 0, total_profit: 0, win: 0, lose: 0 };
    }
    personStats[p.person].total_stake += parseFloat(p.stake) || 0;
    personStats[p.person].total_profit += outcome.profit;
    if (outcome.result === 'win') personStats[p.person].win++;
    else if (outcome.result === 'lose') personStats[p.person].lose++;
  }

  for (const [name, s] of Object.entries(personStats)) {
    summary.appendRow([name, s.total_stake, s.total_profit, s.win, s.lose]);
  }

  return { success: true, settled: settledCount };
}

function calculateProfit(pick, result) {
  const stake  = parseFloat(pick.stake) || 0;
  const odds   = parseFloat(pick.odds) || 0;
  const home   = parseInt(result.home_score, 10);
  const away   = parseInt(result.away_score, 10);
  const line   = parseFloat(pick.line) || 0;
  const type   = pick.bet_type;
  const sel    = pick.selection;

  // Correct score
  if (type === 'correct_score') {
    const parts = sel.split('-');
    if (parts.length === 2 && parseInt(parts[0]) === home && parseInt(parts[1]) === away) {
      return { result: 'win', profit: stake * odds };
    }
    return { result: 'lose', profit: -stake };
  }

  // Handicap
  if (type === 'handicap') {
    let margin;
    if (sel === 'home') {
      margin = home - away + line;
    } else {
      margin = away - home + line;
    }
    const outcome = halfBallOutcome(margin, line);
    if (outcome === 'win')      return { result: 'win',  profit: stake * odds };
    if (outcome === 'half_win') return { result: 'win',  profit: stake * odds / 2 };
    if (outcome === 'half_lose') return { result: 'lose', profit: -stake / 2 };
    if (outcome === 'lose')     return { result: 'lose', profit: -stake };
    return { result: 'push', profit: 0 };
  }

  // Over/Under
  if (type === 'over_under') {
    const total = home + away;
    let margin;
    if (sel === 'over') {
      margin = total - line;
    } else {
      margin = line - total;
    }
    const outcome = halfBallOutcome(margin, line);
    if (outcome === 'win')      return { result: 'win',  profit: stake * odds };
    if (outcome === 'half_win') return { result: 'win',  profit: stake * odds / 2 };
    if (outcome === 'half_lose') return { result: 'lose', profit: -stake / 2 };
    if (outcome === 'lose')     return { result: 'lose', profit: -stake };
    return { result: 'push', profit: 0 };
  }

  return { result: 'unknown', profit: 0 };
}

// ─── Half-ball (quarter-ball) outcome ─────────────────────────────────────────
function halfBallOutcome(margin, lineStr) {
  const line = parseFloat(lineStr) || 0;
  const isQuarter = Math.abs(line % 1) > 0.01 && Math.abs(Math.abs(line % 1) - 0.5) > 0.01;

  if (!isQuarter) {
    // whole ball hoặc half ball
    if (margin > 0) return 'win';
    if (margin < 0) return 'lose';
    return 'push';
  }

  // quarter ball: margin nằm trong khoảng ±0.5
  if (margin >= 0.5) return 'win';
  if (margin <= -0.5) return 'lose';
  if (margin > 0 && margin < 0.5) return 'half_win';
  if (margin < 0 && margin > -0.5) return 'half_lose';
  return 'push';
}

// ─── Utility: read sheet → array of objects ───────────────────────────────────
function readSheet(name) {
  const sheet = SPREADSHEET.getSheetByName(name);
  if (!sheet) return [];
  const data = sheet.getDataRange().getValues();
  if (!data.length) return [];
  const headers = data[0].map(function(h) { return String(h).trim(); });
  const result = [];
  for (let i = 1; i < data.length; i++) {
    const row = {};
    for (let j = 0; j < headers.length; j++) {
      row[headers[j]] = data[i][j];
    }
    // lọc row rỗng
    const vals = Object.values(row).filter(function(v) { return v !== '' && v !== undefined && v !== null; });
    if (vals.length > 0) result.push(row);
  }
  return result;
}

function jsonResponse(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON)
    .setHeaders(corsHeaders());
}
```

### 2.3 Save
- `Ctrl+S` hoặc click icon 💾 Save.
- Chạy thử `readSheet` để cấp quyền lần đầu:
  - Chọn function `readSheet` ở dropdown.
  - Click `▶ Run` → popup xin quyền → **Review permissions** → chọn tài khoản Google → **Advanced** → **Go to BetTracker-Backend (unsafe)** → **Allow**.

---

## Bước 3: Deploy Web App

### 3.1 Deploy
- Trong GAS editor: `Deploy` (góc trên phải) → `New deployment`.
- Type: **Web App**.
- Description: `BetTracker API v1`.
- Execute as: **Me** (tài khoản của bạn).
- Who has access: **Anyone**.
- Click **Deploy**.
- Copy URL được sinh ra (dạng `https://script.google.com/macros/s/.../exec`).

### 3.2 Test deploy
```bash
# Test GET
curl "https://script.google.com/macros/s/XXXX/exec?action=full"

# Test POST (upload CSV)
curl -X POST "https://script.google.com/macros/s/XXXX/exec?action=uploadCsv" \
  -H "Content-Type: text/plain" \
  -d "person	match	selection	stake	status
NHPhuc	Nam Phi - Canada	Nam Phi 0 - 0 Canada	2 điểm	Active"
```

---

## Bước 4: Cache matches.json vào GAS (optional)

Để tự động lookup odds khi import pick, cần cache data `matches.json` từ GitHub:

1. Trong GAS editor: `Project Settings` (⚙️ gear icon) → `Script Properties`.
2. Add property:
   - Key: `GITHUB_RAW_URL`
   - Value: `https://raw.githubusercontent.com/CloudHoang/NhaCai/main/data/matches.json`
3. Thêm function refresh cache trong GAS:
```javascript
function refreshMatchCache() {
  const url = PropertiesService.getScriptProperties().getProperty('GITHUB_RAW_URL');
  const resp = UrlFetchApp.fetch(url);
  PropertiesService.getScriptProperties().setProperty('MATCHES_CACHE', resp.getContentText());
  Logger.log('Cache refreshed: ' + resp.getContentText().length + ' bytes');
}
```
4. Chạy `refreshMatchCache` lần đầu → set daily trigger:
   - GAS editor: `Triggers` (⏰ icon) → `+ Add Trigger`.
   - Function: `refreshMatchCache`.
   - Time: `Day timer`, chọn giờ (e.g. 9am).

---

## Bước 5: Kết nối với Flask (project hiện tại)

Lưu URL GAS vào biến môi trường hoặc config:

```python
# Trong app.py hoặc config.py
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbxapxVRpm1RbazhvjY4yrJxmsSos0NjuJLBKslyuS9swuuBLj_kIsjznnw_R7ewdwow/exec"
```

Khi chạy Flask local, gọi API GAS để lấy dữ liệu tracker:

```python
import urllib3

def fetch_tracker_data():
    http = urllib3.PoolManager()
    resp = http.request("GET", GAS_WEB_APP_URL + "?action=full")
    return json.loads(resp.data)
```

---

## Bước 6: Re-deploy sau khi sửa code

Quan trọng: **GAS không tự update sau mỗi lần save**. Cần deploy lại:

- `Deploy` → `Manage deployments` → click icon ✏️ (Edit) ở deployment hiện tại.
- Chọn version mới nhất (hoặc `New version`).
- Click **Deploy**.
- Không cần đổi URL (URL giữ nguyên, chỉ cập nhật version).

---

## Tổng kết checklist

- [ ] Google Sheets đã tạo 4 tab + header
- [ ] GAS code đã paste + save
- [ ] GAS đã cấp quyền (Read/Write Sheets)
- [ ] GAS Web App đã deploy, access = Anyone
- [ ] Web App URL đã copy + test bằng curl
- [ ] Cache matches.json đã refresh (nếu dùng)
- [ ] Flask project cập nhật GAS_URL

## URL quan trọng

| Item | URL |
|------|-----|
| Sheets | `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit` |
| GAS Editor | `https://script.google.com/d/<SCRIPT_ID>/edit` |
| GAS Web App | `https://script.google.com/macros/s/<DEPLOY_ID>/exec` |
