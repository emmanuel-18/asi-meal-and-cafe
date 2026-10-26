/** Standard OOXML chart insertion, promoted from the validated Stage 14E.1 proof. */
import JSZip from "jszip";

export type NativeChart = { title: string; kind: "bar" | "line"; labels: string[]; values: number[];
  categoryRef: string; valueRef: string; seriesRef: string; seriesName: string; money: boolean;
  anchor: { left: number; top: number; right: number; bottom: number } };
const decl = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
const relNS = "http://schemas.openxmlformats.org/package/2006/relationships";
const officeNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
const chartNS = "http://schemas.openxmlformats.org/drawingml/2006/chart";
const mainNS = "http://schemas.openxmlformats.org/drawingml/2006/main";
const drawingNS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing";
export const xmlText = (value: string) => value.toWellFormed().split("").filter(c => c.charCodeAt(0) >= 32 || "\t\n\r".includes(c)).join("")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&apos;");

function chartXML(chart: NativeChart, id: number): string {
  const esc = xmlText;
  const cashFormat = chart.money ? '"₱"#,##0.00' : "0";
  const points = (values: (string | number)[]) => values.map((value, i) => `<c:pt idx="${i}"><c:v>${esc(String(value))}</c:v></c:pt>`).join("");
  const axisA = 100000 + id * 2, axisB = axisA + 1;
  const series = `<c:ser><c:idx val="0"/><c:order val="0"/>
    <c:tx><c:strRef><c:f>${esc(chart.seriesRef)}</c:f><c:strCache><c:ptCount val="1"/><c:pt idx="0"><c:v>${esc(chart.seriesName)}</c:v></c:pt></c:strCache></c:strRef></c:tx>
    <c:spPr>${chart.kind === "line" ? '<a:ln w="25400"><a:solidFill><a:srgbClr val="4094D9"/></a:solidFill></a:ln>' : '<a:solidFill><a:srgbClr val="4094D9"/></a:solidFill><a:ln><a:noFill/></a:ln>'}</c:spPr>
    ${chart.kind === "bar" ? '<c:invertIfNegative val="0"/>' : '<c:marker><c:symbol val="none"/></c:marker>'}
    <c:cat><c:strRef><c:f>${esc(chart.categoryRef)}</c:f><c:strCache><c:ptCount val="${chart.labels.length}"/>${points(chart.labels)}</c:strCache></c:strRef></c:cat>
    <c:val><c:numRef><c:f>${esc(chart.valueRef)}</c:f><c:numCache><c:formatCode>${esc(cashFormat)}</c:formatCode><c:ptCount val="${chart.values.length}"/>${points(chart.values)}</c:numCache></c:numRef></c:val>
    ${chart.kind === "line" ? '<c:smooth val="0"/>' : ""}
  </c:ser>`;
  return `${decl}<c:chartSpace xmlns:c="${chartNS}" xmlns:a="${mainNS}" xmlns:r="${officeNS}"><c:lang val="en-PH"/>
  <c:chart><c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-PH" sz="1200"/><a:t>${esc(chart.title)}</a:t></a:r></a:p></c:rich></c:tx><c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>
  <c:plotArea><c:layout/>
  ${chart.kind === "bar" ? `<c:barChart><c:barDir val="bar"/><c:grouping val="clustered"/><c:varyColors val="0"/>${series}<c:dLbls><c:numFmt formatCode="${esc(cashFormat)}" sourceLinked="0"/><c:dLblPos val="outEnd"/><c:showLegendKey val="0"/><c:showVal val="1"/><c:showCatName val="0"/><c:showSerName val="0"/><c:showPercent val="0"/><c:showBubbleSize val="0"/></c:dLbls><c:gapWidth val="65"/><c:axId val="${axisA}"/><c:axId val="${axisB}"/></c:barChart>` : `<c:lineChart><c:grouping val="standard"/><c:varyColors val="0"/>${series}<c:marker val="0"/><c:smooth val="0"/><c:axId val="${axisA}"/><c:axId val="${axisB}"/></c:lineChart>`}
  <c:catAx><c:axId val="${axisA}"/><c:scaling><c:orientation val="${chart.kind === "bar" ? "maxMin" : "minMax"}"/></c:scaling><c:delete val="0"/><c:axPos val="${chart.kind === "bar" ? "l" : "b"}"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${axisB}"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>
  <c:valAx><c:axId val="${axisB}"/><c:scaling><c:orientation val="minMax"/><c:min val="0"/></c:scaling><c:delete val="0"/><c:axPos val="${chart.kind === "bar" ? "b" : "l"}"/><c:majorGridlines/><c:numFmt formatCode="${esc(cashFormat)}" sourceLinked="0"/><c:majorTickMark val="none"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/><c:crossAx val="${axisA}"/><c:crosses val="${chart.kind === "bar" ? "max" : "autoZero"}"/><c:crossBetween val="between"/></c:valAx>
  </c:plotArea><c:plotVisOnly val="1"/><c:dispBlanksAs val="zero"/><c:showDLblsOverMax val="0"/></c:chart></c:chartSpace>`;
}

