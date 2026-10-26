param(
    [Parameter(Mandatory = $true)][string]$WorkbookPath,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory
)

# Local synthetic artifact only. Opens a new Excel instance; never attaches to
# the owner's existing Excel session. Does not interact with any ASI service.
$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $WorkbookPath).Path
$sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash
$evidencePath = [System.IO.Path]::GetFullPath($EvidenceDirectory)
New-Item -ItemType Directory -Force -Path $evidencePath | Out-Null
$copyPath = Join-Path $evidencePath 'edited-roundtrip.xlsx'
if (Test-Path -LiteralPath $copyPath) { throw 'Evidence already exists; choose a fresh evidence directory.' }
$excel = $null
$book = $null
$reopened = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.AutomationSecurity = 3 # Disable macros; this synthetic file has none.
    $excel.AskToUpdateLinks = $false
    # UpdateLinks=0; normal load (no repair/extract mode). Do not suppress alerts.
    $book = $excel.Workbooks.Open($sourcePath, 0, $true)
    if ($book.Worksheets.Count -ne 1) { throw 'Unexpected worksheet count.' }
    $sheet = $book.Worksheets.Item('Executive Dashboard')
    if ($sheet.ChartObjects().Count -ne 1) { throw 'Expected one native chart object.' }
    $chart = $sheet.ChartObjects().Item(1).Chart
    $series = $chart.SeriesCollection(1)
    $formula = [string]$series.Formula
    if ($formula -notlike '*$A$6:$A$10*' -or $formula -notlike '*$B$6:$B$10*') { throw 'Unexpected native source formula.' }
    if ([string]$sheet.Range('B14').Value2 -cne '00001234') { throw 'Text identifier was lost.' }
    if ([decimal]$sheet.Range('B12').Value2 -ne [decimal]470.35) { throw 'Initial total does not reconcile.' }
    if (@($series.Values).Count -ne 5) { throw 'Zero-valued category was dropped.' }
    $previewPath = Join-Path $evidencePath 'native-payment-chart.png'
    if (-not $chart.Export($previewPath, 'PNG')) { throw 'Excel chart rendering failed.' }

    # Prove a real source edit updates both the native series and total.
    $sheet.Range('B6').Value2 = 55.02
    $excel.CalculateFull()
    if ([decimal]@($series.Values)[0] -ne [decimal]55.02) { throw 'Chart did not update after editing its source.' }
    if ([decimal]$sheet.Range('B12').Value2 -ne [decimal]480.36) { throw 'Formula did not recalculate exactly to cents.' }
    $chart.ChartTitle.Text = 'Editable chart verified in Microsoft Excel'
    $book.SaveCopyAs($copyPath)
    $book.Close($false)
    $book = $null
    $reopened = $excel.Workbooks.Open($copyPath, 0, $true)
    $roundtripSheet = $reopened.Worksheets.Item('Executive Dashboard')
    $roundtripChart = $roundtripSheet.ChartObjects().Item(1).Chart
    if ($roundtripChart.ChartTitle.Text -ne 'Editable chart verified in Microsoft Excel') { throw 'Chart title edit was not preserved.' }
    if ([decimal]@($roundtripChart.SeriesCollection(1).Values)[0] -ne [decimal]55.02) { throw 'Chart source edit was not preserved.' }
    if ([decimal]$roundtripSheet.Range('B12').Value2 -ne [decimal]480.36) { throw 'Reopened total does not reconcile.' }
    $originalUnchanged = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash -eq $sourceHash
    if (-not $originalUnchanged) { throw 'Original prototype changed unexpectedly.' }
    [PSCustomObject]@{
        ExcelVersion = [string]$excel.Version
        ExcelBuild = [string]$excel.Build
        WorksheetCount = 1
        NativeChartCount = 1
        SeriesFormula = $formula
        InitialTotal = '470.35'
        EditedTotal = '480.36'
        SourceEditAndRecalculation = 'Passed'
        ChartTitleEditAndSaveReopen = 'Passed'
        OriginalWorkbookChanged = -not $originalUnchanged
        ChartPreview = $previewPath
        EditedEvidenceCopy = $copyPath
    } | ConvertTo-Json
} finally {
    if ($reopened) { $reopened.Close($false) }
    if ($book) { $book.Close($false) }
    if ($excel) { $excel.Quit(); [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
