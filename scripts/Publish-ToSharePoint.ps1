# SharePoint Document Publisher - PowerShell Script
# Publishes all generated documents to SharePoint Semiconductor Knowledge Hub

param(
    [string]$SiteUrl = "https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub",
    [string]$LibraryName = "Semiconductor Knowledge",
    [string]$DocumentsPath = "C:\Projects\SharePoint\SharePoint-AISearch-POC\data\generated_documents"
)

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║       SharePoint Document Publisher - PowerShell Script        ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Configuration
Write-Host "Configuration:" -ForegroundColor Yellow
Write-Host "  Site URL:      $SiteUrl" -ForegroundColor Gray
Write-Host "  Library:       $LibraryName" -ForegroundColor Gray
Write-Host "  Documents:     $DocumentsPath" -ForegroundColor Gray
Write-Host ""

# Check if PnP PowerShell is installed
$pnpModule = Get-Module PnP.PowerShell -ListAvailable
if (-not $pnpModule) {
    Write-Host "⚠️  PnP PowerShell not installed" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "To install, run:" -ForegroundColor Yellow
    Write-Host "  Install-Module PnP.PowerShell -Force" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Alternative methods to upload:" -ForegroundColor Yellow
    Write-Host "  1. Manual upload via SharePoint UI" -ForegroundColor Gray
    Write-Host "  2. Use python scripts/publish_to_sharepoint.py" -ForegroundColor Gray
    Write-Host "  3. Use Invoke-WebRequest with authentication" -ForegroundColor Gray
    exit 1
}

Write-Host "✓ PnP PowerShell detected" -ForegroundColor Green
Write-Host ""

# Connect to SharePoint
Write-Host "Connecting to SharePoint..." -ForegroundColor Cyan
try {
    Connect-PnPOnline -Url $SiteUrl -Interactive -ErrorAction Stop
    Write-Host "✓ Connected to SharePoint" -ForegroundColor Green
} catch {
    Write-Host "✗ Connection failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Get all document files
$categories = @("Quality", "Manufacturing", "Inventory", "Sales", "Supply_Chain", "Yield")
$totalFiles = 0
$successfulFiles = 0
$failedFiles = 0

foreach ($category in $categories) {
    $categoryPath = Join-Path $DocumentsPath $category
    
    if (-not (Test-Path $categoryPath)) {
        Write-Host "⚠️  Category folder not found: $category" -ForegroundColor Yellow
        continue
    }
    
    Write-Host "Uploading $category documents..." -ForegroundColor Yellow
    
    # Ensure category folder exists in SharePoint
    $folderUrl = "$LibraryName/$category"
    
    try {
        $folder = Get-PnPFolder -Url $folderUrl -ErrorAction SilentlyContinue
        if (-not $folder) {
            Write-Host "  Creating folder: $category" -ForegroundColor Cyan
            $folder = New-PnPFolder -Name $category -Folder $LibraryName -ErrorAction Stop
        }
    } catch {
        Write-Host "  Warning: Could not create folder: $_" -ForegroundColor Yellow
    }
    
    # Get all files in category
    $files = Get-ChildItem -Path $categoryPath -File
    
    foreach ($file in $files) {
        $totalFiles++
        
        try {
            # Upload file
            $uploadResult = Add-PnPFile -Path $file.FullName -Folder $folderUrl -ErrorAction Stop
            Write-Host "  ✓ $($file.Name)" -ForegroundColor Green
            $successfulFiles++
        } catch {
            Write-Host "  ✗ $($file.Name): $_" -ForegroundColor Red
            $failedFiles++
        }
    }
    
    Write-Host ""
}

# Summary
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║                      Upload Summary                            ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "Total Files:      $totalFiles" -ForegroundColor Cyan
Write-Host "Successful:       $successfulFiles" -ForegroundColor Green
Write-Host "Failed:           $failedFiles" -ForegroundColor $(if ($failedFiles -eq 0) { "Green" } else { "Red" })
Write-Host ""

if ($failedFiles -eq 0 -and $totalFiles -gt 0) {
    Write-Host "✓ All documents uploaded successfully!" -ForegroundColor Green
} elseif ($totalFiles -eq 0) {
    Write-Host "⚠️  No documents found to upload" -ForegroundColor Yellow
} else {
    Write-Host "✗ Some documents failed to upload" -ForegroundColor Red
}

Write-Host ""

# Disconnect
Disconnect-PnPOnline

Write-Host "✓ Disconnected from SharePoint" -ForegroundColor Gray
Write-Host ""
