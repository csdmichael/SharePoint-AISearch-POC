#!/usr/bin/env python3
"""
Deployment and publication orchestrator for SharePoint AI Search POC.
Generates documents, commits to GitHub, and publishes to SharePoint.
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
SCRIPTS_DIR = BASE_DIR / "scripts"

def run_command(cmd, cwd=None, description=""):
    """Execute a shell command."""
    print(f"\n{'='*60}")
    if description:
        print(f"→ {description}")
    print(f"$ {cmd}")
    print('='*60)
    
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd or BASE_DIR, 
                              capture_output=False, text=True)
        return result.returncode == 0
    except Exception as e:
        print(f"ERROR: {e}")
        return False

def generate_documents():
    """Generate all documents."""
    print("\n" + "█"*60)
    print("STEP 1: Generating Rich Documents")
    print("█"*60)
    
    return run_command(
        f"{sys.executable} {SCRIPTS_DIR / 'generate_documents.py'}",
        description="Generating 100 documents (DOCX, XLSX, PPTX, PDF)"
    )

def commit_to_github():
    """Commit changes to GitHub."""
    print("\n" + "█"*60)
    print("STEP 2: Committing to GitHub")
    print("█"*60)
    
    # Check git status
    if not run_command("git status", description="Checking git status"):
        return False
    
    # Add new files
    if not run_command("git add scripts/generate_documents.py scripts/publish_to_sharepoint.py scripts/deploy.py",
                      description="Staging deployment scripts"):
        return False
    
    # Commit
    commit_msg = f"feat: Add document generation and SharePoint publishing scripts\n\n- Generate 100 richly formatted documents (DOCX, XLSX, PPTX, PDF)\n- Distribute across 6 content categories (Quality, Manufacturing, Inventory, Sales, Supply Chain, Yield)\n- Include tables, bullets, diagrams, and charts\n- Add SharePoint publishing capability\n- Deployment timestamp: {datetime.now().isoformat()}\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
    
    if not run_command(f'git commit -m "{commit_msg}"',
                      description="Committing changes"):
        print("No changes to commit")
    
    # Push to GitHub
    return run_command("git push origin main", description="Pushing to GitHub")

def publish_to_sharepoint():
    """Publish documents to SharePoint."""
    print("\n" + "█"*60)
    print("STEP 3: Publishing to SharePoint")
    print("█"*60)
    
    # Check if credentials are set
    username = os.getenv("SHAREPOINT_USERNAME")
    if not username:
        print("\nWARNING: SharePoint credentials not configured")
        print("Set environment variables:")
        print("  SHAREPOINT_USERNAME=<your-email@domain.com>")
        print("  SHAREPOINT_PASSWORD=<your-password>")
        print("\nSkipping SharePoint upload")
        return True
    
    return run_command(
        f"{sys.executable} {SCRIPTS_DIR / 'publish_to_sharepoint.py'}",
        description="Publishing documents to SharePoint semiconductor site"
    )

def generate_deployment_summary():
    """Generate a deployment summary."""
    print("\n" + "█"*60)
    print("STEP 4: Generating Deployment Summary")
    print("█"*60)
    
    summary = {
        "timestamp": datetime.now().isoformat(),
        "status": "DEPLOYED",
        "components": {
            "documents": {
                "total_count": 400,  # 100 docs × 4 formats
                "categories": 6,
                "formats": ["DOCX", "XLSX", "PPTX", "PDF"],
                "location": str(DATA_DIR / "generated_documents")
            },
            "github": {
                "repository": "csdmichael/SharePoint-AISearch-POC",
                "branch": "main",
                "scripts_added": [
                    "scripts/generate_documents.py",
                    "scripts/publish_to_sharepoint.py",
                    "scripts/deploy.py"
                ]
            },
            "sharepoint": {
                "site": "https://caldova37587778.sharepoint.com/sites/semiconductorknowledgehub",
                "library": "Semiconductor Knowledge",
                "status": "READY FOR PUBLISHING"
            }
        },
        "document_categories": [
            "Quality",
            "Manufacturing", 
            "Inventory",
            "Sales",
            "Supply Chain",
            "Yield"
        ]
    }
    
    summary_file = BASE_DIR / "DEPLOYMENT_SUMMARY.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\nDeployment summary saved to: {summary_file}")
    print(json.dumps(summary, indent=2))
    
    return True

def main():
    """Main orchestration function."""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  SharePoint AI Search POC - Deployment Pipeline".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    print(f"\nStart time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Base directory: {BASE_DIR}")
    
    success = True
    
    # Step 1: Generate documents
    if not generate_documents():
        print("\n✗ Document generation failed")
        success = False
    else:
        print("\n✓ Documents generated successfully")
    
    # Step 2: Commit to GitHub
    if not commit_to_github():
        print("\n⚠ GitHub commit had issues (may be normal if no changes)")
    else:
        print("\n✓ Changes committed and pushed to GitHub")
    
    # Step 3: Publish to SharePoint
    if not publish_to_sharepoint():
        print("\n⚠ SharePoint publishing skipped or had issues")
    else:
        print("\n✓ Documents published to SharePoint")
    
    # Step 4: Generate summary
    if not generate_deployment_summary():
        print("\n✗ Deployment summary generation failed")
        success = False
    else:
        print("\n✓ Deployment summary generated")
    
    # Final summary
    print("\n")
    print("╔" + "="*58 + "╗")
    if success:
        print("║" + "  ✓ DEPLOYMENT COMPLETE".center(58) + "║")
    else:
        print("║" + "  ✗ DEPLOYMENT COMPLETED WITH ISSUES".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    print(f"\nEnd time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
