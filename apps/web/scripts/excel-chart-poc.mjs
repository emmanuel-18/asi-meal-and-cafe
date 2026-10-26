/** Isolated, synthetic native-chart proof. Not imported by the application. */
import ExcelJS from "exceljs";
import JSZip from "jszip";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { pathToFileURL } from "node:url";

export const paymentFixture = Object.freeze([
  Object.freeze({ label: "Cash", amount: "45.01" }),
  Object.freeze({ label: "GCash", amount: "200.09" }),
  Object.freeze({ label: "Salary Deduction", amount: "150.25" }),
  Object.freeze({ label: "Incentive", amount: "0.00" }),
  Object.freeze({ label: "Finance", amount: "75.00" }),
]);
const sheetName = "Executive Dashboard";
const currencyFormat = '"₱"#,##0.00';
const declaration = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
const relNs = "http://schemas.openxmlformats.org/package/2006/relationships";
const officeRelNs = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const chartNs = "http://schemas.openxmlformats.org/drawingml/2006/chart";
const drawingNs = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing";
const mainNs = "http://schemas.openxmlformats.org/drawingml/2006/main";

function xml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&apos;");
}

function numericMoney(value) {
  if (!/^\d+\.\d{2}$/.test(value)) throw new Error("Expected nonnegative decimal cents");
  const cents = BigInt(value.replace(".", ""));
  // Same conservative 15-digit centavo boundary as the existing Excel exporter.
  if (cents > 999999999999999n) throw new Error("Amount exceeds safe Excel numeric precision");
  const number = Number(cents) / 100;
  if (Math.round(number * 100) !== Number(cents)) throw new Error("Amount loses cents");
  return number;
}

/** Only accepts this prototype's own single-sheet ExcelJS output, not arbitrary XLSX. */
export async function addPaymentChart(bytes, rows = paymentFixture) {
  if (rows.length !== 5 || rows.some((row, i) => row.label !== paymentFixture[i].label)) {
    throw new Error("Expected exactly the five supported payment categories in order");
  }
  rows.forEach(row => numericMoney(row.amount));
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: true });
  const part = async name => {
    const file = zip.file(name);
    if (!file) throw new Error(`Missing expected XLSX part: ${name}`);
    return file.async("string");
  };
  // Resolve the generated worksheet via its relationship, not an assumed sheet1.xml.
  const workbook = await part("xl/workbook.xml");
  const sheets = [...workbook.matchAll(/<sheet\s[^>]*\/>/g)];
  if (sheets.length !== 1 || !sheets[0][0].includes(`name="${sheetName}"`)) {
    throw new Error("Expected only Executive Dashboard");
  }
  const sheetId = /\br:id="([^"]+)"/.exec(sheets[0][0])?.[1];
  const relationships = await part("xl/_rels/workbook.xml.rels");
  const relationship = [...relationships.matchAll(/<Relationship\s[^>]*\/>/g)]
    .map(match => match[0]).find(value => value.includes(`Id="${sheetId}"`));
  const target = /\bTarget="([^"]+)"/.exec(relationship ?? "")?.[1];
  if (!target || !/^worksheets\/sheet\d+\.xml$/.test(target)) {
    throw new Error("Unexpected worksheet relationship target");
  }
  const sheetPath = `xl/${target}`;
  const sheet = await part(sheetPath);
  const types = await part("[Content_Types].xml");
  if (/<drawing\b|<extLst\b|<tableParts\b/.test(sheet) ||
      Object.keys(zip.files).some(name => /^xl\/(drawings|charts)\//.test(name))) {
    throw new Error("Prototype refuses existing drawings, charts or trailing worksheet extensions");
  }
  const sheetRelPath = `xl/worksheets/_rels/${target.split("/").at(-1)}.rels`;
  if (zip.file(sheetRelPath)) throw new Error("Prototype refuses existing worksheet relationships");

  const categoryRef = `'${sheetName}'!$A$6:$A$10`;
  const valueRef = `'${sheetName}'!$B$6:$B$10`;
  const points = (key, convert) => rows.map((row, i) =>
    `<c:pt idx="${i}"><c:v>${xml(convert(row[key]))}</c:v></c:pt>`).join("");
  const chart = `${declaration}
<c:chartSpace xmlns:c="${chartNs}" xmlns:a="${mainNs}" xmlns:r="${officeRelNs}">
  <c:lang val="en-PH"/>
  <c:chart>
    <c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-PH"/><a:t>Payment allocations (synthetic)</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title>
    <c:autoTitleDeleted val="0"/>
    <c:plotArea><c:layout/>
      <c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/><c:varyColors val="0"/>
        <c:ser><c:idx val="0"/><c:order val="0"/>
          <c:tx><c:strRef><c:f>'${sheetName}'!$B$5</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>Allocated amount</c:v></c:pt></c:strCache></c:strRef></c:tx>
          <c:spPr><a:solidFill><a:srgbClr val="4094D9"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr>
          <c:invertIfNegative val="0"/>
          <c:cat><c:strRef><c:f>${xml(categoryRef)}</c:f><c:strCache><c:ptCount val="5"/>${points("label", String)}</c:strCache></c:strRef></c:cat>
          <c:val><c:numRef><c:f>${xml(valueRef)}</c:f><c:numCache><c:formatCode>${xml(currencyFormat)}</c:formatCode><c:ptCount val="5"/>${points("amount", numericMoney)}</c:numCache></c:numRef></c:val>
        </c:ser>
        <c:dLbls><c:dLblPos val="outEnd"/><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls>
        <c:gapWidth val="65"/><c:axId val="100001"/><c:axId val="100002"/>
      </c:barChart>
      <c:catAx><c:axId val="100001"/><c:scaling><c:orientation val="maxMin"/></c:scaling><c:delete val="0"/><c:axPos val="l"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="100002"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>
      <c:valAx><c:axId val="100002"/><c:scaling><c:orientation val="minMax"/><c:min val="0"/></c:scaling><c:delete val="0"/><c:axPos val="b"/><c:majorGridlines/><c:numFmt formatCode="${xml(currencyFormat)}" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="100001"/><c:crosses val="max"/><c:crossBetween val="between"/></c:valAx>
    </c:plotArea>
    <c:plotVisOnly val="1"/><c:dispBlanksAs val="zero"/><c:showDLblsOverMax val="0"/>
  </c:chart>
</c:chartSpace>`;
  const drawing = `${declaration}
<xdr:wsDr xmlns:xdr="${drawingNs}" xmlns:a="${mainNs}">
  <xdr:twoCellAnchor>
    <xdr:from><xdr:col>3</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>4</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>
    <xdr:to><xdr:col>13</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>24</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>
    <xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="1" name="Payment allocations"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>
      <xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>
      <a:graphic><a:graphicData uri="${chartNs}"><c:chart xmlns:c="${chartNs}" xmlns:r="${officeRelNs}" r:id="rId1"/></a:graphicData></a:graphic>
    </xdr:graphicFrame><xdr:clientData/>
  </xdr:twoCellAnchor>
</xdr:wsDr>`;
  const rel = (type, target) => `${declaration}<Relationships xmlns="${relNs}"><Relationship Id="rId1" Type="${officeRelNs}/${type}" Target="${target}"/></Relationships>`;
  zip.file(sheetPath, sheet.replace("</worksheet>", '<drawing r:id="rId1"/></worksheet>'));
  zip.file(sheetRelPath, rel("drawing", "../drawings/drawing1.xml"));
  zip.file("xl/drawings/drawing1.xml", drawing);
  zip.file("xl/drawings/_rels/drawing1.xml.rels", rel("chart", "../charts/chart1.xml"));
  zip.file("xl/charts/chart1.xml", chart);
  zip.file("[Content_Types].xml", types.replace("</Types>",
    '<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>' +
    '<Override PartName="/xl/charts/chart1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>'));
  return zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
}

