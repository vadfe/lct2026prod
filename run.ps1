# ==============================================================================
# LCT2026 Wine Label Search - PowerShell Interactive Runner
# ==============================================================================

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location $PSScriptRoot

function Test-Docker {
    docker info >$null 2>&1
    return ($LASTEXITCODE -eq 0)
}

function Ensure-Docker {
    while (-not (Test-Docker)) {
        Write-Host ""
        Write-Host "[!] Docker Desktop не запущен или еще запускается!" -ForegroundColor Red
        Write-Host "Пожалуйста, запустите Docker Desktop (зеленый значок в трее)." -ForegroundColor Yellow
        Write-Host "Нажмите [Enter] для повторной проверки..." -NoNewline
        Read-Host
    }
}

Ensure-Docker

if (-not (Test-Path ".env")) {
    Write-Host "[ИНФО] Файл .env не найден, копирую из .env.example..." -ForegroundColor Cyan
    Copy-Item ".env.example" ".env"
}

function Show-Menu {
    Clear-Host
    Write-Host "====================================================================" -ForegroundColor Cyan
    Write-Host "     LCT2026 Wine Label Search - Локальная панель управления" -ForegroundColor Green
    Write-Host "     Текущая ветка: alexey_shch" -ForegroundColor Yellow
    Write-Host "====================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  [1] Запустить проект (docker compose up -d)" -ForegroundColor White
    Write-Host "  [2] Проверить статус сервисов и базы данных" -ForegroundColor White
    Write-Host "  [3] Перезапустить API (применить правки кода в app/)" -ForegroundColor White
    Write-Host "  [4] Показать логи API в реальном времени" -ForegroundColor White
    Write-Host "  [5] Протестировать распознавание вина (тестовое фото)" -ForegroundColor White
    Write-Host "  [6] Открыть Swagger документацию в браузере" -ForegroundColor White
    Write-Host "  [7] Восстановить базу данных из дампа (2037 вин, 236к векторов)" -ForegroundColor White
    Write-Host "  [8] Остановить проект (docker compose down)" -ForegroundColor White
    Write-Host "  [0] Выход" -ForegroundColor Gray
    Write-Host ""
    Write-Host "====================================================================" -ForegroundColor Cyan
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Выберите действие [0-8] (по умолчанию 1)"
    if ([string]::IsNullOrWhiteSpace($choice)) { $choice = "1" }

    switch ($choice) {
        "1" {
            Write-Host "`n[1/2] Запуск контейнеров..." -ForegroundColor Cyan
            docker compose up -d
            Write-Host "[2/2] Ожидание инициализации API и моделей..." -ForegroundColor Cyan
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
                Write-Host "`n[УСПЕХ] Проект полностью готов к работе!" -ForegroundColor Green
                Write-Host "  - Swagger Docs: http://localhost:8030/api/docs" -ForegroundColor Yellow
                Write-Host "  - Проверка API: http://localhost:8030/api/ready" -ForegroundColor Yellow
            } else {
                Write-Host "`n[!] API еще запускается. Проверьте статус через пункт 2 или логи (пункт 4)." -ForegroundColor Yellow
            }
            Write-Host "`nНажмите Enter для возврата в меню..." -NoNewline
            Read-Host
        }
        "2" {
            Write-Host "`n=== Контейнеры Docker ===" -ForegroundColor Cyan
            docker compose ps
            Write-Host "`n=== Статус готовности API ===" -ForegroundColor Cyan
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:8030/api/ready" -ErrorAction Stop
                Write-Host "Ready: $($r.ready) | Database: $($r.database) | Models: $($r.models)" -ForegroundColor Green
            } catch {
                Write-Host "API пока недоступен." -ForegroundColor Red
            }
            Write-Host "`n=== Количество товаров в базе PostgreSQL ===" -ForegroundColor Cyan
            docker compose exec -T db psql -U lct -d lct2026 -c "SELECT count(*) AS products_count FROM products; SELECT count(*) AS embeddings_count FROM product_embeddings;"
            Write-Host "`nНажмите Enter для возврата в меню..." -NoNewline
            Read-Host
        }
        "3" {
            Write-Host "`nПерезапуск контейнера API для применения изменений в app/..." -ForegroundColor Cyan
            docker compose restart api
            Write-Host "Ожидание готовности моделей..." -ForegroundColor Cyan
            Start-Sleep -Seconds 3
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:8030/api/ready" -ErrorAction Stop
                Write-Host "[УСПЕХ] Сервис перезапущен и готов!" -ForegroundColor Green
            } catch {
                Write-Host "Сервис перезапускается..." -ForegroundColor Yellow
            }
            Write-Host "`nНажмите Enter для возврата в меню..." -NoNewline
            Read-Host
        }
        "4" {
            Write-Host "`nДля выхода из логов нажмите Ctrl + C`n" -ForegroundColor Yellow
            docker compose logs -f --tail=50
        }
        "5" {
            Write-Host "`nТестирование распознавания бутылки tmp/1/queries/04f3ce15.jpg..." -ForegroundColor Cyan
            $res = curl.exe -s -X POST "http://localhost:8030/api/v1/eval/predict" -F "image=@tmp/1/queries/04f3ce15.jpg"
            Write-Host "Ответ бэкенда: $res" -ForegroundColor Green
            Write-Host "Ожидаемый ответ: {""slug"":""chateau-de-talu-ruzh-kaberne-sovinon-krasnoe-suhoe-14""}" -ForegroundColor Yellow
            Write-Host "`nНажмите Enter для возврата в меню..." -NoNewline
            Read-Host
        }
        "6" {
            Start-Process "http://localhost:8030/api/docs"
        }
        "7" {
            Write-Host "`n[1/3] Распаковка медиа-кропов..." -ForegroundColor Cyan
            if (-not (Test-Path "media")) { New-Item -ItemType Directory -Path "media" -Force }
            tar.exe -xzf data/media_catalog.tar.gz -C media
            Write-Host "[2/3] Копирование и импорт дампа базы..." -ForegroundColor Cyan
            docker compose cp data/catalog_dump.sql.gz db:/tmp/catalog_dump.sql.gz
            docker compose exec -T db bash -c "gunzip -c /tmp/catalog_dump.sql.gz | psql -U lct -d lct2026 -q && rm /tmp/catalog_dump.sql.gz"
            Write-Host "[3/3] Перезапуск API..." -ForegroundColor Cyan
            docker compose restart api
            Write-Host "`n[УСПЕХ] Каталог успешно восстановлен!" -ForegroundColor Green
            Write-Host "`nНажмите Enter для возврата в меню..." -NoNewline
            Read-Host
        }
        "8" {
            Write-Host "`nОстановка всех сервисов (docker compose down)..." -ForegroundColor Yellow
            docker compose down
            Write-Host "Сервисы остановлены." -ForegroundColor Green
            Write-Host "`nНажмите Enter для возврата в меню..." -NoNewline
            Read-Host
        }
        "0" {
            exit 0
        }
        default {
            Write-Host "Неверный выбор, попробуйте снова." -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
    }
}
