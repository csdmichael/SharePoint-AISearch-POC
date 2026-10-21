#!/usr/bin/env python3
"""
Publish generated documents to SharePoint semiconductor site.
Requires SharePoint Online credentials and the Office 365 Python SDK.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import json
from office365.sharepoint.client_context import ClientContext
from office365.runtime.auth.authentication_context import AuthenticationContext

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
STATE_DIR = BASE_DIR / ".state"

# SharePoint configuration from deployment.json
CONFIG_FILE = BASE_DIR / "config" / "deployment.json"

def load_config():
    """Load SharePoint configuration."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None

def get_sharepoint_credentials():
    """Get SharePoint credentials from environment variables."""
    username = os.getenv("SHAREPOINT_USERNAME")
    password = os.getenv("SHAREPOINT_PASSWORD")
    site_url = os.getenv("SHAREPOINT_SITE_URL", 
                        "https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub")
    
    if not username or not password:
        print("ERROR: Please set SHAREPOINT_USERNAME and SHAREPOINT_PASSWORD environment variables")
        return None, None, None
    
    return username, password, site_url

def upload_to_sharepoint(site_url, username, password, local_file, remote_folder):
    """Upload a file to SharePoint."""
    try:
        auth_context = AuthenticationContext(url=site_url)
        auth_context.acquire_token_for_user(username, password)
        
        ctx = ClientContext(site_url, auth_context)
        
        with open(local_file, 'rb') as f:
            file_info = ctx.web.get_folder_by_server_relative_url(remote_folder).upload_file(
                Path(local_file).name, f
            ).execute_query()
        
        return True, file_info
    except Exception as e:
        return False, str(e)

def publish_documents(base_docs_dir, site_url, username, password):
    """Publish all generated documents to SharePoint."""
    
    if not os.path.exists(base_docs_dir):
        print(f"ERROR: Documents directory not found: {base_docs_dir}")
        return False
    
    # Map local folders to SharePoint folders
    categories = ["Quality", "Manufacturing", "Inventory", "Sales", "Supply_Chain", "Yield"]
    sp_library = "/sites/semiconductorknowledgehub/Semiconductor%20Knowledge"
    
    total_files = 0
    successful_uploads = 0
    failed_uploads = 0
    
    print(f"\nStarting document upload to SharePoint...")
    print(f"Site URL: {site_url}")
    print(f"Library: {sp_library}\n")
    
    for category in categories:
        local_category_dir = os.path.join(base_docs_dir, category)
        sp_category_folder = f"{sp_library}/{category}"
        
        if not os.path.exists(local_category_dir):
            print(f"Skipping category {category} - folder not found")
            continue
        
        print(f"\nUploading {category} documents...")
        
        files = list(Path(local_category_dir).glob("*"))
        
        for file_path in files:
            if file_path.is_file() and file_path.suffix in ['.docx', '.xlsx', '.pptx', '.pdf']:
                total_files += 1
                success, result = upload_to_sharepoint(
                    site_url, username, password, 
                    str(file_path), sp_category_folder
                )
                
                if success:
                    successful_uploads += 1
                    print(f"  ✓ {file_path.name}")
                else:
                    failed_uploads += 1
                    print(f"  ✗ {file_path.name}: {result}")
    
    print(f"\n" + "="*60)
    print(f"Upload Summary:")
    print(f"  Total files: {total_files}")
    print(f"  Successful: {successful_uploads}")
    print(f"  Failed: {failed_uploads}")
    print(f"="*60)
    
    return failed_uploads == 0

def main():
    """Main function."""
    print("SharePoint Document Publisher")
    print("="*60)
    
    # Load configuration
    config = load_config()
    
    # Get credentials
    username, password, site_url = get_sharepoint_credentials()
    if not username:
        return 1
    
    # Publish documents
    docs_dir = DATA_DIR / "generated_documents"
    
    if publish_documents(str(docs_dir), site_url, username, password):
        print("\n✓ All documents published successfully!")
        return 0
    else:
        print("\n✗ Some documents failed to upload")
        return 1

if __name__ == "__main__":
    sys.exit(main())
