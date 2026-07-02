// ─── Constants ───────────────────────────────────────────────────────────────
const SHEET_PICKS   = 'Picks';
const SHEET_RESULTS = 'Results';
const SHEET_SETTLED = 'Settled';
const SHEET_SUMMARY = 'Summary';

const SPREADSHEET = SpreadsheetApp.getActiveSpreadsheet();

// ─── CORS helper ─────────────────────────────────────────────────────────────
// Lưu ý: ContentService.TextOutput KHÔNG cho phép set custom headers trong
// Apps Script runtime mới. CORS chỉ work tự động với HtmlService. Với JSON,
// browser fetch sẽ thành công nếu dùng Content-Type: text/plain (no preflight).
// → Mọi client phải POST với 'Content-Type: text/plain;charset=utf-8' thay vì
//   'application/json' để bypass CORS preflight.
function jsonOutput(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
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
  if (action === 'matches' || action === 'full') out.matches = listMatches();

  if (action === 'backfillResultNames') {
    return jsonOutput(backfillResultNames());
  }

  if (action === 'revertCorruptedSelections') {
    return jsonOutput(revertCorruptedSelections());
  }

  if (action === 'revertCorruptedSettledSelections') {
    return jsonOutput(revertCorruptedSettledSelections());
  }

  return jsonOutput(out);
}

function listMatches() {
  const cache = PropertiesService.getScriptProperties().getProperty('MATCHES_CACHE');
  if (!cache) return [];
  try {
    const arr = JSON.parse(cache);
    return arr.map(function(m) {
      return { id: String(m.id), home: m.home || m.homeName || '', away: m.away || m.awayName || '', time: m.time || m.matchTime || 0 };
    });
  } catch (e) {
    return [];
  }
}

// ─── Robust body parser ────────────────────────────────────────────────────
// Browser dùng mode:'no-cors' chỉ cho phép Content-Type safelisted. Nếu client
// gửi 'application/json' thực sự → an toàn (GAS thấy JSON hợp lệ).
// Nếu client gửi 'text/plain' với body là JSON string → cũng OK.
// Nếu client gửi 'text/plain' với body CSV → fallback trả raw string.
// Hàm này tự nhận diện: thử parse JSON trước, fail thì trả raw.
function parseBody_(e) {
  const raw = e.postData ? e.postData.contents : '';
  if (!raw) return { _raw: '', _isJson: false };
  // Thử parse JSON
  const trimmed = raw.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      return JSON.parse(trimmed);
    } catch (err) {
      // Có thể là "{key=value}" wrapped do form submit → strip wrapper
      Logger.log('parseBody_: JSON.parse failed, treating as raw: ' + err);
    }
  }
  return { _raw: raw, _isJson: false };
}

function doPost(e) {
  const params = e ? (e.parameter || {}) : {};
  const action = params.action || '';

  try {
    if (action === 'uploadCsv') {
      const body = parseBody_(e);
      const csv = body._isJson === false ? body._raw : '';
      // Hoặc nếu JSON có field 'csv'
      const csvText = body.csv || csv || '';
      const result = importCsv(csvText);
      return jsonOutput(result);
    }
    if (action === 'updateResult') {
      const body = parseBody_(e);
      const result = updateResult(body.match_id, body.home_score, body.away_score, body.match_name);
      return jsonOutput(result);
    }
    if (action === 'recalcMatch') {
      // Recalc settled + summary cho 1 match cụ thể (theo match_name).
      // Body: { match_name, match_id? } — nếu không có scores thì đọc từ Results sheet.
      const body = parseBody_(e);
      const result = recalcMatchByName(body.match_name, body.match_id);
      return jsonOutput(result);
    }
    if (action === 'recalcAll') {
      // Chạy lại settlePicks toàn cục (escape hatch khi data lệch).
      const result = settlePicks();
      return jsonOutput(result);
    }
    if (action === 'settle') {
      const result = settlePicks();
      return jsonOutput(result);
    }
    return jsonOutput({ error: 'Unknown action: ' + action });
  } catch (err) {
    return jsonOutput({ error: err.toString() });
  }
}

// ─── Upload CSV → Picks sheet ────────────────────────────────────────────────
function importCsv(csvText) {
  const rows = Utilities.parseCsv(csvText, '\t');       // tab-separated
  if (rows.length && rows[0][0] === 'person') rows.shift();

  const sheet = SPREADSHEET.getSheetByName(SHEET_PICKS);
  let inserted = 0;
  const ts = new Date().toISOString();

  for (const row of rows) {
    const person    = (row[0] || '').trim();
    const match     = normalizeMatchName_((row[1] || '').trim());
    const selection = (row[2] || '').trim();
    const stake     = parseFloat((row[3] || '').replace(/[^0-9.]/g, ''));
    const status    = (row[4] || 'Active').trim();

    if (!person || !match || isNaN(stake)) continue;

    const parsed = parseSelection(selection, match);

    const pickId = 'p' + (Date.now().toString(36) + Math.random().toString(36).slice(2, 6));
    // Correct score: prepend "'" để Google Sheets không tự parse thành Date
    let selVal = parsed.selection_val;
    if (parsed.bet_type === 'correct_score' && selVal && !selVal.startsWith("'")) {
      selVal = "'" + selVal;
    }
    sheet.appendRow([
      pickId, ts, person, match,
      parsed.bet_type, selVal, parsed.line, parsed.odds,
      stake, status, 'upload'
    ]);
    inserted++;
  }

  // Ép cột F (selection) thành plain text để tránh auto-parse Date lần sau
  ensureSelectionColumnIsText_(sheet);
}

function ensureSelectionColumnIsText_(sheet) {
  // Dùng full column (không giới hạn lastRow) để format áp dụng cho cả row mới
  // thêm sau bằng appendRow. Nếu chỉ set trên data range, các row mới sẽ giữ
  // format mặc định (Date auto-detect) → "2-1" bị Sheets tự parse thành ngày.
  // Nếu column đã typed (Date) từ lần ghi trước → setNumberFormat throw
  // "can't set the number format of a typed column". Bỏ qua lỗi: data vẫn
  // đúng ("'2-1"), chỉ display format vẫn kiểu Date.
  const colF = sheet.getRange(1, 6, sheet.getMaxRows(), 1);
  try {
    colF.setNumberFormat('@');
  } catch (e) {
    Logger.log('ensureSelectionColumnIsText_: setNumberFormat skipped: ' + e);
  }
}

