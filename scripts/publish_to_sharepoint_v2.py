#!/usr/bin/env python3
"""
Publish generated documents to SharePoint Semiconductor Knowledge Hub
Simplified version using direct file upload via SharePoint REST API
"""

import os
import sys
import requests
from pathlib import Path
from datetime import datetime
import json

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data" / "generated_documents"

# SharePoint Configuration
SHAREPOINT_SITE_URL = "https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub"
SHAREPOINT_LIBRARY = "Semiconductor Knowledge"

def get_sharepoint_token(username, password):
    """Get authentication token for SharePoint Online."""
    auth_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    
    payload = {
        "client_id": "9bc3ab49-b65d-410a-85ad-de665a3cccad",  # SPO management shell
        "username": username,
        "password": password,
        "grant_type": "password",
        "scope": "https://graph.microsoft.com/.default"
    }
    
    try:
        response = requests.post(auth_url, data=payload, timeout=10)
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception as e:
        print(f"Authentication failed: {e}")
    
    return None

def publish_documents_to_sharepoint(username, password):
    """Publish all generated documents to SharePoint."""
    
    print(f"\nConnecting to SharePoint...")
    print(f"Site: {SHAREPOINT_SITE_URL}")
    print(f"Library: {SHAREPOINT_LIBRARY}\n")
    
    if not DATA_DIR.exists():
        print(f"ERROR: Documents directory not found: {DATA_DIR}")
        return False
    
    # Get token
    token = get_sharepoint_token(username, password)
    if not token:
        print("ERROR: Could not obtain authentication token")
        print("Trying alternative approach...")
        return publish_with_sharepoint_online_cli(username, password)
    
    categories = ["Quality", "Manufacturing", "Inventory", "Sales", "Supply_Chain", "Yield"]
    total_files = 0
    successful = 0
    failed = 0
    
    for category in categories:
        category_dir = DATA_DIR / category
        if not category_dir.exists():
            continue
        
        print(f"\nUploading {category} documents...")
        
        files = list(category_dir.glob("*"))
        for file_path in files:
            if file_path.is_file():
                total_files += 1
                try:
                    # Upload file to SharePoint
                    upload_url = f"{SHAREPOINT_SITE_URL}/Shared%20Documents/{category}/{file_path.name}"
                    
                    with open(file_path, 'rb') as f:
                        files_dict = {'file': f}
                        headers = {'Authorization': f'Bearer {token}'}
                        
                        response = requests.put(
                            upload_url,
                            files=files_dict,
                            headers=headers,
                            timeout=30
                        )
                        
                        if response.status_code in [200, 201]:
                            print(f"  ✓ {file_path.name}")
                            successful += 1
                        else:
                            print(f"  ✗ {file_path.name} (Status: {response.status_code})")
                            failed += 1
                
                except Exception as e:
                    print(f"  ✗ {file_path.name}: {e}")
                    failed += 1
    
    print(f"\n" + "="*60)
    print(f"Upload Summary:")
    print(f"  Total files: {total_files}")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")
    print(f"="*60)
    
    return failed == 0

def publish_with_sharepoint_online_cli(username, password):
    """Alternative: Use CLI or manual upload instructions."""
    print("\n" + "="*60)
    print("SharePoint Authentication Configuration")
    print("="*60)
    print(f"\nTo publish documents, use one of these methods:\n")
    
    print("METHOD 1: Using PnP PowerShell (Recommended)")
    print("-" * 60)
    print("""
# Install PnP PowerShell (if not installed)
Install-Module PnP.PowerShell -Force

# Connect and upload
Connect-PnPOnline -Url "https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub" -Interactive

# Upload documents
$files = Get-ChildItem "c:\\Projects\\SharePoint\\SharePoint-AISearch-POC\\data\\generated_documents" -Recurse -File
foreach ($file in $files) {
    $category = $file.Directory.Name
    Add-PnPFile -Path $file.FullName -Folder "Semiconductor Knowledge/$category"
    Write-Host "Uploaded: $($file.Name)"
}
""")
    
    print("\nMETHOD 2: Manual Upload via SharePoint UI")
    print("-" * 60)
    print(f"""
1. Open SharePoint site:
   {SHAREPOINT_SITE_URL}

2. Navigate to "Semiconductor Knowledge" library

3. For each category folder:
   - Quality
   - Manufacturing
   - Inventory
   - Sales
   - Supply_Chain
   - Yield
   
4. Upload corresponding documents from:
   c:\\Projects\\SharePoint\\SharePoint-AISearch-POC\\data\\generated_documents\\
""")
    
    print("\nMETHOD 3: Using Graph API (For Automation)")
    print("-" * 60)
    print("""
See publish_to_sharepoint.py for example implementation
Requires Azure AD app registration with Files.ReadWrite scope
""")
    
    return True

def main():
    """Main function."""
    print("\n" + "="*60)
    print("SharePoint Document Publisher")
    print("="*60)
    
    username = os.getenv("SHAREPOINT_USERNAME")
    password = os.getenv("SHAREPOINT_PASSWORD")
    
    if not username or not password:
        print("\nERROR: SharePoint credentials not set")
        print("\nSet environment variables:")
        print("  $env:SHAREPOINT_USERNAME = 'user@company.com'")
        print("  $env:SHAREPOINT_PASSWORD = 'your-password'\n")
        
        print("Then run: python scripts/publish_to_sharepoint.py\n")
        
        # Show alternative methods
        publish_with_sharepoint_online_cli(None, None)
        return 1
    
    success = publish_documents_to_sharepoint(username, password)
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
