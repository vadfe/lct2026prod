# 1. Подготовка

## 1.1. Установка Git и Git LFS

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y git git-lfs

# macOS
brew install git git-lfs

# Инициализация (один раз на машину)
git lfs install
```

## 1.2. Клонирование и скачивание моделей

```bash
git clone <url-репозитория>
cd lct2026prod
git lfs pull
```

> В репозитории вместо моделей лежат pointer-файлы (~100 байт). `git lfs pull` заменяет их на реальные файлы (сотни МБ).

Проверка размера:
```bash
ls -lh models/yolo_label.pt web/models/yolov8_label.onnx
```
Если видите ~100 байт — LFS не сработал, `git lfs pull` не выполнен.

## 1.3. Проверка контрольных сумм

```bash
sha256sum --check models/MODEL_MANIFEST.sha256
```

Ожидаемый вывод: `models/...: OK` для всех файлов.

## 1.4. Возможные проблемы

### Проблема: `FAILED`, но размер файлов нормальный

Возможно, разработчик обновил модели, но не пересчитал хеши в манифесте. Проверим, что модели рабочие:

```bash
python3 -m venv /tmp/test-models
source /tmp/test-models/bin/activate
pip install --upgrade pip
pip install torch torchvision ultralytics

python -c "
from ultralytics import YOLO
model = YOLO('models/yolo_label.pt')
print('OK, классы:', list(model.names.values()))
"

deactivate
rm -rf /tmp/test-models
```

Если модель загрузилась — файл рабочий, проблема только в манифесте. Можно игнорировать ошибку.

### Проблема: `sha256sum` ругается на пути

`sha256sum` ищет файлы строго по тем путям, что записаны в манифесте. Если в файле `models/yolo_label.pt`, а вы запускаете проверку из другой директории — будет `FAILED` даже для целых файлов.

**Решение:** всегда запускать из корня репозитория:
```bash
cd /путь/к/lct2026prod
sha256sum --check models/MODEL_MANIFEST.sha256
```

### Проблема: `git lfs pull` повторно скачивает битые файлы

Если скачивание файлов по какой-то причине прервано - можно запустить pull повторно. Git LFS кэширует объекты в `.git/lfs/objects/`. Битый объект может застрять в кэше.

```bash
# Удалить битые файлы
rm models/yolo_label.pt web/models/yolov8_label.onnx

# Очистить кэш и скачать заново
git lfs prune
git lfs pull
```

Если не помогло:
```bash
rm -rf .git/lfs/
git lfs pull
```

## 1.5. Проверка CUDA (для GPU)
Если у вас есть NVIDIA GPU и вы планируете использовать её (настоятельно рекомендуется — без GPU нейросети работают в 10-100 раз медленнее):

    `nvidia-smi`

Должна показать таблицу с вашей GPU и строку CUDA Version: X.Y (не ниже 12.4).

    Важно: CUDA Version в nvidia-smi — это максимальная версия CUDA, которую поддерживает драйвер. Для проекта нужна версия не ниже 12.4. Драйвер обратно совместим: если он поддерживает CUDA 13.0, контейнеры с CUDA 12.4 и 12.8 будут работать.

Если nvidia-smi не работает — драйвер не установлен

# 2. Установка NVIDIA Container Toolkit
https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

Для того чтобы Docker-контейнеры могли использовать видеокарту, необходимо установить NVIDIA Container Toolkit.


## 2.1. Добавить GPG-ключ
```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
```

## 2.2. Добавить репозиторий
```bash
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
```

## 2.3. Установить и настроить
```bash
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

## 2.4. Проверить работу
```
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```
*Если вы увидите таблицу с вашей видеокартой (название, драйвер, память) — поздравляю, мост построен!*

# 3. Запуск приложения
```
docker compose up --build
```

## Readiness check (БД + модели загружены в GPU)
```
curl http://localhost:8030/api/ready
```