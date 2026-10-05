# Runs the app from this PC for phones on any network: https://adynamic-trinh-thickly.ngrok-free.dev
# Logins doctor / doctor2 / admin; the password is in .public-password (kept out of git).
# Run:  powershell -ExecutionPolicy Bypass -File run-public.ps1 [-Reset]   (-Reset wipes all records first)
# Stop: close the three windows it opens.
param([switch]$Reset)

$root = $PSScriptRoot
$domain = "adynamic-trinh-thickly.ngrok-free.dev"
$env:CAPTURE_DEMO_PASSWORD = (Get-Content "$root\.public-password" -Raw).Trim()
$resetFlag = if ($Reset) { "--reset" } else { "" }

# API on 127.0.0.1:8000 with the stub AI worker; the built web app on 127.0.0.1:4173 (it forwards /api); ngrok in front.
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\server'; uv run --extra ocr python -m capture.devserver $resetFlag --worker stub --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\web'; npm run build; npx vite preview --host 127.0.0.1 --port 4173 --strictPort"
Start-Process ngrok -ArgumentList "http", "--domain=$domain", "4173"

Write-Host "Starting... open https://$domain in a minute."
