import csv
import os
import glob
import re

class WineCatalog:
    def __init__(self, csv_path: str = r"D:\VINA\data\wines_integrated.csv", uploads_dir: str = r"D:\VINA\media"):
        """
        Инициализация каталога вин.
        Автоматически определяет современную базу 2 037 товаров (как в VINA2 / LCT2026),
        либо откатывается к Strapi CSV при необходимости.
        """
        self.csv_path = csv_path
        self.uploads_dir = uploads_dir
        self.wines_by_slug = {}
        self.upload_files = {}

        # 1. Проверяем наличие полной базы 2037 товаров
        full_json = r"D:\VINA\data\products_catalog.json"
        full_csv = r"D:\VINA\data\wines_integrated.csv"
        media_products = r"D:\VINA\media\products"

        if os.path.isfile(full_json) and os.path.isdir(media_products):
            self._load_full_catalog(full_json, full_csv, media_products)
        else:
            self._index_uploads()
            self._load_legacy_catalog()

    def _load_full_catalog(self, json_path: str, csv_path: str, media_dir: str):
        print(f"[WineCatalog] Быстрая загрузка полной базы из {json_path}...")
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            products = json.load(f)

        df_by_slug = {}
        if os.path.isfile(csv_path):
            try:
                import pandas as pd
                df = pd.read_csv(csv_path)
                df_by_slug = {r['Slug']: r for _, r in df.iterrows() if pd.notna(r.get('Slug'))}
            except Exception as e:
                print(f"[WineCatalog] Предупреждение при чтении {csv_path}: {e}")

        for p in products:
            slug = p.get("slug")
            if not slug:
                continue

            extra = df_by_slug.get(slug, {})
            prod_id = p.get("id")
            src_path = os.path.join(media_dir, prod_id, "source.webp")
            lbl_path = os.path.join(media_dir, prod_id, "label.webp")

            self.wines_by_slug[slug] = {
                "name": str(extra.get("Название вина") or p.get("title") or slug),
                "winery": str(extra.get("Винодельня") or p.get("manufacturer") or ""),
                "category": str(extra.get("Категория") or ""),
                "color": str(extra.get("Цвет") or ""),
                "region": str(extra.get("Регион") or ""),
                "grape": str(extra.get("Сорт винограда") or ""),
                "description": str(extra.get("Описание") or p.get("description") or ""),
                "slug": slug,
                "image_path": src_path if os.path.isfile(src_path) else "",
                "label_path": lbl_path if os.path.isfile(lbl_path) else "",
            }

        print(f"[WineCatalog] Успешно загружено {len(self.wines_by_slug)} вин с полными метаданными и изображениями.")

    def _index_uploads(self):
        if not os.path.exists(self.uploads_dir):
            return
            
        for root, _, files in os.walk(self.uploads_dir):
            for file in files:
                if file.lower().endswith(('.webp', '.png', '.jpg', '.jpeg')):
                    if file.startswith(('thumbnail_', 'small_', 'medium_', 'large_')):
                        continue
                    self.upload_files[file] = os.path.join(root, file)

    def _clean_str(self, s: str) -> str:
        return re.sub(r'[^a-z0-9]', '', s.lower())

    def _find_image_path(self, photo_name: str, slug: str) -> str:
        if not photo_name:
            return ""
        if photo_name in self.upload_files:
            return self.upload_files[photo_name]
        name_without_ext = os.path.splitext(photo_name)[0]
        for file_name, full_path in self.upload_files.items():
            if file_name.startswith(name_without_ext):
                return full_path
        for file_name, full_path in self.upload_files.items():
            if file_name.startswith(slug) or file_name.startswith(slug.replace('-', '_')):
                return full_path
        clean_slug = self._clean_str(slug)
        for file_name, full_path in self.upload_files.items():
            clean_file = self._clean_str(os.path.splitext(file_name)[0])
            if clean_file[:-10] == clean_slug or clean_slug in clean_file:
                return full_path
        return ""

    def _load_legacy_catalog(self):
        if not os.path.exists(self.csv_path):
            return
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            for row in reader:
                if len(row) < 9:
                    continue
                slug = row[7].strip()
                if not slug:
                    continue
                photo_name = row[8].strip()
                image_path = self._find_image_path(photo_name, slug)
                self.wines_by_slug[slug] = {
                    "name": row[0].strip(),
                    "category": row[1].strip(),
                    "color": row[2].strip(),
                    "region": row[3].strip(),
                    "grape": row[4].strip(),
                    "description": row[5].strip(),
                    "winery": row[6].strip(),
                    "slug": slug,
                    "photo_name_csv": photo_name,
                    "image_path": image_path
                }

    def get_wine(self, slug: str) -> dict:
        return self.wines_by_slug.get(slug)

    def get_all_wines(self) -> list:
        return list(self.wines_by_slug.values())

    def get_wines_with_images(self) -> list:
        return [w for w in self.wines_by_slug.values() if w.get("image_path")]
