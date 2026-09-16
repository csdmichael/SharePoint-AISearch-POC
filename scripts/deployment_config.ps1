function Import-DeploymentConfig {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path $Path)) { throw "Deployment config not found: $Path" }
    try {
        return Get-Content $Path -Raw | ConvertFrom-Json
    }
    catch {
        throw "Deployment config is not valid JSON: $Path. $($_.Exception.Message)"
    }
}

function Get-DeploymentConfigValue {
    param(
        [Parameter(Mandatory)][object]$Config,
        [Parameter(Mandatory)][string]$Path
    )

    $value = $Config
    foreach ($segment in $Path.Split('.')) {
        if ($null -eq $value -or $value.PSObject.Properties.Name -notcontains $segment) {
            throw "Deployment config is missing '$Path'."
        }
        $value = $value.$segment
    }
    if ($null -eq $value -or ($value -is [string] -and [string]::IsNullOrWhiteSpace($value))) {
        throw "Deployment config value '$Path' is empty."
    }
    return $value
}

function Resolve-DeploymentPath {
    param(
        [Parameter(Mandatory)][string]$RepositoryRoot,
        [Parameter(Mandatory)][string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) { return $Path }
    return Join-Path $RepositoryRoot ($Path -replace '/', [IO.Path]::DirectorySeparatorChar)
}