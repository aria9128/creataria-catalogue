# -*- coding: utf-8 -*-
"""Génère l'état exhaustif des 216 cellules famille/niveau/durée."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
GRID_FILE = BASE_DIR / "catalogue_grid.json"
CATALOG_FILE = BASE_DIR / "creations.json"
STATUS_FILE = BASE_DIR / "catalogue_grid_status.json"

ALIASES = {
    "couture-loisir": "couture", "laine": "textile", "tricotin": "textile",
    "broderie-papier": "broderie", "recyclage-creatif": "recyclage",
    "jardinage-loisir": "jardinage"
}


def build_status() -> dict:
    grid = json.loads(GRID_FILE.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    records = catalog.get("creations", [])
    levels = {value.casefold(): value for value in grid["levels"]}
    result = {
        "schema_version": 1,
        "family_count": len(grid["families"]),
        "cells_total": len(grid["families"]) * len(grid["levels"]) * len(grid["durations"]),
        "cells_filled": 0,
        "minimum_creations_per_family": int(grid.get("minimum_creations_per_family", 5)),
        "family_counts": {},
        "cells": []
    }
    for family in grid["families"]:
        for level in grid["levels"]:
            for duration in grid["durations"]:
                linked = []
                for record in records:
                    family_id = record.get("family_id") or ALIASES.get(record.get("category", ""), record.get("category", ""))
                    record_level = levels.get(str(record.get("level", "")).casefold())
                    minutes = record.get("minutes")
                    if family_id != family["id"] or record_level != level or not isinstance(minutes, (int, float)):
                        continue
                    if minutes < duration["min_minutes"]:
                        continue
                    if duration["max_minutes"] is not None and minutes > duration["max_minutes"]:
                        continue
                    linked.append(record.get("id", ""))
                cell = {
                    "family_id": family["id"], "level": level,
                    "duration_id": duration["id"], "duration_label": duration["label"],
                    "creation_ids": linked, "status": "complete" if linked else "empty"
                }
                result["cells"].append(cell)
                result["cells_filled"] += bool(linked)
    result["cells_empty"] = result["cells_total"] - result["cells_filled"]
    for family in grid["families"]:
        result["family_counts"][family["id"]] = sum(
            1 for record in records
            if (record.get("family_id") or ALIASES.get(record.get("category", ""), record.get("category", ""))) == family["id"]
        )
    result["families_below_minimum"] = [
        family_id for family_id, count in result["family_counts"].items()
        if count < result["minimum_creations_per_family"]
    ]
    STATUS_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    status = build_status()
    print(f"Grille : {status['cells_filled']}/{status['cells_total']} cellules remplies; {status['cells_empty']} vides.")
