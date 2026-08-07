/**
 * Красивая выгрузка по дням. После правки кода:
 * Развернуть → Управление развёртываниями → ✏️ → Новая версия → Развернуть
 *
 * POST: { sheets: [{ name, headers, rows, formats? }] }
 * formats: { verdictCol: 14, zskCol: 13 }  // 1-based
 */

var EXPECTED_TOKEN = "";
var VERSION = "v3-pretty-days";

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
    var verdictCol = (data.verdictCol || 14) | 0;
    var zskCol = (data.zskCol || 13) | 0;

    for (var i = 0; i < sheets.length; i++) {
      var spec = sheets[i];
      var headers = spec.headers || [];
      var rows = spec.rows || [];
      var name = String(spec.name || "лист").substring(0, 90);
      if (!headers.length) continue;

      keep[name] = true;
      var sh = ss.getSheetByName(name);
      if (!sh) sh = ss.insertSheet(name);
      sh.clear();
      sh.clearFormats();
      sh.setHiddenGridlines(true);

      var cols = headers.length;
      var all = [headers].concat(rows);
      for (var r = 0; r < all.length; r++) {
        var row = all[r] || [];
        if (row.length < cols) {
          while (row.length < cols) row.push("");
        } else if (row.length > cols) {
          all[r] = row.slice(0, cols);
        }
      }

      var range = sh.getRange(1, 1, all.length, cols);
      range.setValues(all);
      range.setFontFamily("Arial");
      range.setFontSize(10);
      range.setVerticalAlignment("middle");
      range.setWrap(false);

      // шапка
      var head = sh.getRange(1, 1, 1, cols);
      head.setBackground("#1F4E79");
      head.setFontColor("#FFFFFF");
      head.setFontWeight("bold");
      head.setFontSize(11);
      head.setHorizontalAlignment("center");
      sh.setRowHeight(1, 32);
      sh.setFrozenRows(1);
      if (cols >= 2) sh.setFrozenColumns(2);

      if (rows.length > 0) {
        sh.setRowHeights(2, rows.length, 24);
        // зебра
        for (var rr = 0; rr < rows.length; rr++) {
          var bg = rr % 2 === 0 ? "#FFFFFF" : "#F3F6FA";
          sh.getRange(rr + 2, 1, 1, cols).setBackground(bg);
        }
        // тонкие границы
        sh.getRange(1, 1, rows.length + 1, cols)
          .setBorder(true, true, true, true, true, true, "#D0D7DE", SpreadsheetApp.BorderStyle.SOLID);

        // цвета вердикта / ЗСК
        if (verdictCol >= 1 && verdictCol <= cols) {
          for (var v = 0; v < rows.length; v++) {
            var cell = sh.getRange(v + 2, verdictCol);
            var t = String(rows[v][verdictCol - 1] || "").toUpperCase();
            if (t.indexOf("ДА") === 0 || t === "БРАТЬ") {
              cell.setBackground("#C6EFCE").setFontWeight("bold");
            } else if (t.indexOf("НЕТ") === 0) {
              cell.setBackground("#FFC7CE").setFontWeight("bold");
            } else if (t.indexOf("СОМН") === 0 || t.indexOf("ОСТОРОЖ") >= 0) {
              cell.setBackground("#FFEB9C").setFontWeight("bold");
            }
          }
        }
        if (zskCol >= 1 && zskCol <= cols) {
          for (var z = 0; z < rows.length; z++) {
            var zc = sh.getRange(z + 2, zskCol);
            var zt = String(rows[z][zskCol - 1] || "").toLowerCase();
            if (zt.indexOf("зелён") >= 0 || zt.indexOf("зелен") >= 0) {
              zc.setBackground("#C6EFCE");
            } else if (zt.indexOf("жёлт") >= 0 || zt.indexOf("желт") >= 0) {
              zc.setBackground("#FFEB9C");
            } else if (zt.indexOf("красн") >= 0) {
              zc.setBackground("#FFC7CE");
            }
          }
        }

        sh.getRange(1, 1, rows.length + 1, cols).createFilter();
      }

      _setWidths(sh, cols);
      // цвет вкладки: сегодня/свежие — синий, старее — серый
      try {
        sh.setTabColor(i < 3 ? "#2E75B6" : "#9AA5B1");
      } catch (ignore) {}

      total += rows.length;
      written.push(name);
    }

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
        if (ss.getSheets().length > 1) ss.deleteSheet(existing[j]);
      }
    }

    for (var k = 0; k < written.length; k++) {
      var shMove = ss.getSheetByName(written[k]);
      if (shMove) {
        ss.setActiveSheet(shMove);
        ss.moveActiveSheet(k + 1);
      }
    }

    return _json({
      ok: true,
      version: VERSION,
      rows: total,
      sheets: written.length,
      names: written.slice(0, 50),
    });
  } catch (err) {
    return _json({ ok: false, error: String(err), version: VERSION });
  }
}

function doGet() {
  return _json({
    ok: true,
    version: VERSION,
    info: "POST JSON {sheets:[{name,headers,rows}]}",
  });
}

function _setWidths(sh, cols) {
  var widths = {
    1: 200,
    2: 110,
    3: 90,
    4: 110,
    5: 90,
    6: 260,
    7: 100,
    8: 110,
    9: 120,
    10: 130,
    11: 100,
    12: 120,
    13: 130,
    14: 320,
    15: 60,
    16: 110,
    17: 120,
    18: 200,
    19: 220,
    20: 140,
  };
  for (var c = 1; c <= cols; c++) {
    sh.setColumnWidth(c, widths[c] || 100);
  }
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
