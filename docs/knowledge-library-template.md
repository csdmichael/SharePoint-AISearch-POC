# Governed Knowledge document library template

This template gives site owners a reusable **document library**, not a list,
with all 27 additional columns from
[the governance policy](../config/governance-policy.json). Built-in file name,
title, created/modified dates and author/editor columns remain available.
No documents, sample data, credentials or tenant-specific URLs are included.

## Publish once (SharePoint administrator)

Use the latest SharePoint Online Management Shell. The publishing script
requires the `Microsoft.Online.SharePoint.PowerShell` module and an account with
the SharePoint Administrator role. Follow Microsoft's
[connection instructions](https://learn.microsoft.com/powershell/sharepoint/sharepoint-online/connect-sharepoint-online),
including the Windows PowerShell compatibility instructions if using PowerShell 7.
The scripts do not install modules or grant permissions automatically.

From the repository root, preview without connecting or changing the tenant:

```powershell
.\scripts\Publish-KnowledgeLibraryTemplate.ps1 `
    -AdminUrl https://contoso-admin.sharepoint.com -WhatIf
```

Then publish and retain the returned site script and list design IDs:

```powershell
$template = .\scripts\Publish-KnowledgeLibraryTemplate.ps1 `
    -AdminUrl https://contoso-admin.sharepoint.com
$template
```

Interactive authentication is handled by `Connect-SPOService` using modern
authentication in the system browser, avoiding native Windows broker dependencies. The script
generates the definition directly from the current policy, registers it with
`Add-SPOSiteScript`, then exposes it using `Add-SPOListDesign`. Template type
**101** makes it a document library template. The template is available
organization-wide by default; this does not grant access to any site or files.
Duplicate titles are rejected rather than creating duplicate picker entries.
If registration fails after creating the site script, its ID is printed for
administrator cleanup with `Remove-SPOSiteScript -Identity <site-script-id>`.

To limit template visibility, use
`Grant-SPOSiteDesignRights -Identity <list-design-id> -Principals <user-or-group> -Rights View`
as described in Microsoft's
[custom template guidance](https://learn.microsoft.com/sharepoint/lists-custom-template#scope-the-permissions-to-a-custom-template).
Template visibility is separate from library permissions.

## Create a library (site owner)

1. Open the target SharePoint site. You need permission to create libraries
   (normally a site owner with Full Control).
2. Open **Site contents > New > Document library**.
3. Select **From your organization > Governed Knowledge**.
4. Preview the template, select **Use template**, give the new library a unique
   name, and create it.
5. Open **Knowledge Documents**, the default view for everyday ownership,
   publication and classification work. Use **All Metadata** to see all 27
   additional fields, including lineage and governance results.
6. Upload a test document and open its details. Confirm **Lifecycle Status =
   Draft**, **Authoritative = No**, **AI Ready = No**, and the choice values below.
   Repeat with a second, differently named library to verify independent reuse.

The library name selected in the picker is specific to that library. Do not
apply the raw site script to an existing site as a substitute for using the
picker: `createSPList` can update a library with the same name.

## Included columns

Internal names are preserved so existing governance and search mappings work.
All fields are optional at the library schema level to allow drafts and uploads.

| Display name | Internal name | Type / choices |
| --- | --- | --- |
| Artifact ID | `ArtifactId` | Text, 64 characters, indexed and unique |
| Knowledge Category | `KnowledgeCategory` | Choice: Quality, Engineering |
| Source Table | `SourceTable` | Text, 255 characters |
| Source System | `SourceSystem` | Text, 255 characters |
| Profile Generated At | `ProfileGeneratedAt` | Date and time |
| Knowledge Owner | `KnowledgeOwner` | Single person or group |
| Lifecycle Status | `LifecycleStatus` | Draft, Published, Superseded, Archived; default Draft |
| Authoritative | `Authoritative` | Yes/No; default No |
| Review Date | `ReviewDate` | Date only |
| Document Type | `DocumentType` | Procedure, Specification, Test Report, Decision Record, Meeting Summary, Technical Guide |
| Product Family | `ProductFamily` | Choice: ApexDrive X500 |
| Process Area | `ProcessArea` | Failure Analysis, Quality Escalation, General Engineering |
| Content Sensitivity | `Sensitivity` | General, Confidential, Highly Confidential |
| Effective Date | `EffectiveDate` | Date only |
| Expiration Date | `ExpirationDate` | Date only |
| Supersedes Document | `SupersedesDocument` | Text, 255 characters |
| Business Unit | `BusinessUnit` | Text, 255 characters |
| Owner Display Name | `OwnerDisplayName` | Text, 255 characters; system-populated |
| AI Ready | `AIReady` | Yes/No; default No; system-computed |
| Trust Score | `TrustScore` | Whole number, 0 to 100; system-computed |
| Data Quality Status | `DataQualityStatus` | Good, Needs Review, Stale, Duplicate, Conflicting; system-computed |
| Conflict Status | `ConflictStatus` | None, Conflicting Authoritative, Conflicts With Authoritative; system-computed |
| Conflict With | `ConflictWith` | Text, 255 characters; system-computed |
| Duplicate Of | `DuplicateOf` | Text, 255 characters; system-computed |
| Content Hash | `ContentHash` | Text, 64 characters; system-computed |
| Trust Reasons | `TrustReasons` | Plain multiline text; system-computed |
| Last Validated Date | `LastValidatedDate` | Date only; system-populated |

The template preserves the policy's indexing and uniqueness settings, date
formats, numeric range and single-line text limits. SharePoint multiline text
has no equivalent to Graph's `maxLength` setting; the policy's 2,000-character
Trust Reasons limit must be enforced by the writer, not this column.

## Governance boundaries

- This is **schema provisioning only**. It does not deploy a sync, workflow,
  approval process, retention label, sensitivity label, permissions, search
  indexer or Foundry integration. New libraries must be explicitly onboarded to
  those services; creating a library does not start processing it.
- The policy requires an owner, lifecycle, authority decision and review date
  when publishing. This template does **not** enforce conditional publication
  validation. Connect an owner-approved governance process before production use.
- System-computed fields are ordinary metadata, not SharePoint calculated
  columns. They stay empty (or No for AI Ready) until a governance writer runs.
  They are not protected from editing and must not be used as security controls.
- Content Sensitivity is a choice field, **not** a Microsoft Purview sensitivity
  label. Choice values neither classify nor secure the underlying file.
- The unique Artifact ID is not automatically generated. Populate a stable,
  distinct identifier per document through your upload/governance process.
- Product Family is a Choice field for this POC, not managed metadata.
  Do not broaden the choices without also reviewing the policy and consumers.

## Regenerate or replace

[The checked-in site script](../config/knowledge-library.site-script.json) can
be inspected or registered manually. Regenerate it after changing the policy:

```powershell
.\scripts\New-KnowledgeLibrarySiteScript.ps1 `
    -OutputPath .\config\knowledge-library.site-script.json | Out-Null
.\tests\Test-KnowledgeLibraryTemplate.ps1
```

Column IDs are deterministic by internal name, and XML values are escaped.
The publisher always regenerates from policy rather than trusting a stale export.
It supports `-Title` for a versioned picker entry and `-PolicyPath` for a reviewed
alternative policy.
Custom descriptions must be between 1 and 128 characters, matching the
SharePoint site script registration limit.

Microsoft documents list designs as immutable. Prefer publishing a new
versioned title; after migration, remove the old picker entry with
`Remove-SPOListDesign -Identity <list-design-id>`. Remove its site script only
when it is no longer referenced. Replacing a template does **not** update
libraries already created from it; plan existing-library migrations separately.

## Validation

The offline PowerShell tests verify all 27 policy definitions against the
generated and checked-in template, stable IDs, XML escaping, safe defaults,
views, invalid inputs and publication using mocked SharePoint commands.
They do not connect to SharePoint. Administrator publication and the two-library
site-owner check above are required to verify the live picker experience.

References: [Add-SPOListDesign](https://learn.microsoft.com/powershell/module/microsoft.online.sharepoint.powershell/add-spolistdesign),
[site script schema](https://learn.microsoft.com/sharepoint/dev/declarative-customization/site-design-json-schema).
