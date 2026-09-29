param(
  [Parameter(Mandatory=$true, Position=0)]
  [string]$Pattern,

  [Parameter(Position=1, ValueFromRemainingArguments=$true)]
  [string[]]$Paths = @('.')
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
$files = New-Object System.Collections.ArrayList
foreach ($relative in $Paths) {
  $target = if ([System.IO.Path]::IsPathRooted($relative)) { $relative } else { Join-Path $Root $relative }
  if (Test-Path -LiteralPath $target -PathType Leaf) {
    [void]$files.Add((Get-Item -LiteralPath $target))
  } elseif (Test-Path -LiteralPath $target -PathType Container) {
    Get-ChildItem -LiteralPath $target -Recurse -File -ErrorAction Stop | ForEach-Object {
      if ($_.FullName -notmatch '[\\/](\.git|\.runtime|__pycache__|\.pytest_cache)[\\/]') { [void]$files.Add($_) }
    }
  } else {
    Write-Error "SEARCH_PATH_NOT_FOUND:$relative"
    exit 2
  }
}
$matches = @($files | Select-String -Pattern $Pattern -AllMatches -ErrorAction SilentlyContinue)
foreach ($m in $matches) {
  $full = [System.IO.Path]::GetFullPath($m.Path)
  $prefix = $Root.TrimEnd('\\') + '\\'
  if ($full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { $rel = $full.Substring($prefix.Length) } else { $rel = $full }
  $rel = $rel.Replace('\\','/')
  Write-Output ("{0}:{1}:{2}" -f $rel, $m.LineNumber, $m.Line.Trim())
}
exit $(if ($matches.Count -gt 0) { 0 } else { 1 })