// ─── Revert CS picks bị Google Sheets tự parse thành Date ───────────────────
// Khi importCsv() prepend "'" vào selection "2-1" trước khi appendRow, Sheets
// vẫn có thể parse thành Date (đặc biệt với data cũ trước khi fix). Hàm này
// scan tất cả CS picks, nếu cell là Date object → convert về "H-A" string
// (dựa trên month/day) rồi set lại với format text.
function revertCorruptedSelections() {
  const sheet = SPREADSHEET.getSheetByName(SHEET_PICKS);
  const data  = sheet.getDataRange().getValues();
  let fixed = 0;
  const fixedDetails = [];

  for (let i = 1; i < data.length; i++) {
    const betType   = data[i][4];
    const selection = data[i][5];
    if (betType !== 'correct_score') continue;
    if (!(selection instanceof Date)) continue;   // chỉ xử lý cell Date

    const month = selection.getMonth() + 1;
    const day   = selection.getDate();
    const restored = month + '-' + day;
    sheet.getRange(i + 1, 6).setValue("'" + restored);  // prepend "'" để giữ text
    fixed++;
    fixedDetails.push(`row ${i + 1}: ${selection.toISOString()} -> ${restored}`);
  }

  if (fixed > 0) {
    ensureSelectionColumnIsText_(sheet);
    fillOddsFromMatches();
  }
  return { success: true, fixed: fixed, details: fixedDetails.slice(0, 20) };
}

// ─── Tương tự cho Settled sheet (col E) ─────────────────────────────────────
// Settled.appendRow() cũng gặp vấn đề parse Date cho CS picks. Hàm này scan
// col E của Settled, nếu cell Date → convert về "H-A" string với format text.
function revertCorruptedSettledSelections() {
  const sheet = SPREADSHEET.getSheetByName(SHEET_SETTLED);
  const data  = sheet.getDataRange().getValues();
  let fixed = 0;
  const fixedDetails = [];

  for (let i = 1; i < data.length; i++) {
    const betType   = data[i][3];
    const selection = data[i][4];
    if (betType !== 'correct_score') continue;
    if (!(selection instanceof Date)) continue;

    const month = selection.getMonth() + 1;
    const day   = selection.getDate();
    const restored = month + '-' + day;
    sheet.getRange(i + 1, 5).setValue("'" + restored);  // col E
    fixed++;
    fixedDetails.push(`row ${i + 1}: ${selection.toISOString()} -> ${restored}`);
  }

  if (fixed > 0) {
    // Cố gắng ép plain text. Nếu column đã typed (Date) mà setValues() trên đã
    // convert sang Date → có thể throw. Bỏ qua lỗi vì data đã được set đúng
    // giá trị ("'2-1"), chỉ là display format vẫn kiểu Date.
    try {
      sheet.getRange(1, 5, sheet.getMaxRows(), 1).setNumberFormat('@');
    } catch (e) {
      Logger.log('revertCorruptedSettledSelections: setNumberFormat skipped: ' + e);
    }
  }
  return { success: true, fixed: fixed, details: fixedDetails.slice(0, 20) };
}

// ─── Parse selection string ───────────────────────────────────────────────────
function parseSelection(raw, match) {
  const s = raw.trim();

  // Correct score: chỉ chứa "<H>-<A>" (vd "2-1") hoặc "<team> <H> - <A> <team>"
  // Ưu tiên detect score thuần trước, fallback về form đầy đủ.
  let csMatch = s.match(/^\s*(\d+)\s*-\s*(\d+)\s*$/);
  if (csMatch) {
    return {
      bet_type: 'correct_score',
      selection_val: csMatch[1] + '-' + csMatch[2],
      line: '',
      odds: ''
    };
  }
  csMatch = s.match(/(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)/);
  if (csMatch) {
    return {
      bet_type: 'correct_score',
      selection_val: csMatch[2] + '-' + csMatch[3],
      line: '',
      odds: ''
    };
  }

  // Over/Under — match cả "Tài 2.5", "tai 2.5", "Over 2.5", "Under 2.5",
  // "Tài/Xỉu 2.5", "Trên 2.5", "Dưới 2.5", "Over 5 điểm", "Xỉu 2.5 trái"
  // và cả "Over"/"Under"/"Tài"/"Xỉu" đứng một mình (line rỗng, để trống cho user cập nhật).
  const ouMatch = s.match(/(tai|tài|over|trên|tren|xiu|xỉu|under|dưới|duoi)\s*(?:[/\\]\s*(?:tai|tài|over|trên|tren|xiu|xỉu|under|dưới|duoi))?\s*([\d.]+)?/i);
  if (ouMatch) {
    const head = String(ouMatch[1] || '').toLowerCase();
    const isOver = /^(tai|tài|over|trên|tren)/.test(head);
    return {
      bet_type: 'over_under',
      selection_val: isOver ? 'over' : 'under',
      line: ouMatch[2] || '',
      odds: ''
    };
  }

  // Handicap: <team> +-<number>
  const hdpMatch = s.match(/(.+?)\s+([+\-][\d.]+)/);
  if (hdpMatch) {
    const team  = hdpMatch[1].trim();
    const line  = parseFloat(hdpMatch[2]);
    const parts = match.split(/\s*-\s*/);
    const home  = parts[0] ? parts[0].trim() : '';
    const away  = parts[1] ? parts[1].trim() : '';
    const homeLow = home.toLowerCase();
    const awayLow = away.toLowerCase();
    const teamLow = team.toLowerCase();
    const isHome = homeLow.includes(teamLow) || teamLow.includes(homeLow);
    const isAway = !isHome && (awayLow.includes(teamLow) || teamLow.includes(awayLow));
    // Ghi tên đội thật (ưu tiên team trong selection nếu khớp, fallback về home/away)
    let selTeam = '';
    if (isHome) selTeam = home;
    else if (isAway) selTeam = away;
    else selTeam = team;
    return {
      bet_type: 'handicap',
      selection_val: selTeam,
      line: String(line),
      odds: ''
    };
  }

  // Handicap không kèm line: chỉ chọn tên đội thắng (vd "Paraguay" trong "Đức - Paraguay")
  const parts = match.split(/\s*-\s*/);
  if (parts.length === 2) {
    const home = parts[0].trim();
    const away = parts[1].trim();
    const sLow = s.toLowerCase();
    const homeLow = home.toLowerCase();
    const awayLow = away.toLowerCase();
    if (sLow === homeLow || sLow.includes(homeLow) || homeLow.includes(sLow)) {
      return { bet_type: 'handicap', selection_val: home, line: '', odds: '' };
    }
    if (sLow === awayLow || sLow.includes(awayLow) || awayLow.includes(sLow)) {
      return { bet_type: 'handicap', selection_val: away, line: '', odds: '' };
    }
  }

  return { bet_type: 'unknown', selection_val: s, line: '', odds: '' };
}

