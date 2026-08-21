param(
  [Parameter(Mandatory = $true)][string]$LogFile,
  [Parameter(Mandatory = $true)][string]$Phase,
  [Parameter(Mandatory = $true)][string]$Decision,
  [Parameter(Mandatory = $true)][string]$Why,
  [Parameter(Mandatory = $true)][string]$Evidence,
  [Parameter(Mandatory = $true)][string]$Result
)

$ErrorActionPreference = "Stop"

function ConvertTo-SafeCell([string]$Value) {
  $clean = $Value -replace "[`t`r`n]", " "
  if ($clean -match "^[=+\-@]") {
    return "'$clean"
  }
  return $clean
}

$parent = Split-Path -Parent $LogFile
if ($parent -and -not (Test-Path -LiteralPath $parent)) {
  New-Item -ItemType Directory -Path $parent | Out-Null
}

if (-not (Test-Path -LiteralPath $LogFile)) {
  "ts`tphase`tdecision`twhy`tevidence`tresult" | Set-Content -LiteralPath $LogFile -Encoding utf8NoBOM
}

$cells = @(
  [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"),
  (ConvertTo-SafeCell $Phase),
  (ConvertTo-SafeCell $Decision),
  (ConvertTo-SafeCell $Why),
  (ConvertTo-SafeCell $Evidence),
  (ConvertTo-SafeCell $Result)
)

($cells -join "`t") | Add-Content -LiteralPath $LogFile -Encoding utf8NoBOM
