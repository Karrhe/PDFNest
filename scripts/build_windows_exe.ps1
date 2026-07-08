param(
    [string]$Version = "0.1.0"
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
$IconPng = Join-Path $Root "Icon.png"
$IconIco = Join-Path $ReleaseAssets "PDFNest.ico"
$IconBuilder = Join-Path $Root "scripts\make_windows_icon.py"
$Main = Join-Path $Root "src\pdf_notes_reader\main.py"
$Asset = Join-Path $Root "src\pdf_notes_reader\assets\Icon.png"

New-Item -ItemType Directory -Force -Path $ReleaseAssets | Out-Null
New-Item -ItemType Directory -Force -Path $Release | Out-Null

& $Python $IconBuilder $IconPng $IconIco

& $PyInstaller --noconfirm --clean --windowed --name PDFNest --paths (Join-Path $Root "src") --distpath $Release --workpath $WorkOnedir --specpath $WorkOnedir --icon $IconIco --add-data "$Asset;pdf_notes_reader\assets" $Main

$Zip = Join-Path $Release "PDFNest-$Version-windows-x64.zip"
if (Test-Path $Zip) {
    Remove-Item -LiteralPath $Zip -Force
}
Compress-Archive -Path (Join-Path $Release "PDFNest") -DestinationPath $Zip -CompressionLevel Optimal

& $PyInstaller --noconfirm --clean --onefile --windowed --name "PDFNest-$Version-windows-x64" --paths (Join-Path $Root "src") --distpath $Release --workpath $WorkOnefile --specpath $WorkOnefile --icon $IconIco --add-data "$Asset;pdf_notes_reader\assets" $Main

Get-ChildItem $Release | Format-Table Name,Length,LastWriteTime