// ─── Fill odds + line từ matches data (lookup bằng match name) ───────────────
function fillOddsFromMatches() {
  const matchesJson = PropertiesService.getScriptProperties().getProperty('MATCHES_CACHE');
  if (!matchesJson) return { error: 'MATCHES_CACHE chưa được set. Chạy refreshMatchCache() trước.' };

  const matches = JSON.parse(matchesJson);
  const sheet   = SPREADSHEET.getSheetByName(SHEET_PICKS);
  const data    = sheet.getDataRange().getValues();

  let filledOdds = 0, filledLine = 0;

  for (let i = 1; i < data.length; i++) {
    const row          = data[i];
    const matchName    = row[3];
    const betType      = row[4];
    const selection    = String(row[5] || '').replace(/^'/, '');  // strip leading '
    const existingOdds = row[7];
    const existingLine = row[6];

    const m = findMatch(matches, matchName);
    if (!m || !m.odds) continue;

    // 1) FILL LINE nếu rỗng (correct_score không cần line — đã có trong selection)
    if (!existingLine && betType !== 'correct_score') {
      let newLine = '';
      if (betType === 'handicap' && m.odds.handicap) {
        newLine = m.odds.handicap.instantHandicap || '';
      } else if (betType === 'over_under' && m.odds.overUnder) {
        newLine = m.odds.overUnder.instantHandicap || '';
      }
      if (newLine) {
        sheet.getRange(i + 1, 7).setValue(newLine);  // col G
        filledLine++;
      }
    }

    // 2) FILL ODDS nếu rỗng
    if (!existingOdds) {
      let odds = '';
      const curLine = !existingLine ? (betType === 'handicap' ? (m.odds.handicap || {}).instantHandicap
                                       : (m.odds.overUnder || {}).instantHandicap) : existingLine;
      if (betType === 'correct_score') {
        // m.cs[] format thực tế: "H:A:odds" (vd "2:1:8.2"), selection = "H-A"
        const csList = m.cs || [];
        const selClean = selection.replace(/^'/, '');
        const [hStr, aStr] = selClean.split('-');
        const found = csList.find(function(s) {
          const parts = s.split(':');
          return parts[0] === hStr && parts[1] === aStr;
        });
        if (found) {
          const parts = found.split(':');
          odds = parts[2] || '';
        }
      } else if (betType === 'handicap') {
        const hc = m.odds.handicap || {};
        // So sánh selection với home/away name để chọn odds
        const selLow = selection.toLowerCase();
        const homeLow = (m.home || '').toLowerCase();
        const awayLow = (m.away || '').toLowerCase();
        if (selLow === homeLow || selLow.includes(homeLow) || homeLow.includes(selLow)) {
          odds = hc.instantHome || '';
        } else if (selLow === awayLow || selLow.includes(awayLow) || awayLow.includes(selLow)) {
          odds = hc.instantAway || '';
        } else {
          // Fallback: 'home'/'away' legacy
          if (selection === 'home') odds = hc.instantHome || '';
          else if (selection === 'away') odds = hc.instantAway || '';
        }
      } else if (betType === 'over_under') {
        const ou = m.odds.overUnder || {};
        const selLow = selection.toLowerCase();
        if (selLow === 'over' || selLow === 'tai' || selLow === 'tài' || selLow === 'trên') {
          odds = ou.instantOver || '';
        } else if (selLow === 'under' || selLow === 'xiu' || selLow === 'xỉu' || selLow === 'dưới') {
          odds = ou.instantUnder || '';
        }
      }

      if (odds) {
        sheet.getRange(i + 1, 8).setValue(odds);  // col H
        filledOdds++;
      }
    }
  }

  return { success: true, filledOdds: filledOdds, filledLine: filledLine };
}

// Map tên tiếng Việt → tên gốc (EN) cho các đội có phiên dịch khác xa giữa
// tên trong sheet (do user nhập tay, có thể là "Ma Rốc") và tên trong
// cache matches.json (vd "Morocco"). Dùng để findMatch() robust.
const TEAM_ALIAS_VI_TO_EN = {
  'ma rốc': 'morocco',
  'bờ biển ngà': 'côte d\'ivoire',
  'ivory coast': 'côte d\'ivoire',
  'cô-oét': 'kuwait',
  'hàn quốc': 'south korea',
  'triều tiên': 'north korea',
  'trung quốc': 'china',
  'ả rập xê-út': 'saudi arabia',
  'ả rập saudi': 'saudi arabia',
  'séc': 'czechia',
  'séc rep': 'czechia',
  'mỹ': 'usa',
  'anh': 'england',
  'tây ban nha': 'spain',
  'bồ đào nha': 'portugal',
  'đức': 'germany',
  'pháp': 'france',
  'ý': 'italy',
  'hà lan': 'netherlands',
  'bỉ': 'belgium',
  'thụy sĩ': 'switzerland',
  'thụy điển': 'sweden',
  'na uy': 'norway',
  'đan mạch': 'denmark',
  'brazil': 'brazil',
  'mexico': 'mexico',
  'ecuador': 'ecuador',
  'paraguay': 'paraguay',
  'nhật bản': 'japan',
  'hàn quốc': 'south korea',
  'nam phi': 'south africa',
  'canada': 'canada',
  'senegal': 'senegal',
  'haiti': 'haiti'
};

function viToEn(s) {
  // Normalize toàn bộ string: tìm & replace từng alias trong input.
  // Cần thiết vì "Hà Lan - Ma Rốc" phải map về "netherlands - morocco".
  let k = String(s || '').trim().toLowerCase();
  // Thử exact match trước (cho "ma rốc" toàn string)
  if (TEAM_ALIAS_VI_TO_EN[k]) return TEAM_ALIAS_VI_TO_EN[k];
  // Fallback: replace substring (cho "hà lan - ma rốc" → "netherlands - morocco")
  for (const vi in TEAM_ALIAS_VI_TO_EN) {
    if (vi && k.indexOf(vi) !== -1) {
      k = k.split(vi).join(TEAM_ALIAS_VI_TO_EN[vi]);
    }
  }
  return k;
}

// ─── Build index lookup: nhiều key (VI/EN/normalized) → match ───────────────
// Thay vì substring match từng trận (chậm + dễ sai Unicode), build 1 map
// {key → match} với các key sinh ra từ mỗi trận. findMatch() tra O(1) trước,
// fallback substring match nếu miss.
function buildMatchIndex_(matches) {
  const idx = {};
  for (const m of (matches || [])) {
    const home = m.home || m.homeName || '';
    const away = m.away || m.awayName || '';
    if (!home || !away) continue;
    const hLow = home.toLowerCase().trim();
    const aLow = away.toLowerCase().trim();
    const hEn  = viToEn(home);
    const aEn  = viToEn(away);
    // Key variants — match cả VI thường, EN thường, và VI→EN
    const keys = [
      `${hLow} - ${aLow}`,
      `${hEn} - ${aEn}`,
      `${hLow}-${aLow}`,
      `${hEn}-${aEn}`,
      `${hLow}|${aLow}`,
      `${hEn}|${aEn}`,
      // Home/Away swap (đề phòng user ghi ngược)
      `${aLow} - ${hLow}`,
      `${aEn} - ${hEn}`,
      `${aLow}-${hLow}`,
      `${aEn}-${hEn}`,
    ];
    for (const k of keys) {
      if (k && !(k in idx)) idx[k] = m;
    }
  }
  return idx;
}

function findMatch(matches, name) {
  if (!name) return null;
  const n = String(name).trim().toLowerCase();
  // 1) Exact match trên index
  const idx = buildMatchIndex_(matches);
  if (idx[n]) return idx[n];
  // 2) Normalize separator: " vs " / " v " → " - "
  const normalized = n.replace(/\s+vs\.?\s+/g, ' - ').replace(/\s+v\s+/g, ' - ');
  if (idx[normalized]) return idx[normalized];
  // 3) Fallback: substring match (giữ logic cũ cho edge case)
  const parts = normalized.split(/\s*-\s*/);
  const a = parts[0] || '';
  const b = parts[1] || '';
  const aEn = viToEn(a);
  const bEn = viToEn(b);
  for (const m of (matches || [])) {
    const hn = (m.home || '').toLowerCase();
    const an = (m.away || '').toLowerCase();
    if (normalized.includes(hn) && normalized.includes(an)) return m;
    const aInHN = hn.includes(a) || a.includes(hn) || hn.includes(aEn) || aEn.includes(hn);
    const bInAN = an.includes(b) || b.includes(an) || an.includes(bEn) || bEn.includes(an);
    const aInAN = an.includes(a) || a.includes(an) || an.includes(aEn) || aEn.includes(an);
    const bInHN = hn.includes(b) || b.includes(hn) || hn.includes(bEn) || bEn.includes(hn);
    if ((aInHN && bInAN) || (aInAN && bInHN)) return m;
  }
  return null;
}

// ─── Re-classify picks 'unknown' có selection trùng tên đội → handicap ──────
function reclassifyUnknownPicks() {
  const sheet = SPREADSHEET.getSheetByName(SHEET_PICKS);
  const data  = sheet.getDataRange().getValues();
  let fixed = 0;
  for (let i = 1; i < data.length; i++) {
    const betType = data[i][4];
    if (betType !== 'unknown') continue;
    const match     = data[i][3];
    const selection = data[i][5];
    const parsed    = parseSelection(selection, match);
    if (parsed.bet_type !== 'unknown') {
      sheet.getRange(i + 1, 5).setValue(parsed.bet_type);   // col E: bet_type
      sheet.getRange(i + 1, 6).setValue(parsed.selection_val); // col F: selection
      fixed++;
    }
  }
  if (fixed > 0) {
    fillOddsFromMatches();
    ensureSelectionColumnIsText_(sheet);
  }
  return { success: true, fixed: fixed };
}

// ─── Chuẩn hóa match name về dạng "Home - Away" ────────────────────────────
// Mọi nơi ghi match name vào Sheets (Results/Picks/Settled) phải dùng hàm này
// để đảm bảo separator thống nhất là " - ". Nếu không, join giữa các sheet
// dùng viToEn("south africa vs canada") vs viToEn("south africa - canada")
// sẽ ra 2 key khác nhau → settle fail.
function normalizeMatchName_(name) {
  if (!name) return '';
  // Replace " vs ", " VS ", "v " (1 chữ cái) → " - "
  // Lưu ý: KHÔNG động vào "-" đã có
  return String(name)
    .replace(/\s+vs\.?\s+/gi, ' - ')     // " vs ", " vs. "
    .replace(/\s+v\s+/gi, ' - ')         // " v " (ít gặp)
    .replace(/\s+VS\s+/g, ' - ')         // " VS " (uppercase)
    .trim();
}

// ─── Fill odds cho correct_score picks (lookup từ m.cs[]) ────────────────────
function fillCorrectScoreOddsOnly() {
  const matchesJson = PropertiesService.getScriptProperties().getProperty('MATCHES_CACHE');
  if (!matchesJson) return { error: 'MATCHES_CACHE chưa được set. Chạy refreshMatchCache() trước.' };

  const matches = JSON.parse(matchesJson);
  const cacheInfo = {
    isArray: Array.isArray(matches),
    total: Array.isArray(matches) ? matches.length : (matches.matches ? matches.matches.length : 0),
    sample: Array.isArray(matches) && matches.length > 0 ? matches[0].home + ' vs ' + matches[0].away : 'N/A'
  };

  const sheet   = SPREADSHEET.getSheetByName(SHEET_PICKS);
  const data    = sheet.getDataRange().getValues();

  let filled = 0;
  let missing = 0;
  const missingDetails = [];

  for (let i = 1; i < data.length; i++) {
    const betType      = data[i][4];
    const selection    = String(data[i][5] || '').replace(/^'/, '');  // strip leading '
    const matchName    = data[i][3];
    const existingOdds = data[i][7];

    if (betType !== 'correct_score') continue;
    if (existingOdds) continue;  // đã có odds → skip

    const m = findMatch(matches, matchName);
    if (!m) { missing++; missingDetails.push(`${matchName} | ${selection} (no match)`); continue; }

    const csList = m.cs || [];
    // m.cs[] format thực tế: "H:A:odds" (vd "2:1:8.2" = tỷ số 2-1, odds 8.2)
    // selection dạng "H-A" (vd "2-1")
    const [hStr, aStr] = selection.split('-');
    const found = csList.find(function(s) {
      const parts = s.split(':');
      return parts[0] === hStr && parts[1] === aStr;
    });
    if (found) {
      const parts = found.split(':');
      // parts = [H, A, odds]
      const odds = parts[2] || '';
      if (odds) {
        sheet.getRange(i + 1, 8).setValue(odds);
        filled++;
      } else {
        missing++;
        missingDetails.push(`${matchName} | ${selection} (no odds in ${found})`);
      }
    } else {
      missing++;
      missingDetails.push(`${matchName} | ${selection} (not in cs list)`);
    }
  }

  return {
    success: true,
    cache: cacheInfo,
    filled: filled,
    missing: missing,
    missingDetails: missingDetails.slice(0, 20)
  };
}

// ─── Update match result ──────────────────────────────────────────────────────
function updateResult(matchId, homeScore, awayScore, matchName) {
  Logger.log('updateResult: START matchId=' + matchId + ' home=' + homeScore + ' away=' + awayScore + ' matchName=' + matchName);
  // Nếu matchName rỗng → auto-resolve từ MATCHES_CACHE theo matchId.
  // Picks sheet KHÔNG có match_id (chỉ có tên trận), nên settlePicks() phụ thuộc
  // vào match_name để join. Thiếu match_name → settle ra 0 row.
  if (!matchName || String(matchName).trim() === '') {
    const resolved = resolveMatchNameFromCache_(matchId);
    if (resolved) {
      matchName = resolved;
    }
    Logger.log('updateResult: resolved matchName from cache: ' + matchName);
  }

  // Defensive: nếu vẫn rỗng (không có matchId hoặc cache miss) → KHÔNG settle,
  // chỉ ghi tỷ số vào Results để user nhập tay sau. Tránh lỗi "match_name rỗng"
  // phá vỡ luồng và gây mất data.
  if (!matchName || String(matchName).trim() === '') {
    Logger.log('updateResult: matchName vẫn rỗng sau resolve — bỏ qua settle, chỉ ghi Results');
    return {
      success: true,
      match_id: matchId,
      match_name: '',
      settled: 0,
      note: 'Đã ghi Results nhưng không có match_name để settle (matchId không có trong MATCHES_CACHE).'
    };
  }

  ensureResultsHeader_();

  // Chuẩn hóa matchName về dạng "Home - Away" trước khi ghi Sheets
  matchName = normalizeMatchName_(matchName);

  const sheet = SPREADSHEET.getSheetByName(SHEET_RESULTS);
  const data  = sheet.getDataRange().getValues();

  let found = false;
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][0]) === String(matchId)) {
      sheet.getRange(i + 1, 2).setValue(matchName);  // col B: match name (đã chuẩn hóa)
      sheet.getRange(i + 1, 3).setValue(homeScore);
      sheet.getRange(i + 1, 4).setValue(awayScore);
      sheet.getRange(i + 1, 5).setValue(new Date().toISOString());
      found = true;
      break;
    }
  }
  if (!found) {
    sheet.appendRow([String(matchId), matchName, homeScore, awayScore, new Date().toISOString()]);
    Logger.log('updateResult: appended new row to Results');
  } else {
    Logger.log('updateResult: updated existing row in Results');
  }

  // Wrap settle trong try-catch để tránh throw giữa chừng làm hỏng data.
  // Gọi recalcMatchByName thay vì settlePicks() toàn cục → chỉ re-settle
  // picks của match này, không clear/rewrite toàn bộ Settled + Summary.
  var settleResult;
  try {
    settleResult = recalcMatchByName(matchName, matchId);
    Logger.log('updateResult: recalcMatchByName result: ' + JSON.stringify(settleResult));
  } catch (e) {
    Logger.log('updateResult: recalcMatchByName FAILED: ' + e);
    return { success: false, error: 'recalcMatchByName failed: ' + e.toString(), match_id: matchId, match_name: matchName };
  }
  return { success: true, match_id: matchId, match_name: matchName, settled: settleResult.settled };
}

