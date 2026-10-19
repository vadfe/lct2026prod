#!/usr/bin/env python3
"""Скорость и эффект этапа близнецов на контрольных фото.

Отправляет каждое фото из queries.tsv в POST /api/cascade/search (по одному, как participant_test.sh) и из одного
прогона считает время с этапом близнецов и без него: этап отчитывается отдельно (`timings.twin_ms`), поэтому
«без этапа» = total_ms - twin_ms. Для сверки можно сделать второй прогон с ENABLE_CASCADE_TWIN_RESOLVER=false.

    python scripts/twin_timing.py --images-dir ../eval/queries --manifest ../eval/queries.tsv \\
        --mapping ../eval/mapping.json --endpoint http://127.0.0.1:8080/api/cascade/search --output twin_timing.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
import urllib.request
import uuid
from pathlib import Path


def post_image(endpoint: str, path: Path, timeout: float) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="k"\r\n\r\n3\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def describe(name: str, values: list[float]) -> str:
    if not values:
        return f"{name}: нет данных"
    return (f"{name}: среднее {statistics.mean(values):.0f}, медиана {statistics.median(values):.0f}, "
            f"p90 {percentile(values, 0.9):.0f}, p95 {percentile(values, 0.95):.0f}, max {max(values):.0f} мс")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, help="mapping.json: тогда считается и точность")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/api/cascade/search")
    parser.add_argument("--output", type=Path, default=Path("twin_timing.csv"))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    with args.manifest.open(encoding="utf-8") as handle:
        queries = list(csv.DictReader(handle, delimiter="\t"))
    expected = {}
    if args.mapping:
        expected = {case["query_id"]: case.get("expected_slug") for case in json.loads(args.mapping.read_text(encoding="utf-8"))["cases"]}

    rows = []
    for query in queries:
        started = time.perf_counter()
        try:
            data = post_image(args.endpoint, args.images_dir / query["image_path"], args.timeout)
        except Exception as exc:  # noqa: BLE001 — a failed request is recorded, the run goes on
            print(f"{query['query_id']}: ошибка запроса: {exc}")
            continue
        wall_ms = (time.perf_counter() - started) * 1000
        timings, decision = data["timings"], data["decision"]
        twin_ms = timings.get("twin_ms")
        winner = (data.get("winner") or {}).get("slug")
        top = data.get("final_results") or []
        rows.append({
            "query_id": query["query_id"],
            "expected_slug": expected.get(query["query_id"]),
            "predicted_slug": winner,
            "correct": winner == expected.get(query["query_id"]) if expected else "",
            "wall_ms": round(wall_ms, 1),
            "total_ms": timings["total_ms"],
            "twin_ms": twin_ms if twin_ms is not None else "",
            "total_without_twin_ms": round(timings["total_ms"] - (twin_ms or 0.0), 1),
            "twin_resolution": decision.get("twin_resolution") or "",
            "fusion_top3": " | ".join(f"{c['slug']}:{c['fusion_score']}" for c in top[:3]),
        })
        print(f"{query['query_id']}: {wall_ms:.0f} мс, близнецы: {decision.get('twin_resolution') or '—'}")

    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["query_id"])
        writer.writeheader()
        writer.writerows(rows)

    ran = [row for row in rows if row["twin_ms"] != ""]
    changed = [row for row in ran if row["twin_resolution"].startswith("Выбран")]
    print("=" * 78)
    print(f"Запросов: {len(rows)}; этап близнецов запускался: {len(ran)}; поменял ответ или подтвердил выбор: {len(changed)}")
    if expected:
        print(f"Точность: {sum(row['correct'] is True for row in rows)}/{len(rows)}")
    print(describe("Время этапа близнецов (где запускался)", [float(row["twin_ms"]) for row in ran]))
    print(describe("Полное время сервера с этапом", [row["total_ms"] for row in rows]))
    print(describe("Полное время сервера без этапа", [row["total_without_twin_ms"] for row in rows]))
    print(describe("Время запроса у клиента", [row["wall_ms"] for row in rows]))
    for row in ran:
        mark = "" if row["correct"] == "" else ("верно" if row["correct"] else "ОШИБКА")
        print(f"  {row['query_id']} {mark} {float(row['twin_ms']):.0f} мс — {row['twin_resolution']}")
    print(f"Подробности: {args.output}")


if __name__ == "__main__":
    main()
