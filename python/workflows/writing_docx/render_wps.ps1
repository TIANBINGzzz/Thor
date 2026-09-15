param([string]$DocumentPath, [string]$PdfPath)
$ErrorActionPreference = 'Stop'
$office = New-Object -ComObject KWPS.Application
$office.Visible = $false
$office.DisplayAlerts = 0
try {
    $document = $office.Documents.Open($DocumentPath, $false, $true)
    try { $document.ExportAsFixedFormat($PdfPath, 17) } finally { $document.Close(0) }
} finally { $office.Quit() }
