$ErrorActionPreference = "Stop"
$repo = "liaoyuqing/clawhunt-2191-link-discovery"
$tok = Get-Content "_ghtok.txt" -Raw
$h = @{ Authorization = "token $tok"; Accept = "application/vnd.github+json"; "User-Agent" = "delivery-2191" }
$root = (Get-Location).Path
$exclude = @("_ghtok.txt", ".git")
$files = Get-ChildItem -Recurse -File | Where-Object {
  $rel = $_.FullName.Substring($root.Length + 1).Replace("\", "/")
  ($exclude -notcontains $rel) -and
  ($rel -notmatch "(^|/)(__pycache__|.pytest_cache|logs|.git)/") -and
  ($rel -notmatch ".pyc$") -and
  ($rel -notmatch "^logs/")
}
$results = @()
foreach ($f in $files) {
  $rel = $f.FullName.Substring($root.Length + 1).Replace("\", "/")
  $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
  $b64 = [Convert]::ToBase64String($bytes)
  $body = @{ message = "Add " + $rel; content = $b64; branch = "main" } | ConvertTo-Json -Compress
  $uri = "https://api.github.com/repos/$repo/contents/" + $rel
  try {
    $r = Invoke-RestMethod -Uri $uri -Headers $h -Method Put -Body $body -ContentType "application/json"
    $results += ("OK   " + $rel)
  } catch {
    $code = $_.Exception.Response.StatusCode.value__
    $msg = ""
    try { $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream()); $msg = $sr.ReadToEnd() } catch {}
    $results += ("FAIL " + $code + " " + $rel + " :: " + $msg)
  }
}
$results | ForEach-Object { $_ }
"TOTAL=" + $files.Count