// Results sheet phải có header row cứng. Nếu sheet rỗng hoặc row 1 là data
// (lần đầu dùng trước khi có hàm này), readSheet() sẽ đọc sai key và settle
// join không bao giờ khớp.
function ensureResultsHeader_() {
  const sheet = SPREADSHEET.getSheetByName(SHEET_RESULTS);
  const header = ['match_id', 'match', 'home_score', 'away_score', 'updated_at'];
  const data = sheet.getDataRange().getValues();
  if (data.length === 0 || String(data[0][0]).toLowerCase() !== 'match_id') {
    if (data.length === 0) {
      sheet.appendRow(header);
    } else {
      sheet.insertRowBefore(1);
      sheet.getRange(1, 1, 1, header.length).setValues([header]);
    }
  }
}

// Tra tên trận "Home - Away" từ MATCHES_CACHE theo matchId.
// Trả về '' nếu không có cache hoặc không tìm thấy.
function resolveMatchNameFromCache_(matchId) {
  var cache = PropertiesService.getScriptProperties().getProperty('MATCHES_CACHE');
  if (!cache) return '';
  try {
    var matches = JSON.parse(cache);
    for (var i = 0; i < matches.length; i++) {
      if (String(matches[i].id) === String(matchId)) {
        var h = matches[i].home || matches[i].homeName || '';
        var a = matches[i].away || matches[i].awayName || '';
        if (h || a) return (h + ' - ' + a).trim();
        break;
      }
    }
  } catch (e) { /* ignore */ }
  return '';
}

