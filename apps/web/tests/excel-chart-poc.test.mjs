import test from "node:test";
import assert from "node:assert/strict";
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { addPaymentChart, buildChartPrototype, paymentFixture } from "../scripts/excel-chart-poc.mjs";

test("native chart proof preserves every existing ZIP part except sheet drawing link and content types", async () => {
  const { base, bytes } = await buildChartPrototype();
  const before = await JSZip.loadAsync(base, { checkCRC32: true });
  const after = await JSZip.loadAsync(bytes, { checkCRC32: true });
  for (const [name, file] of Object.entries(before.files)) {
    if (file.dir || name === "[Content_Types].xml" || name === "xl/worksheets/sheet1.xml") continue;
    assert.deepEqual(await after.file(name).async("uint8array"), await file.async("uint8array"), name);
  }
  const oldSheet = await before.file("xl/worksheets/sheet1.xml").async("string");
  const newSheet = await after.file("xl/worksheets/sheet1.xml").async("string");
  assert.equal(newSheet.replace('<drawing r:id="rId1"/>', ""), oldSheet);
  assert.equal(Object.keys(after.files).filter(name => /xl\/charts\/[^/]+\.xml$/.test(name)).length, 1);
  assert.ok(!Object.keys(after.files).some(name => /externalLinks|vbaProject|xl\/media/.test(name)));
});

test("native drawing relationships and content types form an internal sheet-to-chart chain", async () => {
  const { bytes } = await buildChartPrototype();
  const zip = await JSZip.loadAsync(bytes);
  const sheet = await zip.file("xl/worksheets/sheet1.xml").async("string");
  assert.match(sheet, /<drawing r:id="rId1"\/>/);
  const sheetRels = await zip.file("xl/worksheets/_rels/sheet1.xml.rels").async("string");
  assert.match(sheetRels, /Id="rId1" Type="[^"]+\/drawing" Target="\.\.\/drawings\/drawing1.xml"/);
  const drawing = await zip.file("xl/drawings/drawing1.xml").async("string");
  assert.match(drawing, /<xdr:twoCellAnchor>/);
  assert.match(drawing, /<c:chart [^>]+r:id="rId1"/);
  const drawingRels = await zip.file("xl/drawings/_rels/drawing1.xml.rels").async("string");
  assert.match(drawingRels, /Id="rId1" Type="[^"]+\/chart" Target="\.\.\/charts\/chart1.xml"/);
  for (const name of Object.keys(zip.files).filter(name => name.endsWith(".rels"))) {
    assert.doesNotMatch(await zip.file(name).async("string"), /TargetMode="External"/);
  }
  const types = await zip.file("[Content_Types].xml").async("string");
  assert.match(types, /PartName="\/xl\/charts\/chart1.xml" ContentType="application\/vnd.openxmlformats-officedocument.drawingml.chart\+xml"/);
  assert.match(types, /PartName="\/xl\/drawings\/drawing1.xml" ContentType="application\/vnd.openxmlformats-officedocument.drawing\+xml"/);
});

test("chart series reference all five numeric worksheet cells with exact matching caches and zero category", async () => {
  const { bytes } = await buildChartPrototype();
  const zip = await JSZip.loadAsync(bytes);
  const chart = await zip.file("xl/charts/chart1.xml").async("string");
  assert.match(chart, /<c:barDir val="bar"\/>/);
  assert.match(chart, /<c:f>&apos;Executive Dashboard&apos;!\$A\$6:\$A\$10<\/c:f>/);
  assert.match(chart, /<c:f>&apos;Executive Dashboard&apos;!\$B\$6:\$B\$10<\/c:f>/);
  const numericCache = /<c:numCache>(.*?)<\/c:numCache>/s.exec(chart)[1];
  const values = [...numericCache.matchAll(/<c:pt idx="(\d)"><c:v>(.*?)<\/c:v><\/c:pt>/g)];
  assert.deepEqual(values.map(match => Number(match[2])), [45.01, 200.09, 150.25, 0, 75]);
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(bytes);
  assert.deepEqual(workbook.worksheets.map(sheet => sheet.name), ["Executive Dashboard"]);
  const sheet = workbook.worksheets[0];
  for (let i = 0; i < 5; i++) {
    assert.equal(sheet.getCell(`A${i + 6}`).value, paymentFixture[i].label);
    const cell = sheet.getCell(`B${i + 6}`);
    assert.equal(cell.type, ExcelJS.ValueType.Number);
    assert.equal(cell.numFmt, '"₱"#,##0.00');
    assert.equal(Math.round(cell.value * 100), Number(BigInt(paymentFixture[i].amount.replace(".", ""))));
    assert.equal(cell.value, Number(values[i][2]));
  }
  assert.equal(sheet.getCell("B12").formula, "ROUND(SUM(B6:B10),2)");
  assert.equal(sheet.getCell("B12").result, 470.35);
  assert.equal(sheet.getCell("B14").value, "00001234");
  assert.equal(sheet.getCell("B14").type, ExcelJS.ValueType.String);
  assert.equal(sheet.getCell("B14").numFmt, "@");
  assert.equal(sheet.getCell("A1").fill.fgColor.argb, "FF160D76");
  assert.equal(sheet.views[0].showGridLines, false);
  assert.equal(sheet.pageSetup.orientation, "landscape");
});

test("prototype refuses repeated injection, unsupported categories and unsafe financial values", async () => {
  const { bytes } = await buildChartPrototype();
  await assert.rejects(addPaymentChart(bytes), /refuses existing/);
  await assert.rejects(buildChartPrototype(paymentFixture.map((row, i) => i === 0 ? { ...row, amount: "999999999999999.99" } : row)), /precision/);
  await assert.rejects(buildChartPrototype(paymentFixture.map((row, i) => i === 0 ? { ...row, amount: "1.001" } : row)), /decimal cents/);
  await assert.rejects(buildChartPrototype(paymentFixture.slice(0, 4)), /five supported/);
  await assert.rejects(buildChartPrototype(paymentFixture.map((row, i) => i === 0 ? { ...row, label: "For Deposit" } : row)), /five supported/);
});
