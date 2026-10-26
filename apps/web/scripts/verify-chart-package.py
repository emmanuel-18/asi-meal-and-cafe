"""Independent stdlib ZIP/XML verification of the synthetic chart prototype."""

from decimal import Decimal
import json
from pathlib import Path, PurePosixPath
import posixpath
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile


def verify(path: Path):
    with ZipFile(path) as archive:
        assert archive.testzip() is None, "ZIP CRC failure"
        names = set(archive.namelist())
        documents = {
            name: ET.fromstring(archive.read(name))
            for name in names if name.endswith((".xml", ".rels"))
        }
        relationships = {}
        for name, root in documents.items():
            if not name.endswith(".rels"):
                continue
            base = str(PurePosixPath(name).parent.parent)
            resolved = {}
            for relationship in root:
                assert relationship.get("TargetMode") != "External", "External relationship"
                target = relationship.attrib["Target"]
                target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(base, target))
                assert target in names, (name, target)
                identity = relationship.attrib["Id"]
                assert identity not in resolved, "Duplicate relationship ID"
                resolved[identity] = (relationship.attrib["Type"].rsplit("/", 1)[-1], target)
            relationships[name] = resolved
        ns = {
            "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
            "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
        }
        workbook = documents["xl/workbook.xml"]
        sheets = workbook.findall("s:sheets/s:sheet", ns)
        assert len(sheets) == 1 and sheets[0].get("name") == "Executive Dashboard"
        sheet_id = sheets[0].attrib[f"{{{ns['r']}}}id"]
        kind, sheet_path = relationships["xl/_rels/workbook.xml.rels"][sheet_id]
        assert kind == "worksheet"
        sheet = documents[sheet_path]
        drawing_id = sheet.find("s:drawing", ns).attrib[f"{{{ns['r']}}}id"]
        rel_path = str(PurePosixPath(sheet_path).parent / "_rels" / (PurePosixPath(sheet_path).name + ".rels"))
        kind, drawing_path = relationships[rel_path][drawing_id]
        assert kind == "drawing"
        chart_link = documents[drawing_path].find(".//c:chart", ns)
        rel_path = str(PurePosixPath(drawing_path).parent / "_rels" / (PurePosixPath(drawing_path).name + ".rels"))
        kind, chart_path = relationships[rel_path][chart_link.attrib[f"{{{ns['r']}}}id"]]
        assert kind == "chart"
        types = {element.attrib.get("PartName"): element.attrib.get("ContentType") for element in documents["[Content_Types].xml"]}
        assert types["/" + chart_path].endswith("drawingml.chart+xml")
        assert types["/" + drawing_path].endswith("drawing+xml")
        chart = documents[chart_path]
        assert chart.find(".//c:barDir", ns).get("val") == "bar"
        assert chart.find(".//c:cat/c:strRef/c:f", ns).text == "'Executive Dashboard'!$A$6:$A$10"
        assert chart.find(".//c:val/c:numRef/c:f", ns).text == "'Executive Dashboard'!$B$6:$B$10"
        categories = [point.find("c:v", ns).text for point in chart.findall(".//c:cat/c:strRef/c:strCache/c:pt", ns)]
        assert categories == ["Cash", "GCash", "Salary Deduction", "Incentive", "Finance"]
        amounts = [Decimal(point.find("c:v", ns).text) for point in chart.findall(".//c:val/c:numRef/c:numCache/c:pt", ns)]
        assert amounts == list(map(Decimal, ["45.01", "200.09", "150.25", "0.00", "75.00"]))
        cells = {cell.attrib["r"]: cell for cell in sheet.findall("s:sheetData/s:row/s:c", ns)}
        for row, amount in enumerate(amounts, 6):
            cell = cells[f"B{row}"]
            assert cell.get("t") in (None, "n"), "Source amount is not numeric"
            assert Decimal(cell.find("s:v", ns).text) == amount
        assert sum(amounts) == Decimal(cells["B12"].find("s:v", ns).text) == Decimal("470.35")
        assert cells["B12"].find("s:f", ns).text == "ROUND(SUM(B6:B10),2)"
        assert cells["B14"].get("t") == "s", "Identifier is not text"
        strings = documents["xl/sharedStrings.xml"].findall("s:si", ns)
        assert strings[int(cells["B14"].find("s:v", ns).text)].find("s:t", ns).text == "00001234"
        assert not any("externalLinks" in name or "vbaProject" in name or "xl/media/" in name for name in names)
        return {"zip_crc": "passed", "xml_parts_parsed": len(documents), "all_relationship_targets": "resolved", "chart_source_cells_and_caches": "matched", "exact_total": "470.35", "text_identifier": "preserved"}


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1])), indent=2))
