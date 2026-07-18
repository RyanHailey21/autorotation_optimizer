param(
    [switch]$Force,
    [switch]$RefreshPolar,
    [ValidateSet("neuralfoil", "fallback")]
    [string]$Backend = "neuralfoil",
    [string[]]$Airfoils = @(),
    [ValidateRange(1, 64)]
    [int]$Jobs = 4
)

$ErrorActionPreference = "Stop"
$windowsRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$linuxRoot = (wsl.exe --cd $windowsRoot pwd).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to translate the project path for WSL."
}

$runnerArguments = @("--backend", $Backend, "--jobs", $Jobs)
if ($Force) { $runnerArguments += "--force" }
if ($RefreshPolar) { $runnerArguments += "--refresh-polar" }
if ($Airfoils.Count -gt 0) {
    foreach ($airfoil in $Airfoils) {
        if ($airfoil -notmatch '^NACA\d{4}$') {
            throw "Invalid airfoil '$airfoil'. Expected a name such as NACA2412."
        }
    }
    $runnerArguments += "--airfoils"
    $runnerArguments += $Airfoils
}
$argumentText = $runnerArguments -join " "

wsl bash -lc "cd '$linuxRoot' && exec bash ./run.sh $argumentText"
if ($LASTEXITCODE -ne 0) {
    throw "Optimization failed with exit code $LASTEXITCODE."
}
