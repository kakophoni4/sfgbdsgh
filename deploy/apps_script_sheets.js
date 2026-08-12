/**
 * Красивая выгрузка по дням. После правки кода:
 * Развернуть → Управление развёртываниями → ✏️ → Новая версия → Развернуть
 *
 * POST: { sheets: [{ name, headers, rows, formats? }] }
 * formats: { verdictCol: 14, zskCol: 13 }  // 1-based
 */

var EXPECTED_TOKEN = "";
var VERSION = "v5.1-inn-text";

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
      // старый фильтр блокирует createFilter / иногда clear
      try {
        var oldF = sh.getFilter();
        if (oldF) oldF.remove();
      } catch (ignoreFilter) {}
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

      // Балл / ИНН — всегда текст (иначе Sheets: дата или 9,723,214,226)
      var scoreCol = _headerIndex(headers, "Балл");
      if (scoreCol < 0) scoreCol = 17;
      var innCol = _headerIndex(headers, "ИНН");
      if (innCol < 0) innCol = 3;
      if (scoreCol >= 1 && scoreCol <= cols) {
        for (var sr = 1; sr < all.length; sr++) {
          var sv = all[sr][scoreCol - 1];
          if (sv !== "" && sv !== null && sv !== undefined) {
            all[sr][scoreCol - 1] = String(sv);
          }
        }
      }
      if (innCol >= 1 && innCol <= cols) {
        for (var ir = 1; ir < all.length; ir++) {
          var iv = all[ir][innCol - 1];
          if (iv !== "" && iv !== null && iv !== undefined) {
            // только цифры; ведущий ' заставляет Sheets держать TEXT
            var is = String(iv).replace(/[^\d]/g, "");
            all[ir][innCol - 1] = is ? "'" + is : "";
          }
        }
        // формат TEXT до записи — иначе setValues всё равно сделает number
        sh.getRange(1, innCol, Math.max(all.length, 2), innCol).setNumberFormat("@");
      }
      if (scoreCol >= 1 && scoreCol <= cols) {
        sh.getRange(1, scoreCol, Math.max(all.length, 2), scoreCol).setNumberFormat("@");
      }

      var range = sh.getRange(1, 1, all.length, cols);
      range.setValues(all);
      range.setFontFamily("Arial");
      range.setFontSize(10);
      range.setVerticalAlignment("middle");
      range.setWrap(false);
      if (scoreCol >= 1 && scoreCol <= cols && all.length >= 2) {
        sh.getRange(2, scoreCol, all.length, scoreCol).setNumberFormat("@");
      }
      if (innCol >= 1 && innCol <= cols && all.length >= 2) {
        sh.getRange(2, innCol, all.length, innCol).setNumberFormat("@");
      }
      // Цена — обычное число, не дата
      var priceCol = _headerIndex(headers, "Цена");
      if (priceCol >= 1 && priceCol <= cols && all.length >= 2) {
        sh.getRange(2, priceCol, all.length, priceCol).setNumberFormat("#,##0");
      }

      // шапка
      var head = sh.getRange(1, 1, 1, cols);
      head.setBackground("#1F4E79");
      head.setFontColor("#FFFFFF");
      head.setFontWeight("bold");
      head.setFontSize(11);
      head.setHorizontalAlignment("center");
      sh.setRowHeight(1, 32);
      sh.setFrozenRows(1);
      // Источник + Название + ИНН
      if (cols >= 3) sh.setFrozenColumns(3);
      else if (cols >= 2) sh.setFrozenColumns(2);

      if (rows.length > 0) {
        sh.setRowHeights(2, rows.length, 24);
        // тонкие границы
        sh.getRange(1, 1, rows.length + 1, cols)
          .setBorder(true, true, true, true, true, true, "#D0D7DE", SpreadsheetApp.BorderStyle.SOLID);

        // цвет ВСЕЙ строки по итогу (вердикту)
        for (var v = 0; v < rows.length; v++) {
          var rowRange = sh.getRange(v + 2, 1, 1, cols);
          var verdictText = "";
          if (verdictCol >= 1 && verdictCol <= cols) {
            verdictText = String(rows[v][verdictCol - 1] || "");
          }
          var kind = _verdictKind(verdictText);
          var rowBg = "#FFFFFF";
          if (kind === "yes") rowBg = "#C6EFCE";
          else if (kind === "no") rowBg = "#FFC7CE";
          else if (kind === "maybe") rowBg = "#FFEB9C";
          else rowBg = v % 2 === 0 ? "#FFFFFF" : "#F3F6FA";
          rowRange.setBackground(rowBg);
          if (kind !== "none" && verdictCol >= 1 && verdictCol <= cols) {
            sh.getRange(v + 2, verdictCol).setFontWeight("bold");
          }
        }

        // ЗСК — чуть ярче поверх цвета строки
        if (zskCol >= 1 && zskCol <= cols) {
          for (var z = 0; z < rows.length; z++) {
            var zc = sh.getRange(z + 2, zskCol);
            var zt = String(rows[z][zskCol - 1] || "").toLowerCase();
            if (zt.indexOf("зелён") >= 0 || zt.indexOf("зелен") >= 0) {
              zc.setBackground("#A9D08E");
            } else if (zt.indexOf("жёлт") >= 0 || zt.indexOf("желт") >= 0) {
              zc.setBackground("#FFD966");
            } else if (zt.indexOf("красн") >= 0) {
              zc.setBackground("#FF8B94");
            }
          }
        }

        try {
          var prev = sh.getFilter();
          if (prev) prev.remove();
        } catch (ignore2) {}
        sh.getRange(1, 1, rows.length + 1, cols).createFilter();
      }

      _setWidths(sh, cols, headers);
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

