@echo off
chcp 65001 >nul
title LCT2026 Wine Label Search - Local Runner
cd /d "%~dp0"

:CHECK_DOCKER
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Docker Desktop не запущен или недоступен!
    echo Пожалуйста, запустите Docker Desktop и нажмите любую клавишу для повторной проверки.
    pause >nul
    goto CHECK_DOCKER
)

:CHECK_ENV
if not exist ".env" (
    echo [ИНФО] Файл .env не найден, копирую из .env.example...
    copy ".env.example" ".env" >nul
)

:MENU
cls
echo ====================================================================
echo      LCT2026 Wine Label Search - Локальная панель управления
echo      Текущая ветка: alexey_shch
echo ====================================================================
echo.
echo  [1] Запустить проект (docker compose up -d)
echo  [2] Проверить статус сервисов и готовность API
echo  [3] Перезапустить API (быстро применить изменения кода в app/)
echo  [4] Показать логи сервисов (live logs)
echo  [5] Протестировать распознавание на тестовом фото (tmp/1)
echo  [6] Восстановить базу данных из дампа (1932 товара, 224к векторов)
echo  [7] Открыть Swagger документацию в браузере (http://localhost:8030/api/docs)
echo  [8] Остановить проект (docker compose down)
echo  [0] Выход
echo.
echo ====================================================================
set /p choice="Выберите действие [1-8, 0] (по умолчанию 1): "

if "%choice%"=="" set choice=1
if "%choice%"=="1" goto START_APP
if "%choice%"=="2" goto STATUS_APP
if "%choice%"=="3" goto RESTART_API
if "%choice%"=="4" goto LOGS_APP
if "%choice%"=="5" goto TEST_SEARCH
if "%choice%"=="6" goto RESTORE_DB
if "%choice%"=="7" goto OPEN_DOCS
if "%choice%"=="8" goto STOP_APP
if "%choice%"=="0" exit /b 0

echo Неверный выбор, попробуйте снова.
timeout /t 2 >nul
goto MENU

:START_APP
echo.
echo [1/3] Запуск контейнеров...
docker compose up -d
echo.
echo [2/3] Ожидание готовности API...
for /l %%i in (1,1,30) do (
    curl -s http://127.0.0.1:8030/api/ready 2>nul | findstr /i "true" >nul
    if not errorlevel 1 (
        echo [УСПЕХ] Сервер и модели готовы к работе!
        goto APP_READY
    )
    timeout /t 1 >nul
)
echo [ПРЕДУПРЕЖДЕНИЕ] API запускается дольше обычного. Проверьте статус через пункт 4 (логи).

:APP_READY
echo.
echo ====================================================================
echo [ИНФОРМАЦИЯ]
echo   - Swagger Docs: http://localhost:8030/api/docs
echo   - Каталог товаров: http://localhost:8030/api/products
echo   - Проверка статуса: http://localhost:8030/api/ready
echo ====================================================================
echo.
pause
goto MENU

:STATUS_APP
echo.
echo === Статус контейнеров Docker ===
docker compose ps
echo.
echo === Проверка готовности API ===
curl -s http://127.0.0.1:8030/api/ready
echo.
echo.
echo === Количество товаров в базе ===
docker compose exec -T db psql -U lct -d lct2026 -c "SELECT count(*) AS products_count FROM products;" 2>nul
pause
goto MENU

:RESTART_API
echo.
echo Перезапуск контейнера API для применения изменений в app/...
docker compose restart api
echo.
echo Ожидание инициализации моделей...
timeout /t 3 >nul
curl -s http://127.0.0.1:8030/api/ready
echo.
echo [ГОТОВО] Изменения применены!
pause
goto MENU

:LOGS_APP
echo.
echo Для выхода из просмотра логов нажмите Ctrl + C.
echo.
docker compose logs -f --tail=50
goto MENU

:TEST_SEARCH
echo.
echo Отправка тестового изображения tmp/1/queries/04f3ce15.jpg в API...
echo.
curl.exe -s -X POST "http://localhost:8030/api/v1/eval/predict" -F "image=@tmp/1/queries/04f3ce15.jpg"
echo.
echo.
echo Ожидаемый результат: {"slug":"chateau-de-talu-ruzh-kaberne-sovinon-krasnoe-suhoe-14"}
echo.
pause
goto MENU

:RESTORE_DB
echo.
echo [1/3] Распаковка медиа-файлов...
if not exist "media" mkdir media
tar.exe -xzf data/media_catalog.tar.gz -C media
echo ✓ Медиа распаковано.
echo.
echo [2/3] Копирование и импорт дампа PostgreSQL...
docker compose cp data/catalog_dump.sql.gz db:/tmp/catalog_dump.sql.gz
docker compose exec -T db bash -c "gunzip -c /tmp/catalog_dump.sql.gz | psql -U lct -d lct2026 -q && rm /tmp/catalog_dump.sql.gz"
echo ✓ База данных импортирована.
echo.
echo [3/3] Перезапуск API...
docker compose restart api
echo [УСПЕХ] Каталог полностью восстановлен!
pause
goto MENU

:OPEN_DOCS
start http://localhost:8030/api/docs
goto MENU

:STOP_APP
echo.
echo Остановка всех сервисов...
docker compose down
echo Сервисы остановлены.
pause
goto MENU