// ─── Settlement logic ─────────────────────────────────────────────────────────
function settlePicks() {
  const picks   = readSheet(SHEET_PICKS);
  Logger.log('DEBUG settlePicks: picks count=' + picks.length);
  if (picks.length > 0) {
    Logger.log('DEBUG settlePicks: first pick keys=' + Object.keys(picks[0]).join(','));
    Logger.log('DEBUG settlePicks: first pick match=' + picks[0].match);
  }

  // Đọc Results bằng column index để tránh phụ thuộc header row.
  // readSheet() dùng row 1 làm key names → nếu Results chưa có header cứng,
  // key sẽ là giá trị data (rỗng, số, ...) → join fail toàn bộ.
  // Column layout: A=match_id, B=match, C=home_score, D=away_score, E=updated_at
  ensureResultsHeader_();
  const resultsSheet    = SPREADSHEET.getSheetByName(SHEET_RESULTS);
  const resultsRaw      = resultsSheet.getDataRange().getValues();
  const resultsHeader   = resultsRaw.length > 0 ? String(resultsRaw[0][0]).toLowerCase().trim() : '';
  const resultsStartRow = (resultsHeader === 'match_id') ? 1 : 0;

  const resultByName = {};
  const resultById   = {};
  for (let i = resultsStartRow; i < resultsRaw.length; i++) {
    const row   = resultsRaw[i];
    const _id   = String(row[0] || '').trim();
    const _name = String(row[1] || '').trim();
    const r     = { match_id: _id, match: _name, home_score: row[2], away_score: row[3] };
    if (_name) resultByName[viToEn(_name).trim().toLowerCase()] = r;
    if (_id)   resultById[_id] = r;
  }
  Logger.log('DEBUG settlePicks: resultsStartRow=' + resultsStartRow + ' resultsRaw.length=' + resultsRaw.length);
  Logger.log('DEBUG settlePicks: resultByName keys=' + Object.keys(resultByName).join('|'));

  const settled = SPREADSHEET.getSheetByName(SHEET_SETTLED);
  const summary = SPREADSHEET.getSheetByName(SHEET_SUMMARY);

  // Xóa sạch sheet bằng clear() (xóa cả content lẫn formatting cũ) rồi ghi atomic
  // toàn bộ data trong 1 lần setValues. Tránh deleteRows/insertRowBefore/appendRow
  // vì sequence đó dễ tạo phantom row khi sheet rỗng, khiến header bị đẩy lệch.
  settled.clear();
  summary.clear();

  const settledHeader = ['pick_id', 'person', 'match', 'bet_type', 'selection', 'stake', 'odds', 'result', 'profit'];
  const summaryHeader = ['person', 'total_stake', 'total_profit', 'win_count', 'lose_count'];

  const personStats = {};
  const settledData = [settledHeader];

  for (const p of picks) {
    if (p.status === 'Cancelled') continue;

    // Ưu tiên lookup theo match name (picks chỉ có tên); fallback theo match_id.
    // Dùng viToEn() để normalize "Ma Rốc" ↔ "Morocco" (picks user gõ VN ↔ results từ crawler EN).
    const key = viToEn(p.match || '').trim().toLowerCase();
    let res = resultByName[key];
    if (!res && p.match_id) res = resultById[String(p.match_id)];
    if (!res) {
      Logger.log('DEBUG settlePicks: SKIP pick match="' + p.match + '" key="' + key + '" (no result)');
      continue;
    }

    const outcome = calculateProfit(p, res);

    Logger.log('DEBUG settlePicks: MATCH pick="' + p.match + '" → result home=' + res.home_score + ' away=' + res.away_score + ' outcome=' + outcome.result);

    // CS picks: prepend "'" để Sheets giữ string thay vì parse thành Date
    let selVal = String(p.selection || '');
    if (p.bet_type === 'correct_score' && selVal && !selVal.startsWith("'")) {
      selVal = "'" + selVal;
    }

    settledData.push([
      p.pick_id, p.person, p.match, p.bet_type, selVal,
      p.stake, p.odds, outcome.result, outcome.profit
    ]);

    if (!personStats[p.person]) {
      personStats[p.person] = { total_stake: 0, total_profit: 0, win: 0, lose: 0 };
    }
    personStats[p.person].total_stake += parseFloat(p.stake) || 0;
    personStats[p.person].total_profit += outcome.profit;
    if (outcome.result === 'win') personStats[p.person].win++;
    else if (outcome.result === 'lose') personStats[p.person].lose++;
  }

  Logger.log('DEBUG settlePicks: settledData will have ' + settledData.length + ' rows after loop (incl. header)');

  const summaryData = [summaryHeader];
  for (const [name, s] of Object.entries(personStats)) {
    summaryData.push([name, s.total_stake, s.total_profit, s.win, s.lose]);
  }

  // Ghi atomic toàn bộ data (header + rows)
  try {
    settled.getRange(1, 1, settledData.length, settledHeader.length).setValues(settledData);
    summary.getRange(1, 1, summaryData.length, summaryHeader.length).setValues(summaryData);
    Logger.log('DEBUG settlePicks: setValues OK settled=' + (settledData.length - 1) + ' summary=' + (summaryData.length - 1));
  } catch (e) {
    Logger.log('DEBUG settlePicks: setValues FAILED: ' + e);
    throw e;
  }

  return { success: true, settled: Math.max(0, settledData.length - 1) };
}

