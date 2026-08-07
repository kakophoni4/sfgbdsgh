/**
 * Вставьте в таблицу: Расширения → Apps Script → вставьте этот код → Сохранить.
 * Развернуть → Новое развёртывание → Веб-приложение:
 *   - Выполнять от имени: Меня
 *   - У кого есть доступ: Все (или «Все, у кого есть ссылка»)
 * Скопируйте URL вида:
 *   https://script.google.com/macros/s/XXXX/exec
 * В .env на сервере:
 *   GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/XXXX/exec
 *
 * Опционально защита:
 *   GOOGLE_APPS_SCRIPT_TOKEN=любой_секрет
 * и тот же токен в Properties сервиса (см. ниже) или просто сравните в doPost.
 */

var SHEET_NAME = "Лоты";
// Если задали токен — должен совпасть с ?token=... или заголовком
var EXPECTED_TOKEN = ""; // или Script Properties: SCRIPT_TOKEN

function doPost(e) {
  try {
    var token = "";
    if (e.parameter && e.parameter.token) token = e.parameter.token;
    var expected = EXPECTED_TOKEN || PropertiesService.getScriptProperties().getProperty("SCRIPT_TOKEN") || "";
    if (expected && token !== expected) {
      return _json({ ok: false, error: "bad_token" });
    }

    var body = e.postData && e.postData.contents ? e.postData.contents : "";
    var data = JSON.parse(body);
    var headers = data.headers || [];
    var rows = data.rows || [];
    if (!headers.length) {
      return _json({ ok: false, error: "no_headers" });
    }

    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sh = ss.getSheetByName(SHEET_NAME);
    if (!sh) sh = ss.insertSheet(SHEET_NAME);

    sh.clearContents();
    var all = [headers].concat(rows);
    sh.getRange(1, 1, all.length, headers.length).setValues(all);
    sh.setFrozenRows(1);

    return _json({ ok: true, rows: rows.length, sheet: SHEET_NAME });
  } catch (err) {
    return _json({ ok: false, error: String(err) });
  }
}

function doGet() {
  return _json({ ok: true, info: "POST JSON {headers, rows}" });
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(
    ContentService.MimeType.JSON
  );
}
