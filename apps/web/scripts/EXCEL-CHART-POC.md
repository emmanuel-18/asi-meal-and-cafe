# Native Excel chart proof (Stage 14E.1)

This isolated prototype is not imported by `report-export.ts`, the Reports UI or
any application entry point. It uses synthetic fixtures and never contacts an API
or database. It does not implement the four-sheet report.

## Reproduce

Use the existing Node.js 24 development tooling with frontend dependencies
installed. From `apps/web`, choose a new artifact filename (the builder refuses
to overwrite an existing file):

```powershell
node scripts/excel-chart-poc.mjs ../../exports/native-chart-poc-20261026/payment-chart-proof.xlsx
node --test tests/excel-chart-poc.test.mjs
```

From the project root, validate the ZIP/XML using Python's standard library:

```powershell
.\.venv\Scripts\python.exe apps/web/scripts/verify-chart-package.py exports/native-chart-poc-20261026/payment-chart-proof.xlsx
```

On Windows with Microsoft Excel installed, choose a fresh evidence directory:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File apps/web/scripts/verify-excel-chart-poc.ps1 -WorkbookPath exports/native-chart-poc-20261026/payment-chart-proof.xlsx -EvidenceDirectory exports/native-chart-poc-20261026/excel-evidence
```

`ExecutionPolicy Bypass` is limited to this child PowerShell process; it does not
change the machine's execution policy. Review the local script before running it.
The verification opens a new Excel instance, keeps macros disabled, performs a
normal read-only workbook open without requesting repair, and leaves alerts
enabled. It edits only in-memory synthetic values and saves a separate evidence
copy. It never attaches to an existing Excel session. The original file's SHA-256
must remain unchanged. The instance it creates is closed afterward.

## Approach and financial values

- ExcelJS 4.4.0 creates the ordinary worksheet, formatting, text identifier,
  numeric cells and a cached total formula using public APIs.
- JSZip 3.10.2 loads the resulting buffer and adds standard chart/drawing parts,
  sheet-to-drawing and drawing-to-chart relationships, and content types.
  JSZip is pinned as a direct **development** dependency at its existing locked
  version; no package version or production dependency was upgraded.
- The chart is a native editable horizontal bar chart. Its series uses
  `'Executive Dashboard'!$A$6:$A$10` and `$B$6:$B$10`, with a title reference to
  `$B$5` and matching caches. It contains no raster chart, external workbook,
  macro or extra payment category.
- Cash 45.01, GCash 200.09, Salary Deduction 150.25, Incentive 0.00 and Finance
  75.00 total exactly **470.35**. The zero category stays in the chart.
- Money is validated as decimal strings/integer centavos before conversion;
  unsafe numeric magnitudes and fractional cents fail. Excel numeric money
  cells use peso formatting; the synthetic identifier `00001234` stays text.
- This is deliberately a bounded one-sheet injector. It resolves the worksheet
  from workbook relationships and refuses existing charts/drawings/worksheet
  relationships. It is not yet a general merger for image-bearing, multi-sheet
  workbooks. Adding logos or other charts needs explicit relationship allocation
  and further preservation tests before production use.

## Verification recorded on 2026-10-26

- Four focused Node tests passed; the full frontend suite passed **87/87**.
- ESLint, TypeScript (`--noEmit --incremental false`) and production build passed.
- Independent Python ZIP/XML verification parsed 14 XML/relationship parts,
  checked CRCs, resolved all relationship targets, checked content types and
  source-cell/cache equality, and reconciled 470.35 exactly.
- ExcelJS reopened the workbook; all original ZIP parts except the intended
  worksheet drawing link and content types are byte-preserved.
- Microsoft Excel **16.0, build 14334** opened the workbook normally and exposed
  one native chart with the expected `SERIES` formula. Editing Cash to 55.02
  updated the actual chart series and recalculated the total to 480.36.
- Editing the chart title, saving a separate copy and reopening retained the
  title, changed source data, chart and total. The original workbook was unchanged.
- Excel exported a PNG of its actual native chart. That rendered image was
  inspected: all five labels and amounts were readable, bar proportions matched
  the source cells, zero Incentive was labeled and no text was clipped.
- `npm audit` reported two moderate affected-package entries in the existing
  ExcelJS → UUID chain (one underlying advisory, GHSA-w5hq-g745-h8pq), no JSZip
  advisory. No forced fix or incompatible downgrade was applied.

Artifacts are in the ignored `exports/native-chart-poc-20261026/` directory.
The acceptance workbook is `payment-chart-proof.xlsx`; the PNG and edited
round-trip copy are supporting evidence only.

## Acceptance limits

This proves the one-chart approach in the tested Microsoft Excel build. It is
not visual acceptance of the full report, a browser download, mobile Excel,
Excel Online or LibreOffice. The code uses Node APIs and public ZIP operations
compatible with the configured Node 24 tooling; no Docker container was executed,
rebuilt or restarted for this proof, and Docker/browser-runtime execution remains
untested. A future browser integration must select browser-compatible ZIP output
instead of this standalone script's `nodebuffer` output and filesystem CLI.

The latest task names port 43873 as protected. Regardless of earlier port
changes, neither 43871 nor 43873 was accessed in this task. No databases,
application calculations, authentication or live exports changed.