// ─── Tối ưu: recalc 1 match thay vì toàn bộ Settled + Summary ────────────────
// Trước đây updateResult gọi settlePicks() chạy lại toàn bộ 150 picks + clear
// + rewrite 2 sheet. Nếu throw giữa chừng sẽ mất sạch data. Hàm này chỉ đụng
// vào rows của matchName, giữ nguyên các match khác, và update Summary bằng
// cách đọc lại toàn bộ Settled (rẻ hơn nhiều so với clear+rewrite toàn bộ).
function recalcMatchByName(matchName, matchId) {
  // Fallback: nếu matchName rỗng nhưng có matchId → resolve từ MATCHES_CACHE
  if (!matchName || String(matchName).trim() === '') {
    if (matchId) {
      const resolved = resolveMatchNameFromCache_(matchId);
      Logger.log('recalcMatchByName: matchName rỗng, resolved from cache: ' + resolved);
      if (resolved) {
        matchName = resolved;
      } else {
        return { success: false, error: 'match_name rỗng và không resolve được từ matchId=' + matchId };
      }
    } else {
      return { success: false, error: 'match_name rỗng' };
    }
  }

  ensureResultsHeader_();

  // 1. Tìm score trong Results sheet theo matchId hoặc matchName
  const resultsSheet = SPREADSHEET.getSheetByName(SHEET_RESULTS);
  const resultsRaw   = resultsSheet.getDataRange().getValues();
  const resultsHdr   = resultsRaw.length > 0 ? String(resultsRaw[0][0]).toLowerCase().trim() : '';
  const resultsStart = (resultsHdr === 'match_id') ? 1 : 0;

  const resultByName = {};
  const resultById   = {};
  for (let i = resultsStart; i < resultsRaw.length; i++) {
    const row   = resultsRaw[i];
    const _id   = String(row[0] || '').trim();
    const _name = String(row[1] || '').trim();
    const r     = { match_id: _id, match: _name, home_score: row[2], away_score: row[3] };
    if (_name) resultByName[viToEn(_name).trim().toLowerCase()] = r;
    if (_id)   resultById[_id] = r;
  }

  const targetKey = viToEn(matchName).trim().toLowerCase();
  let res = resultByName[targetKey];
  if (!res && matchId) res = resultById[String(matchId)];
  if (!res) {
    return { success: false, error: 'Không tìm thấy tỷ số trong Results sheet cho match: ' + matchName, match_name: matchName };
  }

  // 2. Lấy picks của match này
  // targetKey là viToEn(matchName).trim().toLowerCase() — vd "spain - austria"
  // p.match có thể là "Tây Ban Nha - Áo" (sẽ được viToEn → "spain - austria")
  // HOẶC có thể khác format (vd Results ghi "vs", Picks ghi "-") → viToEn normalize.
  // Nếu exact match fail, fallback tìm theo cả 2 phần home/away riêng lẻ.
  // QUAN TRỌNG: split separator phải bao gồm CẢ " - " LẪN " vs " vì Results sheet
  // dùng "vs" trong khi Picks sheet dùng "-". targetKey = "south africa vs canada"
  // → split(/\s+vs\s+|\s+-\s+/) → ["south africa", "canada"].
  const allPicks = readSheet(SHEET_PICKS);
  const targetParts = targetKey.split(/\s+vs\s+|\s+-\s+|\s+v\s+/i);
  const targetHome = targetParts[0] || '';
  const targetAway = targetParts[1] || '';

  const matchPicks = allPicks.filter(p => {
    const k = viToEn(p.match || '').trim().toLowerCase();
    if (k === targetKey) return true;
    // Fallback: p.match có thể chỉ chứa 1 phần (vd "Tây Ban Nha" thay vì "Tây Ban Nha - Áo")
    // hoặc có thêm text khác. Check xem cả home lẫn away có trong p.match không.
    if (targetHome && targetAway && k.includes(targetHome) && k.includes(targetAway)) {
      return true;
    }
    return false;
  });
  Logger.log('recalcMatchByName: ' + matchName + ' → ' + matchPicks.length + ' picks');

  if (matchPicks.length === 0) {
    return { success: true, settled: 0, note: 'Không có pick nào cho trận này', match_name: matchName };
  }

  // 3. Tính outcome cho từng pick
  const newSettledRows = [];
  for (const p of matchPicks) {
    if (p.status === 'Cancelled') continue;
    const outcome = calculateProfit(p, res);
    let selVal = String(p.selection || '');
    if (p.bet_type === 'correct_score' && selVal && !selVal.startsWith("'")) {
      selVal = "'" + selVal;
    }
    newSettledRows.push([
      p.pick_id, p.person, normalizeMatchName_(p.match), p.bet_type, selVal,
      p.stake, p.odds, outcome.result, outcome.profit
    ]);
  }

  // 4. Update Settled sheet: xóa rows cũ của match, append rows mới (giữ rows match khác)
  const settled = SPREADSHEET.getSheetByName(SHEET_SETTLED);
  const settledHeader = ['pick_id', 'person', 'match', 'bet_type', 'selection', 'stake', 'odds', 'result', 'profit'];

  // Đọc Settled hiện tại (raw values) — match column index để xóa chính xác
  const settledRaw = settled.getDataRange().getValues();
  const settledHdr = settledRaw.length > 0 ? String(settledRaw[0][0]).toLowerCase().trim() : '';
  const settledStart = (settledHdr === 'pick_id') ? 1 : 0;

  // Tìm rows cần xóa (theo viToEn() normalized để robust với naming khác nhau)
  const rowsToDelete = [];
  for (let i = settledStart; i < settledRaw.length; i++) {
    const rowMatchName = String(settledRaw[i][2] || '').trim();
    const rowKey = viToEn(rowMatchName).trim().toLowerCase();
    if (rowKey === targetKey) {
      rowsToDelete.push(i + 1); // sheet row = 1-indexed
    } else if (targetHome && targetAway && rowKey.includes(targetHome) && rowKey.includes(targetAway)) {
      rowsToDelete.push(i + 1);
    }
  }
  // Xóa từ dưới lên để index không lệch
  for (let i = rowsToDelete.length - 1; i >= 0; i--) {
    settled.deleteRow(rowsToDelete[i]);
  }

  // Append rows mới (nếu có)
  if (newSettledRows.length > 0) {
    const lastRow = settled.getLastRow();
    settled.getRange(lastRow + 1, 1, newSettledRows.length, settledHeader.length).setValues(newSettledRows);
  }

  // 5. Rebuild Summary từ Settled sheet (đọc lại rẻ hơn rewrite toàn bộ từ picks)
  const summary = SPREADSHEET.getSheetByName(SHEET_SUMMARY);
  const summaryHeader = ['person', 'total_stake', 'total_profit', 'win_count', 'lose_count'];
  const personStats = {};

  const settledAfterRaw = settled.getDataRange().getValues();
  const sStart = (settledAfterRaw.length > 0 && String(settledAfterRaw[0][0]).toLowerCase().trim() === 'pick_id') ? 1 : 0;
  for (let i = sStart; i < settledAfterRaw.length; i++) {
    const r = settledAfterRaw[i];
    const person = String(r[1] || '').trim();
    if (!person) continue;
    const stake  = parseFloat(r[5]) || 0;
    const profit = parseFloat(r[8]) || 0;
    const result = String(r[7] || '').toLowerCase();
    if (!personStats[person]) {
      personStats[person] = { total_stake: 0, total_profit: 0, win: 0, lose: 0 };
    }
    personStats[person].total_stake  += stake;
    personStats[person].total_profit += profit;
    if (result === 'win')       personStats[person].win++;
    else if (result === 'lose') personStats[person].lose++;
  }

  // Ghi Summary: clear + setValues (Summary nhỏ, rẻ)
  const summaryData = [summaryHeader];
  for (const [name, s] of Object.entries(personStats)) {
    summaryData.push([name, s.total_stake, s.total_profit, s.win, s.lose]);
  }
  summary.clear();
  summary.getRange(1, 1, summaryData.length, summaryHeader.length).setValues(summaryData);

  Logger.log('DEBUG recalcMatchByName: done — settled_rows=' + newSettledRows.length + ' summary_persons=' + summaryData.length);
  return { success: true, settled: newSettledRows.length, match_name: matchName, score: res.home_score + '-' + res.away_score };
}

