param foundryAccountName string
param foundryProjectName string
param foundryLocation string
param projectDescription string
param apiAppName string
param apiIdentityRoleDefinitionId string
param apiIdentityRoleAssignmentName string
param grantApiIdentityRole bool
param deployIdentityName string

resource account 'Microsoft.CognitiveServices/accounts@2026-09-01' existing = {
  name: foundryAccountName
}

// Not 'existing': deploying under the same name adopts the current project and updates it in place.
resource project 'Microsoft.CognitiveServices/accounts/projects@2026-09-01' = {
  parent: account
  name: foundryProjectName
  location: foundryLocation
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: foundryProjectName
    description: projectDescription
  }
}

resource apiApp 'Microsoft.Web/sites@2023-12-01' existing = {
  name: apiAppName
}

// Reuses the existing assignment's GUID name so ARM adopts it instead of creating a duplicate.
resource apiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (grantApiIdentityRole) {
  name: apiIdentityRoleAssignmentName
  scope: project
  properties: {
    principalId: apiApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', apiIdentityRoleDefinitionId)
  }
}

resource deployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: deployIdentityName
}

// The pipeline identity creates agent versions, so it needs the same data-plane role on the project.
resource deployRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, deployIdentity.id, apiIdentityRoleDefinitionId)
  scope: project
  properties: {
    principalId: deployIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', apiIdentityRoleDefinitionId)
  }
}

output projectId string = project.id
output projectEndpoint string = 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'
