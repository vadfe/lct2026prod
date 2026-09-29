"""Per-photo report for the «Реальные фото» set: every photo goes through the full cascade search
(/api/cascade/search) and lands in one table row:

  query crop (bbox_crop of the service) | link to the source photo | recognised wine | status | confidence |
  latency (client round trip + service total_ms) | reference catalog label of the cascade winner | expected (labels.tsv)

For «нет в каталоге» answers the service has no winner; the table then shows the closest catalog label
(final_results[0]) marked as «ближайшая».

    python eval/real_photos_report.py
    python eval/real_photos_report.py --api http://127.0.0.1:8030 --photos "Реальные фото" --out results/real_photos_eval

Output: <out>/report.html, <out>/report.csv, <out>/search.jsonl, <out>/crops/, <out>/labels/
"""

import argparse
import base64
import csv
import html
import io
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent  # E:\Вина
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
THUMB = 360
STATUS_RU = {"found": "найдено", "probable": "похоже", "not_in_catalog": "нет в каталоге"}


def search(api: str, image: Path) -> tuple[dict, float]:
    boundary = uuid.uuid4().hex
    content_type = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="{image.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + image.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{api}/api/cascade/search", data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=180) as response:
        answer = json.load(response)
    return answer, (time.perf_counter() - started) * 1000


def save_thumb(image: Image.Image, target: Path) -> None:
    image = image.convert("RGB")
    image.thumbnail((THUMB, THUMB))
    image.save(target, format="JPEG", quality=85)


def load_labels(folder: Path) -> dict[str, dict]:
    tsv = folder / "labels.tsv"
    if not tsv.is_file():
        return {}
    with tsv.open(encoding="utf-8", newline="") as handle:
        return {row["image_path"]: row for row in csv.DictReader(handle, delimiter="\t")}


def infer_status(answer: dict) -> tuple[str, float | None]:
    """Map the CascadeSearchResponse to the report's found/probable/not_in_catalog status."""
    winner = answer.get("winner")
    if winner is None:
        return "not_in_catalog", None
    confidence = winner.get("final_score") or winner.get("dino_similarity")
    if confidence is not None and confidence >= 0.75:
        return "found", confidence
    return "probable", confidence


def verdict(label: dict | None, status: str, slug: str | None) -> str:
    """Correctness against labels.tsv: the service answer (winner slug or «нет в каталоге») vs the manual label."""
    if not label:
        return "нет разметки"
    label_status = label.get("status") or ""
    if label_status == "unsure":
        return "не оценивается"
    if label_status == "not_in_catalog":
        return {"not_in_catalog": "верно", "probable": "похоже (вина нет в каталоге)"}.get(status, "ложно найдено")
    accepted = {label.get("expected_slug") or "", *filter(None, (label.get("alt_slugs") or "").split(","))}
    if status == "not_in_catalog":
        return "ошибочно «нет в каталоге»"
    return "верно" if slug in accepted else "ошибка"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8030")
    parser.add_argument("--photos", type=Path, default=ROOT / "Реальные фото")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "real_photos_eval")
    args = parser.parse_args()

    out = args.out.resolve()
    (out / "crops").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    labels = load_labels(args.photos)
    photos = sorted(p for p in args.photos.iterdir() if p.suffix.lower() in IMAGE_EXT)

    rows = []
    raw = []
    for index, photo in enumerate(photos, 1):
        try:
            answer, latency = search(args.api, photo)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f"\n{photo.name}: {error}", file=sys.stderr)
            rows.append({"n": index, "photo": photo, "error": str(error), "label": labels.get(photo.name)})
            continue

        crop_file = None
        if answer.get("bbox_crop"):
            crop_file = f"crops/{index:03d}.jpg"
            data = base64.b64decode(answer["bbox_crop"].split(",", 1)[1])
            save_thumb(Image.open(io.BytesIO(data)), out / crop_file)

        winner = answer.get("winner")
        reference = winner or (answer.get("final_results") or [None])[0]
        ref_file = None
        if reference:
            ref_file = f"labels/{reference['product_id']}.jpg"
            if not (out / ref_file).is_file():
                with urllib.request.urlopen(args.api + urllib.parse.quote(reference["image_url"]), timeout=60) as response:
                    save_thumb(Image.open(io.BytesIO(response.read())), out / ref_file)

        slug = winner["slug"] if winner else None
        status, confidence = infer_status(answer)
        answer["status"] = status
        answer["confidence"] = confidence
        label = labels.get(photo.name)
        rows.append({
            "n": index,
            "photo": photo,
            "answer": answer,
            "winner": winner,
            "reference": reference,
            "crop": crop_file,
            "ref": ref_file,
            "latency": round(latency),
            "label": label,
            "verdict": verdict(label, status, slug),
        })
        slim = {key: value for key, value in answer.items() if key not in ("bbox_crop", "v4_query_crop")}
        raw.append({"image_path": photo.name, "latency_ms": round(latency), **slim})
        print(f"\r{index}/{len(photos)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    (out / "search.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw), encoding="utf-8")
    write_csv(out, rows)
    write_html(out, rows, args.api)
    print(out / "report.html")


def write_csv(out: Path, rows: list[dict]) -> None:
    with (out / "report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow([
            "№", "Фото", "Путь к фото", "Статус", "Распознано", "Производитель", "Slug победителя", "Уверенность",
            "Время клиента, мс", "Время сервиса, мс", "Эталонная этикетка", "Ожидаемый slug", "Оценка",
        ])
        for row in rows:
            answer = row.get("answer") or {}
            winner = row.get("winner") or {}
            reference = row.get("reference") or {}
            label = row.get("label") or {}
            writer.writerow([
                row["n"], row["photo"].name, str(row["photo"]),
                STATUS_RU.get(answer.get("status"), row.get("error", "")),
                winner.get("title", ""), winner.get("manufacturer", ""), winner.get("slug", ""),
                answer.get("confidence", ""), row.get("latency", ""), (answer.get("timings") or {}).get("total_ms", ""),
                row["ref"] or "", label.get("expected_slug", "") or label.get("status", ""), row.get("verdict", ""),
            ])


