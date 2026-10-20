"""Метрики подбора на эталоне (ТЗ п. 8.1) — для настройки весов app/sommelier/data/pairing_config.json.

    python scripts/eval_pairing.py            # сводка + блюда с промахом
    python scripts/eval_pairing.py -v         # все блюда с топ-5 сортов
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.sommelier.pairing import build_pairing_service  # noqa: E402
from app.sommelier.pairing.reference import load_reference  # noqa: E402
from app.sommelier.pairing.scoring import DishProfile, rank_grapes  # noqa: E402


def main(verbose: bool) -> None:
    svc = build_pairing_service("service")   # каталог сканера: только российские вина
    ref = load_reference()
    hit = bad = slots = with_grape = answered = 0
    for p in ref["pairs"]:
        d = svc.dishes.by_id[p["dish"]]
        ranked = rank_grapes(svc.grapes.grapes, DishProfile.from_dish(d), svc.w)
        top = [s.grape.grape_id for s in ranked if s.score >= svc.r["min_grape_score"]][:3]
        h, b = bool(set(top) & set(p["good"])), len(set(top) & set(p["bad"]))
        hit, bad, slots = hit + h, bad + b, slots + len(top)
        wines = svc.pair_dish(d.name)["wines"]
        assert all(w["is_russian"] for w in wines)
        if top:
            with_grape += 1
            answered += bool(wines)
        if verbose or not h or b:
            print(f"{'ok ' if h and not b else 'MISS'} {d.name:32s} top: {', '.join(f'{s.grape.name} {s.score:g}' for s in ranked[:5])}"
                  f" | эталон: {', '.join(p['good'])}; нельзя: {', '.join(p['bad'])}")
    n = len(ref["pairs"])
    print(f"\nэталон {ref['version']} ({ref['status']}), веса {svc.config['version']}, блюд {n}")
    print(f"Top-3 hit rate:              {hit / n:.1%}  (цель ≥ 85%)")
    print(f"Неподходящие сорта в тройке: {bad / max(slots, 1):.1%}  (цель ≤ 5%)")
    print(f"Есть российская бутылка, когда есть подходящий сорт: {answered / max(with_grape, 1):.1%}  (цель ≥ 90%, каталог сканера)")


if __name__ == "__main__":
    main("-v" in sys.argv)
