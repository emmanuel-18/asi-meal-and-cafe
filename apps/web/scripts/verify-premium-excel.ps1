param([Parameter(Mandatory=$true)][string]$ManifestPath,
      [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
      [switch]$PrintPreviews)
$ErrorActionPreference = 'Stop'
$manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$folder = [System.IO.Path]::GetFullPath($EvidenceDirectory)
if (Test-Path -LiteralPath $folder) { throw 'Choose a fresh evidence directory' }
New-Item -ItemType Directory -Path $folder | Out-Null
$excel = $null
$book = $null
$results = @()
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.AutomationSecurity = 3
    $excel.AskToUpdateLinks = $false
    foreach ($entry in $manifest) {
        $path = [System.IO.Path]::GetFullPath($entry.path)
        $hash = (Get-FileHash -LiteralPath $path).Hash
        $name = [System.IO.Path]::GetFileNameWithoutExtension($path)
        # Normal load, read-only, no link updates, no suppressed repair warnings.
        $book = $excel.Workbooks.Open($path, 0, $true)
        $excel.CalculateFull()
        $expectedNames = @('Executive Dashboard','Daily Sales','Salary Deduction List','Mode of Payment')
        if ($book.Worksheets.Count -ne 4) { throw 'Unexpected sheet count' }
        for ($i=1; $i -le 4; $i++) {
            $sheet = $book.Worksheets.Item($i)
            if ($sheet.Name -ne $expectedNames[$i-1]) { throw 'Unexpected worksheet name/order' }
            if (-not $sheet.PageSetup.PrintArea) { throw 'Missing print area' }
            $values = $sheet.UsedRange.Value2
            foreach ($value in $values) {
                if ($value -is [System.Runtime.InteropServices.ErrorWrapper]) { throw 'Excel cell error' }
                if ([string]$value -match '^#(REF!|VALUE!|NUM!|DIV/0!|NAME\?|N/A)$') { throw 'Excel calculation error' }
            }
        }
        $dashboard = $book.Worksheets.Item(1)
        if ([decimal]$dashboard.Range('A5').Value2 -ne [decimal]$entry.total) { throw 'Dashboard total mismatch after recalculation' }
        $payment = $book.Worksheets.Item(4)
        $totalRow = [int]$entry.days + 6
        if ([decimal]$payment.Range("H$totalRow").Value2 -ne [decimal]$entry.total) { throw 'Payment sales total mismatch' }
        if ([decimal]$payment.Range("G$totalRow").Value2 -ne [decimal]$entry.total) { throw 'Allocation total mismatch' }
        if ([decimal]$payment.Range("I$totalRow").Value2 -ne 0) { throw 'Allocation difference after recalculation' }
        $sd = $book.Worksheets.Item(3)
        if ([decimal]$sd.Range('E3').Value2 -ne [decimal]$entry.sd) { throw 'SD total mismatch' }
        $daily = $book.Worksheets.Item(2)
        $footer = $daily.Columns.Item(1).Find('Period total')
        if (-not $footer) { throw 'Missing Daily Sales total' }
        if ([int]$entry.days -le 7) { $totalColumn = $daily.Rows.Item(7).Find('Period total').Column } else { $totalColumn = 13 }
        if ([decimal]$daily.Cells.Item($footer.Row,$totalColumn).Value2 -ne [decimal]$entry.total) { throw 'Daily Sales formula total mismatch' }
        $chartCount = $dashboard.ChartObjects().Count
        if ($chartCount -lt 2) { throw 'Missing native charts' }
        for ($i=1; $i -le $chartCount; $i++) {
            $dashboard.ChartObjects().Item($i).Activate() | Out-Null
            $chart = $dashboard.ChartObjects().Item($i).Chart
            $chart.Refresh()
            if ([string]$chart.SeriesCollection(1).Formula -match '#REF!') { throw 'Broken chart source' }
            if (-not $chart.Export((Join-Path $folder "$name-chart-$i.png"), 'PNG')) { throw 'Chart render failed' }
        }
        if ($PrintPreviews) { $book.ExportAsFixedFormat(0, (Join-Path $folder "$name-print.pdf")) }
        # Test editability and save/reopen only in a separate synthetic evidence copy.
        $series = $dashboard.ChartObjects().Item(1).Chart.SeriesCollection(1)
        $match = [regex]::Match($series.Formula, '\$B\$(\d+):\$B\$\d+')
        if (-not $match.Success) { throw 'Unexpected native series reference' }
        $sourceCell = $dashboard.Range('B' + $match.Groups[1].Value)
        $edited = [double]$sourceCell.Value2 + 0.01
        $sourceCell.Value2 = $edited
        $excel.CalculateFull()
        if ([decimal]@($series.Values)[0] -ne [decimal]$edited) { throw 'Native chart did not update' }
        $dashboard.ChartObjects().Item(1).Chart.ChartTitle.Text = 'Editable native chart verified'
        $copy = Join-Path $folder "$name-edited.xlsx"
        $book.SaveCopyAs($copy); $book.Close($false); $book = $null
        $book = $excel.Workbooks.Open($copy, 0, $true)
        if ($book.Worksheets.Item(1).ChartObjects().Item(1).Chart.ChartTitle.Text -ne 'Editable native chart verified') { throw 'Chart edit lost on reopen' }
        $book.Close($false); $book = $null
        if ((Get-FileHash -LiteralPath $path).Hash -ne $hash) { throw 'Original workbook changed' }
        $results += [PSCustomObject]@{name=$name; charts=$chartCount; total=$entry.total; formulas='recalculated'; chartsEditable=$true; originalUnchanged=$true}
    }
    [PSCustomObject]@{excelVersion=$excel.Version; excelBuild=$excel.Build; results=$results} | ConvertTo-Json -Depth 5 | Tee-Object -FilePath (Join-Path $folder 'excel-verification.json')
} finally {
    if ($book) { $book.Close($false) }
    if ($excel) { $excel.Quit(); [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel) }
    [GC]::Collect(); [GC]::WaitForPendingFinalizers()
}
