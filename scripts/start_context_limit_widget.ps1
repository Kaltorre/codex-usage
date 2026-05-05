$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Widget = Join-Path $ScriptDir "context_limit_widget.py"
$Python = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}
Start-Process -FilePath $Python -ArgumentList (@($Widget) + $args) | Out-Null
