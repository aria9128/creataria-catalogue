# -*- coding: utf-8 -*-
"""Veille automatique et génération de variantes originales CREATARIA.

Le robot lit des flux RSS de recherche multilingues. Il ne télécharge pas les
pages d'articles ni leurs images : le titre, le lien, la date et l'éditeur ne
servent qu'à repérer et citer une idée. Une fiche est ensuite créée à partir
d'une fiche projet complète déjà présente dans le catalogue.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "creations.json"
GRID_PATH = BASE_DIR / "catalogue_grid.json"
STATUS_PATH = BASE_DIR / "catalogue_grid_status.json"
MANIFEST_PATH = BASE_DIR / "manifest.json"
STATE_PATH = BASE_DIR / "catalog_robot_state.json"
MAX_FEED_BYTES = 3_000_000
MAX_ITEMS_PER_FEED = 60
MAX_NEW_PER_RUN = 24
MAX_PER_FAMILY_PER_RUN = 2
MAX_SEEN_URLS = 5000

# Broad discovery terms; the examples supplied by the user are not a closed list.
# RSS headlines are metadata only. Unknown or ambiguous topics are skipped.
SEARCHES = (
    ("en-US", "US", "en", '(DIY OR handmade OR craft OR crafts OR "making things" OR "creative project" OR tutorial) -jobs -course'),
    ("fr-FR", "FR", "fr", '(création OR bricolage OR fait-main OR loisir-créatif OR artisanat OR tutoriel) -emploi -formation'),
    ("es-ES", "ES", "es", '(manualidades OR artesanía OR hecho-a-mano OR bricolaje OR tutorial) -empleo -curso'),
    ("ja-JP", "JP", "ja", '(手芸 OR 工作 OR ハンドメイド OR クラフト OR DIY) -求人'),
    ("pt-BR", "BR", "pt", '(artesanato OR feito-à-mão OR trabalhos-manuais OR bricolagem OR DIY) -emprego'),
)

FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "couture": ("sewing", "sew", "dressmaking", "couture", "costura", "costura criativa", "nähen", "縫製"),
    "crochet": ("crochet", "crocheting", "crochet hook", "ganchillo", "crochê", "かぎ針"),
    "tricot": ("knitting", "knit", "knitted", "tricot", "tejido a dos agujas", "tricô", "編み物"),
    "broderie": ("embroidery", "embroider", "broderie", "bordado", "刺繍"),
    "papier": ("paper craft", "paper mache", "paper mâché", "papercraft", "cartonnage", "papel", "紙工作", "紙細工"),
    "bois": ("woodworking", "wood craft", "wooden", "wood carving", "bois", "madera", "madeira", "木工", "木彫り"),
    "dessin": ("drawing", "sketching", "illustration", "dessin", "dibujo", "desenho", "描画"),
    "peinture": ("painting", "painted", "watercolor", "watercolour", "acrylic painting", "peinture", "pintura", "絵画"),
    "origami": ("origami", "paper folding", "pliage papier", "折り紙"),
    "scrapbooking": ("scrapbooking", "journaling", "memory book", "album créatif", "álbum de recortes", "スクラップブッキング"),
    "bijoux": ("jewelry making", "jewellery", "beading", "beaded", "bijou", "joyería", "bijuteria", "アクセサリー"),
    "modelage": ("clay", "polymer clay", "sculpting", "modelling", "modeling", "pâte polymère", "arcilla", "粘土"),
    "macrame": ("macrame", "macramé", "knot craft", "macramê", "マクラメ"),
    "resine": ("resin art", "epoxy resin", "resin craft", "résine", "resina epoxi", "レジン"),
    "jardinage": ("gardening", "planter", "plant craft", "jardinage", "jardinería", "jardinagem", "園芸"),
    "cuisine_creative": ("decorated cookies", "creative cooking", "food art", "cake decorating", "cuisine créative", "repostería creativa", "料理"),
    "recyclage": ("upcycling", "recycled craft", "reuse craft", "recycling craft", "récupération créative", "reciclaje creativo", "アップサイクル"),
    "jeux": ("handmade game", "DIY game", "board game craft", "jeu fait main", "juego artesanal", "手作りゲーム"),
    "decoration": ("home decor", "seasonal decor", "holiday decoration", "décoration", "decoración", "decoração", "インテリア"),
    "textile": ("felting", "textile art", "fabric dye", "weaving", "tie-dye", "teinture textile", "fieltro", "染色"),
    "mosaique": ("mosaic", "mosaïque", "tile craft", "mosaico", "モザイク"),
    "photographie": ("creative photography", "photo styling", "photography project", "photographie créative", "fotografía creativa", "写真撮影"),
    "astronomie": ("astronomy craft", "star map", "constellation craft", "astronomie amateur", "astronomía", "天体観測"),
    "echecs": ("chess craft", "chess set", "chessboard", "échecs", "ajedrez", "xadrez", "チェス"),
}

THEME_WORDS = (
    "heart", "hearts", "love", "tree", "christmas", "winter", "snowflake", "star", "stars",
    "character", "figurine", "doll", "animal", "bird", "flower", "plant", "house", "home",
    "nativity", "crib", "village", "ornament", "gift", "candle", "lantern", "pumpkin", "easter",
    "coeur", "cœur", "sapin", "crèche", "personnage", "animal", "fleur", "maison", "étoile",
    "corazón", "árbol", "personaje", "flor", "coração", "árvore", "ハート", "ツリー", "人形",
)


def _clean_text(value: str, limit: int = 220) -> str:
    value = unescape(re.sub(r"<[^>]*>", " ", value or ""))
    value = " ".join(value.split())
    value = "".join(ch for ch in value if ch.isprintable())
    return value[:limit].strip()


def _feed_url(locale: tuple[str, str, str, str]) -> str:
    lang, country, language, query = locale
    params = urllib.parse.urlencode({"q": query, "hl": lang, "gl": country, "ceid": f"{country}:{language}"})
    return "https://news.google.com/rss/search?" + params


def _parse_date(value: str) -> str:
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def fetch_feed(locale: tuple[str, str, str, str]) -> list[dict]:
    url = _feed_url(locale)
    request = urllib.request.Request(url, headers={"User-Agent": "CREATARIA-CatalogRobot/1.0 (RSS metadata reader)"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("flux RSS trop volumineux")
    root = ET.fromstring(payload)
    results = []
    for node in root.findall(".//item")[:MAX_ITEMS_PER_FEED]:
        title = _clean_text(node.findtext("title", ""))
        link = _clean_text(node.findtext("link", ""), 1000)
        if not title or urllib.parse.urlparse(link).scheme != "https":
            continue
        source_node = node.find("source")
        publisher = _clean_text(source_node.text or "", 120) if source_node is not None else ""
        results.append({"title": title, "url": link, "publisher": publisher,
                        "published_at": _parse_date(node.findtext("pubDate", "")),
                        "locale": locale[0]})
    return results


def classify(title: str) -> str | None:
    normalized = title.casefold()
    hits = []
    for family_id, keywords in FAMILY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword.casefold() in normalized)
        if score:
            hits.append((score, family_id))
    return max(hits)[1] if hits else None


def select_theme(title: str) -> str:
    normalized = title.casefold()
    for theme in THEME_WORDS:
        if theme.casefold() in normalized:
            return theme
    # Any headline can inspire a palette or decoration; it is not used as an
    # instruction source and is escaped by the UI before display.
    return _clean_text(title, 72) or "idée créative repérée en ligne"


def _load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(fallback)


def _existing_sources(catalog: dict) -> set[str]:
    return {str(item.get("source", {}).get("url", "")) for item in catalog.get("creations", [])
            if isinstance(item.get("source"), dict)}


def _make_record(item: dict, family_id: str, seeds: list[dict]) -> dict:
    digest = hashlib.sha256(item["url"].encode("utf-8")).hexdigest()
    seed = copy.deepcopy(seeds[int(digest[:8], 16) % len(seeds)])
    theme = select_theme(item["title"])
    seed["id"] = f"robot-{family_id}-{digest[:14]}"
    seed["family_id"] = family_id
    seed["category"] = family_id
    seed["title"] = f"{seed.get('title', 'Projet créatif')} — variation : {theme}"
    seed["tags"] = list(dict.fromkeys([*(seed.get("tags") or []), "inspiration en ligne", theme.casefold()]))
    seed["tip"] = (str(seed.get("tip", "")).rstrip() +
                   f" Variation générée automatiquement à partir d'une idée repérée en ligne. "
                   "Le lien est une piste d'inspiration, pas une source d'étapes ou de photo; "
                   "les dimensions, quantités et consignes de cette fiche restent celles du patron CREATARIA.")
    seed["steps"] = list(seed.get("steps") or []) + [
        f"Variation décorative facultative : reprendre le thème « {theme} » uniquement dans les couleurs ou le motif de surface; conserver les matériaux, les mesures et les consignes de sécurité de cette fiche."
    ]
    seed["source"] = {
        "title": item["title"], "url": item["url"], "publisher": item["publisher"],
        "published_at": item["published_at"], "discovered_at": datetime.now(timezone.utc).isoformat(),
        "locale": item["locale"], "method": "Google News RSS; titre, lien et éditeur seulement"
    }
    seed["generated_by"] = "CREATARIA catalog robot"
    return seed


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_manifest_and_status() -> dict:
    # Use the same canonical Python grid builder in Windows and GitHub Actions.
    from catalogue_grid_builder import build_status
    status = build_status()
    status["percentage"] = round(100 * status["cells_filled"] / max(status["cells_total"], 1), 2)
    _write_json(STATUS_PATH, status)
    manifest = _load_json(MANIFEST_PATH, {"module": "CREATARIA", "manifest_version": 1,
                                           "catalog_version": "0.1.0", "catalog_file": "creations.json",
                                           "catalog_scope": "worldwide", "language": "fr"})
    raw = CATALOG_PATH.read_bytes()
    manifest["catalog_sha256"] = hashlib.sha256(raw).hexdigest()
    manifest["catalog_version"] = datetime.now(timezone.utc).strftime("%Y.%m.%d")
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(MANIFEST_PATH, manifest)
    return status


def run() -> int:
    catalog = _load_json(CATALOG_PATH, {"schema_version": 1, "catalog_scope": "worldwide", "language": "fr", "creations": []})
    records = catalog.get("creations", [])
    known_urls = _existing_sources(catalog)
    state = _load_json(STATE_PATH, {"seen_urls": [], "last_run": None})
    seen = set(state.get("seen_urls", []))
    seeds: dict[str, list[dict]] = {}
    grid = _load_json(GRID_PATH, {"families": []})
    family_ids = {f["id"] for f in grid.get("families", [])}
    for family_id in family_ids:
        seeds[family_id] = [r for r in records if r.get("family_id") == family_id
                            and r.get("kind", "project") == "project"
                            and r.get("materials") and r.get("steps") and r.get("pattern_shapes")]

    found: list[dict] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_feed, locale): locale for locale in SEARCHES}
        for future in as_completed(futures):
            locale = futures[future]
            try:
                found.extend(future.result())
            except Exception as exc:
                errors.append(f"{locale[0]}: {type(exc).__name__}: {exc}")

    unique: dict[str, dict] = {}
    for item in found:
        unique.setdefault(item["url"], item)
    candidates = sorted(unique.values(), key=lambda x: x.get("published_at", ""), reverse=True)
    family_counts: dict[str, int] = {}
    additions = []
    for item in candidates:
        url = item["url"]
        if url in seen or url in known_urls:
            continue
        family_id = classify(item["title"])
        if family_id not in family_ids or not seeds.get(family_id):
            continue
        if family_counts.get(family_id, 0) >= MAX_PER_FAMILY_PER_RUN:
            continue
        record = _make_record(item, family_id, seeds[family_id])
        additions.append(record)
        family_counts[family_id] = family_counts.get(family_id, 0) + 1
        seen.add(url)
        if len(additions) >= MAX_NEW_PER_RUN:
            break

    if additions:
        catalog["creations"].extend(additions)
        _write_json(CATALOG_PATH, catalog)
    status = update_manifest_and_status()
    state["seen_urls"] = list(seen)[-MAX_SEEN_URLS:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["last_discovered_count"] = len(found)
    state["last_added_count"] = len(additions)
    state["last_errors"] = errors[:10]
    _write_json(STATE_PATH, state)
    print(json.dumps({"discovered": len(found), "added": len(additions),
                      "family_counts": family_counts, "grid": f"{status['cells_filled']}/{status['cells_total']}",
                      "errors": errors[:5]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
