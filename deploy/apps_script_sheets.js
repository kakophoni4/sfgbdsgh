/**
 * Вставьте в таблицу: Расширения → Apps Script → замените код → Сохранить.
 * Развернуть → Управление развёртываниями → ✏️ → Новая версия → Развернуть
 * (после правки кода нужна НОВАЯ версия, иначе сервер шлёт в старый скрипт).
 *
 * В .env:
 *   GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/XXXX/exec
 *   GOOGLE_APPS_SCRIPT_TOKEN=optional
 *
 * Формат POST JSON:
 *   { "sheets": [ { "name": "07.08.2026", "headers": [...], "rows": [[...], ...] }, ... ] }
 * Старый формат {headers, rows} → один лист «Лоты».
 */

var EXPECTED_TOKEN = "";

function doPost(e) {
  try {
    var token = (e.parameter && e.parameter.token) || "";
    var expected =
      EXPECTED_TOKEN ||
      PropertiesService.getScriptProperties().getProperty("SCRIPT_TOKEN") ||
      "";
    if (expected && token !== expected) {
      return _json({ ok: false, error: "bad_token" });
    }

    var body = e.postData && e.postData.contents ? e.postData.contents : "";
    var data = JSON.parse(body);
    var sheets = data.sheets;
    if (!sheets || !sheets.length) {
      sheets = [
        {
          name: "Лоты",
          headers: data.headers || [],
          rows: data.rows || [],
        },
      ];
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var keep = {};
    var total = 0;
    var written = [];

    for (var i = 0; i < sheets.length; i++) {
      var spec = sheets[i];
      var headers = spec.headers || [];
      var rows = spec.rows || [];
      var name = String(spec.name || "лист").substring(0, 90);
      if (!headers.length) continue;

      keep[name] = true;
      var sh = ss.getSheetByName(name);
      if (!sh) {
        sh = ss.insertSheet(name);
      }
      sh.clear();
      var all = [headers].concat(rows);
      // setValues падает, если строки разной длины — выровнять
      var cols = headers.length;
      for (var r = 0; r < all.length; r++) {
        var row = all[r] || [];
        if (row.length < cols) {
          while (row.length < cols) row.push("");
        } else if (row.length > cols) {
          all[r] = row.slice(0, cols);
        }
      }
      sh.getRange(1, 1, all.length, cols).setValues(all);
      sh.setFrozenRows(1);
      sh.getRange(1, 1, 1, cols).setFontWeight("bold");
      // без гигантских строк от длинного текста
      if (all.length > 1) {
        sh.setRowHeights(2, all.length - 1, 22);
      }
      sh.setRowHeight(1, 36);
      _setWidths(sh, cols);
      total += rows.length;
      written.push(name);
    }

    // убрать старые дневные/служебные листы, которых нет в новой выгрузке
    var existing = ss.getSheets();
    for (var j = existing.length - 1; j >= 0; j--) {
      var n = existing[j].getName();
      if (keep[n]) continue;
      if (
        n === "Лоты" ||
        n === "Sheet1" ||
        n === "Лист1" ||
        n === "без даты" ||
        /^\d{2}\.\d{2}\.\d{4}/.test(n)
      ) {
        if (ss.getSheets().length > 1) {
          ss.deleteSheet(existing[j]);
        }
      }
    }

    // порядок вкладок: свежие слева
    for (var k = 0; k < written.length; k++) {
      var shMove = ss.getSheetByName(written[k]);
      if (shMove) {
        ss.setActiveSheet(shMove);
        ss.moveActiveSheet(k + 1);
      }
    }

    return _json({
      ok: true,
      rows: total,
      sheets: written.length,
      names: written.slice(0, 40),
    });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

function doGet() {
  return _json({
    ok: true,
    info: "POST JSON {sheets:[{name,headers,rows}]}",
  });
}

function _setWidths(sh, cols) {
  var widths = {
    1: 160,
    2: 100,
    3: 100,
    4: 80,
    5: 80,
    6: 220,
    19: 140,
    23: 100,
    24: 120,
    25: 280,
    26: 160,
    34: 200,
    41: 180,
  };
  for (var c = 1; c <= cols; c++) {
    sh.setColumnWidth(c, widths[c] || 90);
  }
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