function calculateProfit(pick, result) {
  const stake = parseFloat(pick.stake) || 0;
  const odds  = parseFloat(pick.odds)  || 0;
  const home  = parseInt(result.home_score, 10);
  const away  = parseInt(result.away_score, 10);
  const line  = parseFloat(pick.line)  || 0;
  const type  = pick.bet_type;
  const sel   = pick.selection;

  if (type === 'correct_score') {
    const parts = sel.split('-');
    if (parts.length === 2 && parseInt(parts[0]) === home && parseInt(parts[1]) === away) {
      return { result: 'win', profit: stake * odds };
    }
    return { result: 'lose', profit: -stake };
  }

  if (type === 'handicap') {
    const margin = (sel === 'home') ? (home - away + line) : (away - home + line);
    const outcome = halfBallOutcome(margin);
    if (outcome === 'win')       return { result: 'win',  profit: stake * odds };
    if (outcome === 'half_win')  return { result: 'win',  profit: stake * odds / 2 };
    if (outcome === 'half_lose') return { result: 'lose', profit: -stake / 2 };
    if (outcome === 'lose')      return { result: 'lose', profit: -stake };
    return { result: 'push', profit: 0 };
  }

  if (type === 'over_under') {
    const total = home + away;
    const margin = (sel === 'over') ? (total - line) : (line - total);
    const outcome = halfBallOutcome(margin);
    if (outcome === 'win')       return { result: 'win',  profit: stake * odds };
    if (outcome === 'half_win')  return { result: 'win',  profit: stake * odds / 2 };
    if (outcome === 'half_lose') return { result: 'lose', profit: -stake / 2 };
    if (outcome === 'lose')      return { result: 'lose', profit: -stake };
    return { result: 'push', profit: 0 };
  }

  return { result: 'unknown', profit: 0 };
}

