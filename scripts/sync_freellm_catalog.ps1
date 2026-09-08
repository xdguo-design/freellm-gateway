param(
    [Parameter(Mandatory = $true)] [string] $Export,
    [Parameter(Mandatory = $true)] [string] $SiteRepo,
    [switch] $Check,
    [switch] $Build
)

$arguments = @("scripts/sync_freellm_catalog.py", "--export", $Export, "--site-repo", $SiteRepo)
if ($Check) { $arguments += "--check" }
if ($Build) { $arguments += "--build" }
python @arguments
exit $LASTEXITCODE