/** Accepts only our generated workbook; preserves all non-chart ZIP content. */
export async function insertNativeCharts(bytes: Uint8Array, sheetName: string, charts: NativeChart[]): Promise<Uint8Array> {
  const zip = await JSZip.loadAsync(bytes, { checkCRC32: true });
  const part = async (name: string) => {
    const file = zip.file(name);
    if (!file) throw new Error("Workbook chart package is incomplete.");
    return file.async("string");
  };
  const wb = await part("xl/workbook.xml");
  // ExcelJS writes one scoped Print_Area name per range. Excel requires one
  // scoped name containing the comma-separated union for disjoint print areas.
  const printAreaPattern = /<definedName name="_xlnm.Print_Area" localSheetId="(\d+)">([^<]+)<\/definedName>/g;
  const printAreas = new Map<string, string[]>();
  for (const match of wb.matchAll(printAreaPattern)) printAreas.set(match[1], [...(printAreas.get(match[1]) ?? []), match[2]]);
  const emitted = new Set<string>();
  const printWorkbook = wb.replace(printAreaPattern, (original, id: string) => {
    const ranges = printAreas.get(id)!;
    if (ranges.length === 1) return original;
    if (emitted.has(id)) return "";
    emitted.add(id);
    return `<definedName name="_xlnm.Print_Area" localSheetId="${id}">${ranges.join(",")}</definedName>`;
  });
  if (printWorkbook !== wb) zip.file("xl/workbook.xml", printWorkbook);
  const tag = [...wb.matchAll(/<sheet\s[^>]*\/>/g)].find(m => m[0].includes(`name="${xmlText(sheetName)}"`))?.[0];
  const identity = /\br:id="([^"]+)"/.exec(tag ?? "")?.[1];
  const wbRels = await part("xl/_rels/workbook.xml.rels");
  const rel = [...wbRels.matchAll(/<Relationship\s[^>]*\/>/g)].find(m => m[0].includes(`Id="${identity}"`))?.[0];
  const target = /\bTarget="([^"]+)"/.exec(rel ?? "")?.[1];
  if (!target || !/^worksheets\/sheet\d+\.xml$/.test(target)) throw new Error("Workbook dashboard reference is invalid.");
  const sheetPath = `xl/${target}`, sheet = await part(sheetPath);
  if (/<drawing\b/.test(sheet)) throw new Error("Dashboard already contains a drawing; refusing to overwrite it.");
  const nextPart = (prefix: string) => {
    let value = 1;
    while (zip.file(`${prefix}${value}.xml`)) value++;
    return value;
  };
  const drawingId = nextPart("xl/drawings/drawing");
  const sheetRelsPath = `xl/worksheets/_rels/${target.split("/").at(-1)}.rels`;
  let sheetRels = zip.file(sheetRelsPath) ? await part(sheetRelsPath) : `${decl}<Relationships xmlns="${relNS}"></Relationships>`;
  let rid = 1;
  while (sheetRels.includes(`Id="rId${rid}"`)) rid++;
  sheetRels = sheetRels.replace("</Relationships>", `<Relationship Id="rId${rid}" Type="${officeNS}/drawing" Target="../drawings/drawing${drawingId}.xml"/></Relationships>`);
  let types = await part("[Content_Types].xml");
  let drawings = "", drawingRels = "";
  for (const [index, chart] of charts.entries()) {
    if (!chart.labels.length || chart.labels.length !== chart.values.length || chart.values.some(v => !Number.isFinite(v) || v < 0)) throw new Error("Invalid native chart data.");
    const safeRef = /^'(Executive Dashboard|Daily Sales|Salary Deduction List|Mode of Payment)'!\$[A-Z]+\$\d+(?::\$[A-Z]+\$\d+)?$/;
    if (![chart.categoryRef, chart.valueRef, chart.seriesRef].every(r => safeRef.test(r))) throw new Error("Invalid native chart reference.");
    const chartId = nextPart("xl/charts/chart");
    zip.file(`xl/charts/chart${chartId}.xml`, chartXML(chart, chartId));
    types = types.replace("</Types>", `<Override PartName="/xl/charts/chart${chartId}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/></Types>`);
    const anchor = (col: number, row: number) => `<xdr:col>${col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>${row}</xdr:row><xdr:rowOff>0</xdr:rowOff>`;
    const a = chart.anchor;
    drawings += `<xdr:twoCellAnchor><xdr:from>${anchor(a.left, a.top)}</xdr:from><xdr:to>${anchor(a.right, a.bottom)}</xdr:to>
    <xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="${index + 1}" name="${xmlText(chart.title)}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="${chartNS}"><c:chart xmlns:c="${chartNS}" xmlns:r="${officeNS}" r:id="rId${index + 1}"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>`;
    drawingRels += `<Relationship Id="rId${index + 1}" Type="${officeNS}/chart" Target="../charts/chart${chartId}.xml"/>`;
  }
  // Drawing occurs before these trailing worksheet children in the OOXML schema.
  const trailing = /<(?:legacyDrawing|legacyDrawingHF|picture|oleObjects|controls|webPublishItems|tableParts|extLst)\b|<\/worksheet>/;
  zip.file(sheetPath, sheet.replace(trailing, match => `<drawing r:id="rId${rid}"/>${match}`));
  zip.file(sheetRelsPath, sheetRels);
  zip.file(`xl/drawings/drawing${drawingId}.xml`, `${decl}<xdr:wsDr xmlns:xdr="${drawingNS}" xmlns:a="${mainNS}">${drawings}</xdr:wsDr>`);
  zip.file(`xl/drawings/_rels/drawing${drawingId}.xml.rels`, `${decl}<Relationships xmlns="${relNS}">${drawingRels}</Relationships>`);
  types = types.replace("</Types>", `<Override PartName="/xl/drawings/drawing${drawingId}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/></Types>`);
  zip.file("[Content_Types].xml", types);
  return zip.generateAsync({ type: "uint8array", compression: "DEFLATE" });
}
