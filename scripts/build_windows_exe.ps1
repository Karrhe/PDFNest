param(
    [string]$Version = "0.2.3"
)

$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $Python)) {
    throw "Missing virtual environment Python: $Python"
}

if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller is not installed. Run: .\.venv\Scripts\python.exe -m pip install pyinstaller"
}

$ReleaseAssets = Join-Path $Root "release_assets"
$Release = Join-Path $Root "release"
$WorkOnedir = Join-Path $Root "build\pyinstaller"
$WorkOnefile = Join-Path $Root "build\pyinstaller-onefile"
$IconPng = Join-Path $ReleaseAssets "PDFNest-256x256-transparent.png"
$IconIco = Join-Path $ReleaseAssets "PDFNest-transparent.ico"
$Main = Join-Path $Root "src\pdf_notes_reader\main.py"
$Asset = Join-Path $Root "src\pdf_notes_reader\assets\Icon.png"
$PicAssets = Join-Path $Root "Pic"

New-Item -ItemType Directory -Force -Path $ReleaseAssets | Out-Null
New-Item -ItemType Directory -Force -Path $Release | Out-Null

if (-not (Test-Path $IconPng)) {
    throw "Missing transparent PNG icon source: $IconPng"
}

if (-not (Test-Path $IconIco)) {
    throw "Missing transparent ICO icon source: $IconIco"
}

if (-not (Test-Path $PicAssets)) {
    throw "Missing UI icon assets folder: $PicAssets"
}

function Write-StartMenuAssets {
    param(
        [string]$TargetDir,
        [string]$ExeStem
    )

    Add-Type -AssemblyName System.Drawing
    $AssetsDir = Join-Path $TargetDir "$ExeStem.VisualElements"
    New-Item -ItemType Directory -Force -Path $AssetsDir | Out-Null

    $LogoSizes = @{
        "Square44x44Logo.png" = 44
        "Square70x70Logo.png" = 70
        "Square150x150Logo.png" = 150
    }

    foreach ($Entry in $LogoSizes.GetEnumerator()) {
        $Size = [int]$Entry.Value
        $Source = [System.Drawing.Bitmap]::new($IconPng)
        try {
            $Bitmap = [System.Drawing.Bitmap]::new($Size, $Size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
            try {
                $Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
                try {
                    $Graphics.Clear([System.Drawing.Color]::Transparent)
                    $Graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
                    $Graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                    $Graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
                    $Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
                    $Graphics.DrawImage($Source, 0, 0, $Size, $Size)
                }
                finally {
                    $Graphics.Dispose()
                }
                $Bitmap.Save((Join-Path $AssetsDir $Entry.Key), [System.Drawing.Imaging.ImageFormat]::Png)
            }
            finally {
                $Bitmap.Dispose()
            }
        }
        finally {
            $Source.Dispose()
        }
    }

    $Manifest = @"
<Application xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <VisualElements
    BackgroundColor="#3f4a48"
    ForegroundText="light"
    ShowNameOnSquare150x150Logo="on"
    Square44x44Logo="$ExeStem.VisualElements\Square44x44Logo.png"
    Square70x70Logo="$ExeStem.VisualElements\Square70x70Logo.png"
    Square150x150Logo="$ExeStem.VisualElements\Square150x150Logo.png" />
</Application>
"@
    Set-Content -LiteralPath (Join-Path $TargetDir "$ExeStem.VisualElementsManifest.xml") -Value $Manifest -Encoding UTF8
}

Copy-Item -LiteralPath $IconPng -Destination (Join-Path $Root "Icon.png") -Force
Copy-Item -LiteralPath $IconPng -Destination (Join-Path $Root "PDFNest-Icon.png") -Force
Copy-Item -LiteralPath $IconPng -Destination $Asset -Force

& $PyInstaller --noconfirm --clean --windowed --name PDFNest --paths (Join-Path $Root "src") --distpath $Release --workpath $WorkOnedir --specpath $WorkOnedir --icon $IconIco --add-data "$Asset;pdf_notes_reader\assets" --add-data "$PicAssets;Pic" $Main
Write-StartMenuAssets -TargetDir (Join-Path $Release "PDFNest") -ExeStem "PDFNest"

$Zip = Join-Path $Release "PDFNest-$Version-windows-x64.zip"
if (Test-Path $Zip) {
    Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $Release "PDFNest") -DestinationPath $Zip -CompressionLevel Optimal

& $PyInstaller --noconfirm --clean --onefile --windowed --name "PDFNest-$Version-windows-x64" --paths (Join-Path $Root "src") --distpath $Release --workpath $WorkOnefile --specpath $WorkOnefile --icon $IconIco --add-data "$Asset;pdf_notes_reader\assets" --add-data "$PicAssets;Pic" $Main
Write-StartMenuAssets -TargetDir $Release -ExeStem "PDFNest-$Version-windows-x64"

Get-ChildItem $Release | Format-Table Name,Length,LastWriteTime