function halfBallOutcome(margin) {
  if (margin > 0)       return 'win';
  if (margin < 0)       return 'lose';
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
    const vals = Object.values(row).filter(function(v) { return v !== '' && v !== undefined && v !== null; });
    if (vals.length > 0) result.push(row);
  }
  return result;
}

// ─── Backfill match_name cho Results rows cũ (chạy 1 lần) ─────────────────
// Tìm match_id trong Results sheet mà col B (match_name) rỗng → lookup tên
// trong MATCHES_CACHE → ghi đè. Cần thiết vì các kết quả ghi trước khi fix
// `updateResult` không có match_name, dẫn đến settlePicks join fail.
function backfillResultNames() {
  const matchesJson = PropertiesService.getScriptProperties().getProperty('MATCHES_CACHE');
  if (!matchesJson) return { error: 'MATCHES_CACHE chưa được set. Chạy refreshMatchCache() trước.' };

  const matches = JSON.parse(matchesJson);
  const byId = {};
  matches.forEach(function(m) { if (m.id) byId[String(m.id)] = m; });

  const sheet = SPREADSHEET.getSheetByName(SHEET_RESULTS);
  const data  = sheet.getDataRange().getValues();

  let filled = 0, missing = 0;
  const missingIds = [];
  for (let i = 1; i < data.length; i++) {
    const matchId   = String(data[i][0] || '').trim();
    const matchName = String(data[i][1] || '').trim();
    if (!matchId || matchName) continue;     // skip empty id hoặc đã có name
    const m = byId[matchId];
    if (m) {
      const name = (m.home || m.homeName || '') + ' - ' + (m.away || m.awayName || '');
      sheet.getRange(i + 1, 2).setValue(name.trim());
      filled++;
    } else {
      missing++;
      missingIds.push(matchId);
    }
  }

  if (filled > 0) settlePicks();
  return { success: true, filled: filled, missing: missing, missingIds: missingIds.slice(0, 20) };
}

// ─── Fix tên trận pick bị user ghi sai (chạy 1 lần) ──────────────────────────
// Trước đây Picks sheet có 2 row ghi:
//   "Anh - Congo"           (thiếu "CHDC")
//   "Mỹ - Bosnia & Herzegovina" (thừa "& Herzegovina")
// Hai tên này không match MATCHES_CACHE nên settle thất bại. Function này
// map về tên chuẩn trong matches.json, rồi trigger settlePicks() lại.
function fixPicksNames() {
  const ALIASES = {
    'anh - congo':              'Anh - CHDC Công gô',
    'anh - chdc congo':         'Anh - CHDC Công gô',
    'anh - chdc công gô':       'Anh - CHDC Công gô',
    'mỹ - bosnia & herzegovina':'Mỹ - Bosnia',
    'mỹ - bosnia and herzegovina':'Mỹ - Bosnia',
    'mỹ - bosnia herzegovina':  'Mỹ - Bosnia',
    'mỹ - bosnia &amp; herzegovina': 'Mỹ - Bosnia',
  };

  const sheet = SPREADSHEET.getSheetByName(SHEET_PICKS);
  const data  = sheet.getDataRange().getValues();
  const fixes = [];

  for (let i = 1; i < data.length; i++) {
    const raw = String(data[i][3] || '').trim();   // col D = match name
    if (!raw) continue;
    const key = raw.toLowerCase();
    if (ALIASES[key]) {
      const target = ALIASES[key];
      sheet.getRange(i + 1, 4).setValue(target);
      fixes.push({ row: i + 1, from: raw, to: target });
    }
  }

  let settle = null;
  if (fixes.length > 0) {
    Logger.log('fixPicksNames applied ' + fixes.length + ' fix(es)');
    settle = settlePicks();
  }
  return { success: true, fixes: fixes, settle: settle };
}

// ─── Refresh match cache từ GitHub (chạy thủ công hoặc trigger) ──────────────
function refreshMatchCache() {
  const url = PropertiesService.getScriptProperties().getProperty('GITHUB_RAW_URL');
  if (!url) {
    Logger.log('GITHUB_RAW_URL chưa được set trong Script Properties');
    return { error: 'GITHUB_RAW_URL chưa được set' };
  }
  const resp = UrlFetchApp.fetch(url);
  PropertiesService.getScriptProperties().setProperty('MATCHES_CACHE', resp.getContentText());
  Logger.log('Cache refreshed: ' + resp.getContentText().length + ' bytes');
  return { success: true, bytes: resp.getContentText().length };
}

// ─── Backfill: chuẩn hóa tất cả match name về "Home - Away" trong 3 sheets ────
// Chạy 1 lần sau khi deploy code mới. Cần thiết vì data cũ có thể ghi "vs"
// (do admin nhập tay hoặc từ crawler cũ). Sau khi chuẩn hóa, gọi settlePicks()
// để rebuild Settled + Summary với match name mới.
function backfillNormalizeMatchNames() {
  const sheets = [
    { name: SHEET_PICKS,   col: 4 },  // D: match
    { name: SHEET_RESULTS, col: 2 },  // B: match
    { name: SHEET_SETTLED, col: 3 },  // C: match
  ];
  const report = [];

  for (const s of sheets) {
    const sh = SPREADSHEET.getSheetByName(s.name);
    if (!sh) { report.push(`${s.name}: sheet không tồn tại`); continue; }
    const data = sh.getDataRange().getValues();
    if (data.length < 2) { report.push(`${s.name}: rỗng`); continue; }

    let fixed = 0;
    for (let i = 1; i < data.length; i++) {
      const old = String(data[i][s.col - 1] || '').trim();
      const norm = normalizeMatchName_(old);
      if (old && norm && old !== norm) {
        sh.getRange(i + 1, s.col).setValue(norm);
        fixed++;
      }
    }
    report.push(`${s.name}: fixed ${fixed} rows`);
  }

  // Sau khi normalize → re-settle toàn bộ để rebuild Settled + Summary
  const settleResult = settlePicks();
  report.push(`settlePicks: ${JSON.stringify(settleResult)}`);

  Logger.log('backfillNormalizeMatchNames:\n  ' + report.join('\n  '));
  return { success: true, report: report };
}

// ─── Tạm: set GITHUB_RAW_URL → matches32.json (workaround cho UI không lưu) ───
function setR32Url() {
  const url = 'https://raw.githubusercontent.com/CloudHoang/NhaCai/main/data/matches32.json';
  PropertiesService.getScriptProperties().setProperty('GITHUB_RAW_URL', url);
  const check = PropertiesService.getScriptProperties().getProperty('GITHUB_RAW_URL');
  Logger.log('GITHUB_RAW_URL set to: ' + check);
  return { success: true, url: check };
}

