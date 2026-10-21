# Publishing Documents to SharePoint

## Overview

This guide provides multiple methods to publish the 288 generated documents to the SharePoint Semiconductor Knowledge Hub.

## Quick Start (Recommended Method)

### Prerequisites
- PowerShell 5.0 or later
- PnP PowerShell module installed
- SharePoint Online access
- Appropriate permissions on the Semiconductor Knowledge library

### Installation

If you don't have PnP PowerShell installed:

```powershell
Install-Module PnP.PowerShell -Force
```

### Publish Documents

Run the PowerShell script:

```powershell
cd C:\Projects\SharePoint\SharePoint-AISearch-POC
.\scripts\Publish-ToSharePoint.ps1
```

This will:
1. Connect to your SharePoint site interactively
2. Create category folders if needed (Quality, Manufacturing, Inventory, Sales, Supply_Chain, Yield)
3. Upload all 288 documents
4. Display upload summary

## Alternative Methods

### Method 1: Python Script

**Requirements:**
```bash
pip install requests
```

**Usage:**
```powershell
# Set credentials as environment variables
$env:SHAREPOINT_USERNAME = "user@company.com"
$env:SHAREPOINT_PASSWORD = "your-password"

# Run the Python script
python scripts/publish_to_sharepoint.py
```

### Method 2: Manual Upload via SharePoint UI

1. Open SharePoint site:
   https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub

2. Navigate to "Semiconductor Knowledge" library

3. Create folders (if not exists):
   - Quality
   - Manufacturing
   - Inventory
   - Sales
   - Supply_Chain
   - Yield

4. Upload documents to corresponding folders:
   - Source: `data/generated_documents/{Category}/`
   - Target: `Semiconductor Knowledge/{Category}/`

### Method 3: Using Graph API

For advanced automation, use Microsoft Graph API:

```powershell
# Authenticate
$AccessToken = Get-MsGraphToken

# Upload file
$file = Get-Item "c:\path\to\file.docx"
$url = "https://graph.microsoft.com/v1.0/drives/root:/Semiconductor Knowledge/Quality/$($file.Name):/content"

Invoke-RestMethod -Uri $url -Method Put -Headers @{"Authorization"="Bearer $AccessToken"} -InFile $file.FullName
```

## Verification

After publishing, verify that documents appear in SharePoint:

1. Open SharePoint site
2. Check "Semiconductor Knowledge" library
3. Verify 6 category folders exist
4. Verify ~48 documents in each folder

Expected structure:
```
Semiconductor Knowledge/
├── Quality/              (48 files)
├── Manufacturing/        (48 files)
├── Inventory/            (48 files)
├── Sales/                (48 files)
├── Supply_Chain/         (48 files)
└── Yield/                (48 files)
```

## Troubleshooting

### Issue: "Module PnP.PowerShell not found"
**Solution:** Install PnP PowerShell
```powershell
Install-Module PnP.PowerShell -Force
```

### Issue: "Access Denied" error
**Solution:** Check permissions
- You need "Edit" or higher permissions on the library
- Contact site owner if needed

### Issue: "Folder not found" error
**Solution:** Create folders manually
1. Navigate to Semiconductor Knowledge library
2. Create 6 folders: Quality, Manufacturing, Inventory, Sales, Supply_Chain, Yield

### Issue: "File already exists" error
**Solution:** Choose action
- Let script overwrite (default)
- Or manually delete existing files first

## Monitoring Upload Progress

The scripts display progress for each file:
- ✓ = Successfully uploaded
- ✗ = Failed upload

Check the summary at the end for total counts.

## Azure AI Search Indexing

After publishing to SharePoint, documents will be automatically indexed:

1. **Automatic Detection**: SharePoint Direct indexer scans library
2. **Indexing Time**: Usually within 15-30 minutes
3. **Search Ready**: Documents searchable via Azure AI Search
4. **Monitoring**: Check Azure Portal > AI Search > Indexers

To monitor indexing status:

```powershell
# Via Azure Portal
https://portal.azure.com
→ Search for "semiconductor-search-myaacoub"
→ Click "Indexers"
→ Check "sharepoint-direct" status
```

## Document Organization

Documents are organized as follows:

| Category | Purpose | Document Count |
|----------|---------|-----------------|
| Quality | Quality assurance metrics and compliance | 16 (DOCX, XLSX, PPTX each) |
| Manufacturing | Production statistics and efficiency | 16 (DOCX, XLSX, PPTX each) |
| Inventory | Stock management and tracking | 16 (DOCX, XLSX, PPTX each) |
| Sales | Revenue analysis and performance | 16 (DOCX, XLSX, PPTX each) |
| Supply_Chain | Logistics and procurement data | 16 (DOCX, XLSX, PPTX each) |
| Yield | Production yield and efficiency | 16 (DOCX, XLSX, PPTX each) |

## Publishing Workflow

```
Local Generation (COMPLETE)
    ↓
GitHub Commit & Push (COMPLETE)
    ↓
SharePoint Publishing (THIS STEP)
    ↓
Azure AI Search Indexing (AUTOMATIC)
    ↓
Foundry Agent Integration (READY)
```

## Post-Publishing Tasks

After successfully publishing documents:

1. **Verify in SharePoint**
   - Check document counts
   - Verify folder structure

2. **Monitor Indexing**
   - Wait for indexer to complete
   - Check search results

3. **Test Searches**
   - Via Azure Portal Search Explorer
   - Via Foundry agent

4. **Foundry Agent Setup**
   - Add SharePoint knowledge source
   - Create knowledge base
   - Test agent responses

## Scripts Reference

### Publish-ToSharePoint.ps1
- **Language**: PowerShell
- **Requirements**: PnP.PowerShell module
- **Status**: Recommended
- **Advantages**: Interactive, detailed feedback, automatic folder creation

### publish_to_sharepoint.py
- **Language**: Python
- **Requirements**: requests module
- **Status**: Alternative
- **Advantages**: Scriptable, CI/CD friendly

### publish_to_sharepoint_v2.py
- **Language**: Python
- **Requirements**: requests module
- **Status**: Enhanced version
- **Advantages**: Multiple auth methods, fallback options

## Support

For issues or questions:

1. Check **Troubleshooting** section above
2. Review script logs and error messages
3. Check SharePoint site permissions
4. Verify documents exist locally

## Next Steps

After publishing documents:

1. ✓ Documents published to SharePoint
2. ⏳ Wait for Azure AI Search indexing (15-30 min)
3. ⏳ Configure Foundry agent knowledge base
4. ⏳ Test semantic search queries
5. ⏳ Monitor performance metrics

---

**Status**: Ready to publish  
**Last Updated**: 2026-10-21  
**Documents Ready**: 288 files  
**Target**: SharePoint Semiconductor Knowledge Hub
