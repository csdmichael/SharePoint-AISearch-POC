param appName string
param planName string
param location string
param runtime string
param startupCommand string
param healthPath string
param appSettings { *: string }

resource plan 'Microsoft.Web/serverfarms@2023-12-01' existing = {
  name: planName
}

resource site 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  kind: 'app,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: runtime
      appCommandLine: startupCommand
      healthCheckPath: healthPath
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
    }
  }
}

// The appsettings PUT replaces the entire settings collection: any setting not listed in appSettings is removed.
resource siteSettings 'Microsoft.Web/sites/config@2023-12-01' = {
  parent: site
  name: 'appsettings'
  properties: appSettings
}

output defaultHostName string = site.properties.defaultHostName
output identityPrincipalId string = site.identity.principalId
