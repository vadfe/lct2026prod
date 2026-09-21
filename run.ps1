# ==============================================================================
# LCT2026 Wine Label Search - PowerShell Interactive Runner
# ==============================================================================

Set-Location $PSScriptRoot

function Test-Docker {
    docker info >$null 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Ensure-Docker {
    while (-not (Test-Docker)) {
        Write-Host ""
        Write-Host "[!] Docker Desktop is not running or still starting!" -ForegroundColor Red
        Write-Host "Please start Docker Desktop (green whale icon in taskbar)." -ForegroundColor Yellow
        Write-Host "Press [Enter] to re-check..." -NoNewline
        Read-Host
    }
}

Ensure-Docker

if (-not (Test-Path ".env")) {
    Write-Host "[INFO] File .env not found, copying from .env.example..." -ForegroundColor Cyan
    Copy-Item ".env.example" ".env"
}

function Show-Menu {
    Clear-Host
    Write-Host "====================================================================" -ForegroundColor Cyan
    Write-Host "     LCT2026 Wine Label Search - Control Panel" -ForegroundColor Green
    Write-Host "     Branch: alexey_shch" -ForegroundColor Yellow
    Write-Host "====================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] Start Project          (docker compose up -d)" -ForegroundColor White
    Write-Host "  [2] Check Status           (containers, API & database)" -ForegroundColor White
    Write-Host "  [3] Restart API            (apply code edits from app/)" -ForegroundColor White
    Write-Host "  [4] API Live Logs          (stream logs in real-time)" -ForegroundColor White
    Write-Host "  [5] Test Wine Search       (test image query)" -ForegroundColor White
    Write-Host "  [6] Open Swagger Docs      (http://localhost:8030/api/docs)" -ForegroundColor White
    Write-Host "  [7] Restore Database Dump  (2,037 wines, 236k vectors)" -ForegroundColor White
    Write-Host "  [8] Stop Project           (docker compose down)" -ForegroundColor White
    Write-Host "  [0] Exit" -ForegroundColor Gray
    Write-Host ""
    Write-Host "====================================================================" -ForegroundColor Cyan
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Select option [0-8] (default: 1)"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" {
            Write-Host "`n[1/2] Starting containers (docker compose up -d)..." -ForegroundColor Cyan
            docker compose up -d
            Write-Host "`n[2/2] Waiting for API & ML models to initialize..." -ForegroundColor Cyan
            $ready = $false
            for ($i = 1; $i -le 30; $i++) {
                try {
                    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8030/api/ready" -TimeoutSec 2 -ErrorAction SilentlyContinue
                    if ($resp.ready -eq $true) {
                        $ready = $true
                        break
                    }
                } catch {}
                Start-Sleep -Seconds 1
            }
            if ($ready) {
                Write-Host "`n[SUCCESS] Project is fully ready!" -ForegroundColor Green
                Write-Host "  - Swagger Docs : http://localhost:8030/api/docs" -ForegroundColor Yellow
                Write-Host "  - Ready Check  : http://localhost:8030/api/ready" -ForegroundColor Yellow
            } else {
                Write-Host "`n[!] API is still initializing. Check status via [2] or logs via [4]." -ForegroundColor Yellow
            }
            Write-Host "`nPress Enter to return to menu..." -NoNewline
            Read-Host
        }
        "2" {
            Write-Host "`n=== Docker Containers ===" -ForegroundColor Cyan
            docker compose ps
            Write-Host "`n=== API Ready Status ===" -ForegroundColor Cyan
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:8030/api/ready" -ErrorAction Stop
                Write-Host "Ready: $($r.ready) | Database: $($r.database) | Models: $($r.models)" -ForegroundColor Green
            } catch {
                Write-Host "API is currently unreachable." -ForegroundColor Red
            }
            Write-Host "`n=== Database Records (PostgreSQL) ===" -ForegroundColor Cyan
            docker compose exec -T db psql -U lct -d lct2026 -c "SELECT count(*) AS products_count FROM products; SELECT count(*) AS embeddings_count FROM product_embeddings;"
            Write-Host "`nPress Enter to return to menu..." -NoNewline
            Read-Host
        }
        "3" {
            Write-Host "`nRestarting API container to apply app/ code changes..." -ForegroundColor Cyan
            docker compose restart api
            Write-Host "Waiting for models..." -ForegroundColor Cyan
            Start-Sleep -Seconds 3
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:8030/api/ready" -ErrorAction Stop
                Write-Host "[SUCCESS] Service restarted and ready!" -ForegroundColor Green
            } catch {
                Write-Host "Service is restarting..." -ForegroundColor Yellow
            }
            Write-Host "`nPress Enter to return to menu..." -NoNewline
            Read-Host
        }
        "4" {
            Write-Host "`nPress Ctrl + C to exit logs`n" -ForegroundColor Yellow
            docker compose logs -f --tail=50
        }
        "5" {
            Write-Host "`nTesting wine bottle recognition for tmp/1/queries/04f3ce15.jpg..." -ForegroundColor Cyan
            $res = curl.exe -s -X POST "http://localhost:8030/api/v1/eval/predict" -F "image=@tmp/1/queries/04f3ce15.jpg"
            Write-Host "API Response: $res" -ForegroundColor Green
            Write-Host "Expected    : {""slug"":""chateau-de-talu-ruzh-kaberne-sovinon-krasnoe-suhoe-14""}" -ForegroundColor Yellow
            Write-Host "`nPress Enter to return to menu..." -NoNewline
            Read-Host
        }
        "6" {
            Start-Process "http://localhost:8030/api/docs"
        }
        "7" {
            Write-Host "`n[1/3] Extracting media crops..." -ForegroundColor Cyan
            if (-not (Test-Path "media")) { New-Item -ItemType Directory -Path "media" -Force }
            tar.exe -xzf data/media_catalog.tar.gz -C media
            Write-Host "[2/3] Copying and importing database dump..." -ForegroundColor Cyan
            docker compose cp data/catalog_dump.sql.gz db:/tmp/catalog_dump.sql.gz
            docker compose exec -T db bash -c "gunzip -c /tmp/catalog_dump.sql.gz | psql -U lct -d lct2026 -q && rm /tmp/catalog_dump.sql.gz"
            Write-Host "[3/3] Restarting API..." -ForegroundColor Cyan
            docker compose restart api
            Write-Host "`n[SUCCESS] Catalog restored successfully (2,037 products)!" -ForegroundColor Green
            Write-Host "`nPress Enter to return to menu..." -NoNewline
            Read-Host
        }
        "8" {
            Write-Host "`nStopping all services (docker compose down)..." -ForegroundColor Yellow
            docker compose down
            Write-Host "Services stopped." -ForegroundColor Green
            Write-Host "`nPress Enter to return to menu..." -NoNewline
            Read-Host
        }
        "0" {
            exit 0
        }
        default {
            Write-Host "Invalid choice, please try again." -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
