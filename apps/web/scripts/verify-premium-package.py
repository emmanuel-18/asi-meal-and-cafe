"""Independent ZIP/XML/cached-cell validation of generated synthetic workbooks."""
from decimal import Decimal
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"}


def verify(entry):
    with ZipFile(entry["path"]) as archive:
        assert archive.testzip() is None
        files = set(archive.namelist())
        docs = {n: ET.fromstring(archive.read(n)) for n in files if n.endswith((".xml", ".rels"))}
        rels = {}
        for name, root in docs.items():
            if not name.endswith(".rels"):
                continue
            targets = {}
            for rel in root:
                assert rel.get("TargetMode") != "External"
                target = rel.attrib["Target"]
                resolved = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(str(PurePosixPath(name).parent.parent), target))
                assert resolved in files, (name, resolved)
                assert rel.attrib["Id"] not in targets
                targets[rel.attrib["Id"]] = resolved
            rels[name] = targets
        sheets = docs["xl/workbook.xml"].findall("s:sheets/s:sheet", NS)
        defined = docs["xl/workbook.xml"].findall("s:definedNames/s:definedName", NS)
        scoped_names = [(n.get("name"), n.get("localSheetId")) for n in defined]
        assert len(scoped_names) == len(set(scoped_names)), "Duplicate scoped workbook names"
        assert [s.attrib["name"] for s in sheets] == ["Executive Dashboard", "Daily Sales", "Salary Deduction List", "Mode of Payment"]
        by_name = {s.attrib["name"]: docs[rels["xl/_rels/workbook.xml.rels"][s.attrib[f"{{{NS['r']}}}id"]]] for s in sheets}
        cells = {name: {c.attrib["r"]: c for c in sheet.findall("s:sheetData/s:row/s:c", NS)} for name, sheet in by_name.items()}
        for sheet in by_name.values():
            for cell in sheet.findall("s:sheetData/s:row/s:c", NS):
                if cell.find("s:f", NS) is not None:
                    assert cell.find("s:v", NS) is not None, "Formula has no cached result"
                    Decimal(cell.find("s:v", NS).text)
        total = Decimal(entry["total"])
        assert Decimal(cells["Executive Dashboard"]["A5"].find("s:v", NS).text) == total
        assert Decimal(cells["Mode of Payment"][f'H{entry["days"] + 6}'].find("s:v", NS).text) == total
        types = {c.attrib.get("PartName"): c.attrib.get("ContentType") for c in docs["[Content_Types].xml"]}
        chart_names = sorted(n for n in docs if re.fullmatch(r"xl/charts/chart\d+\.xml", n))
        for name in chart_names:
            assert types["/" + name].endswith("drawingml.chart+xml")
            chart = docs[name]
            reference = chart.find(".//c:val/c:numRef/c:f", NS).text
            match = re.fullmatch(r"'Executive Dashboard'!\$B\$(\d+):\$B\$(\d+)", reference)
            assert match
            cached = [Decimal(c.find("c:v", NS).text) for c in chart.findall(".//c:val/c:numRef/c:numCache/c:pt", NS)]
            source = [Decimal(cells["Executive Dashboard"][f"B{i}"].find("s:v", NS).text) for i in range(int(match[1]), int(match[2]) + 1)]
            assert source == cached
        anchors = []
        for name, root in docs.items():
            if not re.fullmatch(r"xl/drawings/drawing\d+\.xml", name):
                continue
            assert types["/" + name].endswith("drawing+xml")
            for anchor in root.findall("xdr:twoCellAnchor", NS):
                corners = [tuple(int(anchor.find(f"xdr:{edge}/xdr:{axis}", NS).text) for axis in ("col", "row")) for edge in ("from", "to")]
                left, top = corners[0]; right, bottom = corners[1]
                assert top >= 17 and bottom <= 52 and left < right and top < bottom
                assert all(right <= a or left >= c or bottom <= b or top >= d for a, b, c, d in anchors)
                anchors.append((left, top, right, bottom))
        assert len(anchors) == len(chart_names)
        assert not any("externalLinks" in n or "vbaProject" in n or "xl/media/" in n for n in files)
        return {"name": Path(entry["path"]).name, "sheets": 4, "charts": len(chart_names), "total": str(total), "zip_xml_references_and_cached_values": "passed"}


if __name__ == "__main__":
    print(json.dumps([verify(entry) for entry in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))], indent=2))