def write_html(out: Path, rows: list[dict], api: str) -> None:
    ok = [r for r in rows if "answer" in r]
    inside = [r for r in ok if (r["label"] or {}).get("status") == "in_catalog"]
    outside = [r for r in ok if (r["label"] or {}).get("status") == "not_in_catalog"]
    correct = sum(r["verdict"] == "верно" for r in inside)
    out_counts = {s: sum(r["answer"]["status"] == s for r in outside) for s in STATUS_RU}
    latencies = sorted(r["latency"] for r in ok)
    counts = {s: sum(r["answer"]["status"] == s for r in ok) for s in STATUS_RU}
    median = latencies[len(latencies) // 2] if latencies else 0

    def esc(value) -> str:
        return html.escape(str(value if value is not None else ""))

    body = []
    for row in rows:
        photo_href = Path(os.path.relpath(row["photo"], out)).as_posix()
        link = f'<a href="{esc(urllib.parse.quote(photo_href))}" target="_blank">{esc(row["photo"].name)}</a>'
        if "answer" not in row:
            body.append(f'<tr><td>{row["n"]}</td><td></td><td>{link}</td><td colspan="6" class="bad">{esc(row["error"])}</td></tr>')
            continue
        answer, winner, reference, label = row["answer"], row["winner"], row["reference"], row["label"] or {}
        status = answer["status"]
        crop = f'<img src="{esc(row["crop"])}" loading="lazy">' if row["crop"] else "—"
        if winner:
            name = f'<b>{esc(winner["title"])}</b><br><span class="muted">{esc(winner["manufacturer"])}</span><br><code>{esc(winner["slug"])}</code>'
        else:
            name = '<span class="muted">—</span>'
        ref_caption = "победитель" if winner else "ближайшая (не принята)"
        ref = (
            f'<a href="{esc(api + reference["image_url"])}" target="_blank"><img src="{esc(row["ref"])}" loading="lazy"></a>'
            f'<div class="muted">{ref_caption}: {esc(reference["title"])} · {esc(reference["manufacturer"])}</div>'
        ) if reference else "—"
        expected = esc(label.get("expected_slug") or {"not_in_catalog": "нет в каталоге", "unsure": "не размечено"}.get(label.get("status"), ""))
        note = f'<div class="muted">{esc(label.get("note"))}</div>' if label.get("note") else ""
        verdict_cls = {"верно": "good", "не оценивается": "muted", "нет разметки": "muted", "похоже (вина нет в каталоге)": "warn"}.get(row["verdict"], "bad")
        timings = answer.get("timings") or {}
        body.append(
            f'<tr data-status="{status}" data-verdict="{esc(row["verdict"])}">'
            f'<td>{row["n"]}</td><td class="img">{crop}</td><td>{link}</td>'
            f'<td><span class="st {status}">{STATUS_RU.get(status, status)}</span><br>{name}</td>'
            f'<td class="num">{answer["confidence"] if answer.get("confidence") is not None else "—"}</td>'
            f'<td class="num">{row["latency"]}<div class="muted">сервис {timings.get("total_ms", "—")}</div></td>'
            f'<td class="img">{ref}</td>'
            f'<td>{expected}{note}<div class="{verdict_cls}">{esc(row["verdict"])}</div></td></tr>'
        )

    page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Реальные фото: результаты</title><style>
body{{font:14px/1.4 system-ui,sans-serif;margin:16px;background:#fafafa;color:#222}}
table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border:1px solid #ddd;padding:6px;vertical-align:top;text-align:left}}
th{{background:#f0f0f0;position:sticky;top:0}}
td.img img{{max-width:180px;max-height:180px}}
td.num{{text-align:right;white-space:nowrap}}
.muted{{color:#777;font-size:12px}} .good{{color:#1a7f37;font-weight:600}} .bad{{color:#c62828;font-weight:600}} .warn{{color:#a86b00;font-weight:600}}
.st{{padding:1px 6px;border-radius:4px;font-size:12px}} .found{{background:#d6f5dd}} .probable{{background:#fff1c2}} .not_in_catalog{{background:#f3d6d6}}
code{{font-size:11px;color:#555}} .summary span{{margin-right:18px}}
</style></head><body>
<h1>Распознавание: «Реальные фото» (каскад /api/cascade/search)</h1>
<p class="summary"><span>Фото: <b>{len(rows)}</b></span><span>найдено {counts['found']}, похоже {counts['probable']}, нет в каталоге {counts['not_in_catalog']}</span>
<span>Вино в каталоге: top-1 верно <b>{correct}</b> из {len(inside)} ({100 * correct / max(1, len(inside)):.1f}%)</span>
<span>Вина нет в каталоге ({len(outside)}): «нет в каталоге» {out_counts['not_in_catalog']}, похоже {out_counts['probable']}, ложно «найдено» {out_counts['found']}</span>
<span>Время, мс: медиана {median}, макс {latencies[-1] if latencies else 0}</span></p>
<table><thead><tr><th>№</th><th>Кроп входного фото</th><th>Исходное фото</th><th>Распознано</th><th>Уверенность</th><th>Время, мс</th><th>Эталонная этикетка каталога</th><th>Разметка / оценка</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></body></html>"""
    (out / "report.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