function _setWidths(sh, cols, headers) {
  // 1 Источник, 2 Название … 15 ЗСК, 16 Итог, 17 Балл …
  var widths = {
    1: 120,
    2: 200,
    3: 110,
    4: 90,
    5: 110,
    6: 80,
    7: 240,
    8: 100,
    9: 110,
    10: 160,
    11: 130,
    12: 140,
    13: 100,
    14: 130,
    15: 120,
    16: 420, // Итог — широкий
    17: 60,
    18: 110,
    19: 120,
    20: 200,
    21: 220,
    22: 140,
  };
  for (var c = 1; c <= cols; c++) {
    sh.setColumnWidth(c, widths[c] || 100);
  }
  var itogCol = _headerIndex(headers || [], "Итог");
  if (itogCol < 0) itogCol = 16;
  if (itogCol >= 1 && itogCol <= cols) {
    var last = sh.getLastRow();
    if (last >= 2) {
      sh.getRange(2, itogCol, last, itogCol).setWrap(true);
      sh.setRowHeights(2, last - 1, 48);
    }
  }
}

function _headerIndex(headers, title) {
  for (var i = 0; i < headers.length; i++) {
    if (String(headers[i] || "") === title) return i + 1; // 1-based
  }
  return -1;
}

/**
 * yes / maybe / no / none — по тексту колонки «Итог».
 * Поддерживает и короткий вердикт (ДА/НЕТ), и живой summary.
 */
function _verdictKind(text) {
  var t = String(text || "").trim();
  if (!t) return "none";
  var low = t.toLowerCase();
  var up = t.toUpperCase();

  if (
    low.indexOf("беру в работу") === 0 ||
    up.indexOf("ДА") === 0 ||
    up === "БРАТЬ" ||
    low.indexOf("брать") === 0
  ) {
    return "yes";
  }
  if (
    low.indexOf("скорее пропускаю") === 0 ||
    low.indexOf("пропускаю") === 0 ||
    up.indexOf("НЕТ") === 0
  ) {
    return "no";
  }
  if (
    low.indexOf("пока на паузе") === 0 ||
    low.indexOf("на паузе") === 0 ||
    up.indexOf("СОМН") === 0 ||
    low.indexOf("осторож") >= 0
  ) {
    return "maybe";
  }
  return "none";
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
