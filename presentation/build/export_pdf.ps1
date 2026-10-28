# Exports Repeat_Purchase_Analysis.pptx to PDF using Microsoft PowerPoint (Windows).
#   powershell -ExecutionPolicy Bypass -File presentation/build/export_pdf.ps1 [-PngDir <folder>]
# -PngDir additionally renders each slide to PNG (used for visual QA).
param([string]$PngDir = "")
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$deck = Join-Path $here "..\Repeat_Purchase_Analysis.pptx" | Resolve-Path
$pdf  = [System.IO.Path]::ChangeExtension($deck, ".pdf")
$app = New-Object -ComObject PowerPoint.Application
try {
  $p = $app.Presentations.Open($deck, $true, $false, $false)
  $p.SaveAs($pdf, 32)   # ppSaveAsPDF
  if ($PngDir) {
    New-Item -ItemType Directory -Force $PngDir | Out-Null
    foreach ($sl in $p.Slides) { $sl.Export((Join-Path $PngDir ("slide-{0:D2}.png" -f $sl.SlideIndex)), "PNG", 1600, 900) }
  }
  "Exported $($p.Slides.Count) slides -> $pdf"
  $p.Close()
} finally {
  $app.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($app) | Out-Null
}
