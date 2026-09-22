"""Populate color, category, region, grape from wines_integrated.csv.

Run inside the API container or from a host with access to the database:

    docker compose exec api python -m scripts.populate_wine_details

The script matches products by slug. Products whose slug is not found in the
CSV are skipped silently.
"""

import asyncio
import csv
import os
import sys
from pathlib import Path

# Allow running as `python -m scripts.populate_wine_details` from project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.db.models.product import Product


CSV_PATH = os.environ.get(
    "WINE_CSV_PATH",
    str(Path(__file__).resolve().parents[1] / "wines_integrated.csv"),
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://lct:lct_secret@127.0.0.1:5432/lct2026",
)


def load_csv(path: str) -> dict[str, dict]:
    """Return a dict keyed by slug with wine detail values."""
    lookup: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            slug = (row.get("Slug") or "").strip()
            if not slug:
                continue
            lookup[slug] = {
                "color": (row.get("Цвет") or "").strip() or None,
                "category": (row.get("Категория") or "").strip() or None,
                "region": (row.get("Регион") or "").strip() or None,
                "grape": (row.get("Сорт винограда") or "").strip() or None,
                "description": (row.get("Описание") or "").strip() or None,
            }
    return lookup


async def main() -> None:
    print(f"Loading CSV from {CSV_PATH} ...")
    lookup = load_csv(CSV_PATH)
    print(f"  {len(lookup)} wines loaded from CSV")

    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    updated = 0
    skipped = 0

    async with async_session() as session:
        result = await session.scalars(select(Product))
        products = list(result)
        print(f"  {len(products)} products in database")

        for product in products:
            csv_data = lookup.get(product.slug)
            if csv_data is None:
                skipped += 1
                continue

            changes = {}
            if csv_data["color"] and not product.color:
                changes["color"] = csv_data["color"]
            if csv_data["category"] and not product.category:
                changes["category"] = csv_data["category"]
            if csv_data["region"] and not product.region:
                changes["region"] = csv_data["region"]
            if csv_data["grape"] and not product.grape:
                changes["grape"] = csv_data["grape"]
            if csv_data["description"] and (not product.description or product.description == ""):
                changes["description"] = csv_data["description"]

            if changes:
                await session.execute(
                    update(Product)
                    .where(Product.id == product.id)
                    .values(**changes)
                )
                updated += 1

        await session.commit()

    await engine.dispose()
    print(f"Done: {updated} products updated, {skipped} skipped (no CSV match)")


if __name__ == "__main__":
    asyncio.run(main())