export async function buildChartPrototype(rows = paymentFixture) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = "ASI Meal synthetic chart proof";
  workbook.calcProperties.fullCalcOnLoad = true;
  const sheet = workbook.addWorksheet(sheetName, { views: [{ showGridLines: false, state: "frozen", ySplit: 5 }] });
  sheet.columns = [{ width: 25 }, { width: 20 }, ...Array.from({ length: 11 }, () => ({ width: 9 }))];
  sheet.mergeCells("A1:M2");
  sheet.getCell("A1").value = "ASI Meal | Native Excel chart proof";
  sheet.getCell("A1").fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF160D76" } };
  sheet.getCell("A1").font = { name: "Open Sans", size: 18, bold: true, color: { argb: "FFFFFFFA" } };
  sheet.getCell("A3").value = "Synthetic values only — no report or database connection";
  sheet.mergeCells("A3:M3");
  sheet.getCell("A5").value = "Payment method";
  sheet.getCell("B5").value = "Allocated amount";
  rows.forEach((row, index) => {
    sheet.getCell(`A${index + 6}`).value = row.label;
    sheet.getCell(`B${index + 6}`).value = numericMoney(row.amount);
    sheet.getCell(`B${index + 6}`).numFmt = currencyFormat;
  });
  const totalCents = rows.reduce((sum, row) => sum + BigInt(row.amount.replace(".", "")), 0n);
  sheet.getCell("A12").value = "Total allocated";
  sheet.getCell("B12").value = { formula: "ROUND(SUM(B6:B10),2)", result: numericMoney(`${totalCents / 100n}.${String(totalCents % 100n).padStart(2, "0")}`) };
  sheet.getCell("B12").numFmt = currencyFormat;
  sheet.getCell("A14").value = "Synthetic employee identifier";
  sheet.getCell("B14").value = "00001234";
  sheet.getCell("B14").numFmt = "@";
  sheet.mergeCells("A26:M26");
  sheet.getCell("A26").value = "Edit a numeric source cell in B6:B10 in Excel: the native chart should update.";
  for (const number of [5, 12]) {
    const row = sheet.getRow(number);
    row.font = { name: "Open Sans", bold: true, color: { argb: "FF160D76" } };
    row.height = 28;
  }
  sheet.eachRow(row => { row.height = Math.max(row.height ?? 0, 23); row.eachCell(cell => { cell.alignment = { vertical: "middle", wrapText: true }; }); });
  sheet.pageSetup = { orientation: "landscape", paperSize: 9, fitToPage: true, fitToWidth: 1, fitToHeight: 1, printArea: "A1:M27" };
  const base = Buffer.from(await workbook.xlsx.writeBuffer());
  return { base, bytes: await addPaymentChart(base, rows) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (!process.argv[2] || !process.argv[2].endsWith(".xlsx")) throw new Error("Usage: node scripts/excel-chart-poc.mjs <output.xlsx>");
  const output = resolve(process.argv[2]);
  const { bytes } = await buildChartPrototype();
  await mkdir(dirname(output), { recursive: true });
  await writeFile(output, bytes, { flag: "wx" });
  console.log(`Synthetic native-chart prototype saved: ${output}`);
}
