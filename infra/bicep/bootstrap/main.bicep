param deployIdentityName string
param deployIdentityIssuer string

@description('OIDC subject the federated credential trusts, e.g. repo:<org>/<repo>:environment:<name>.')
param deployIdentitySubject string

@description('OIDC audience, e.g. api://AzureADTokenExchange for GitHub Actions.')
param deployIdentityAudience string

param grantContributorOnResourceGroup bool
param grantUserAccessAdministratorOnFoundryAccount bool
param foundryAccountName string
param contributorRoleDefinitionId string
param userAccessAdministratorRoleDefinitionId string
param storageBlobDataContributorRoleDefinitionId string
param createTerraformState bool
param terraformStateAccountName string
param terraformStateContainerName string
param terraformStateSkuName string
param location string

resource userAssignedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: deployIdentityName
  location: location
}

// Name derived from the subject with uniqueString: stable across deployments and free of special characters.
resource federatedCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: userAssignedIdentity
  name: 'fic-${uniqueString(deployIdentitySubject)}'
  properties: {
    issuer: deployIdentityIssuer
    subject: deployIdentitySubject
    audiences: [
      deployIdentityAudience
    ]
  }
}

resource contributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantContributorOnResourceGroup) {
  name: guid(resourceGroup().id, userAssignedIdentity.id, contributorRoleDefinitionId)
  scope: resourceGroup()
  properties: {
    principalId: userAssignedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleDefinitionId)
  }
}

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2026-09-01' existing = {
  name: foundryAccountName
}

resource uaaAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantUserAccessAdministratorOnFoundryAccount) {
  name: guid(foundryAccount.id, userAssignedIdentity.id, userAccessAdministratorRoleDefinitionId)
  scope: foundryAccount
  properties: {
    principalId: userAssignedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', userAccessAdministratorRoleDefinitionId)
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = if (createTerraformState) {
  name: terraformStateAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: terraformStateSkuName
  }
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobServices 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = if (createTerraformState) {
  parent: storageAccount
  name: 'default'
}

resource terraformStateContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = if (createTerraformState) {
  parent: blobServices
  name: terraformStateContainerName
  properties: {
    publicAccess: 'None'
  }
}

resource storageBlobAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createTerraformState) {
  name: guid(storageAccount.id, userAssignedIdentity.id, storageBlobDataContributorRoleDefinitionId)
  scope: storageAccount
  properties: {
    principalId: userAssignedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleDefinitionId)
  }
}

output clientId string = userAssignedIdentity.properties.clientId
output principalId string = userAssignedIdentity.properties.principalId

// Blank when no Terraform state account is created.
output terraformStateStorageAccountName string = createTerraformState ? terraformStateAccountName : ''
