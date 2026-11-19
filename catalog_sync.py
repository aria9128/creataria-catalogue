# -*- coding: utf-8 -*-
"""Mise à jour indépendante du catalogue CREATARIA depuis un manifest HTTPS."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "creations.json"
CONFIG_PATH = BASE_DIR / "catalog_update.json"
MAX_MANIFEST_BYTES = 256_000
MAX_CATALOG_BYTES = 50_000_000


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def update_catalog() -> tuple[bool, str]:
    """Télécharge et valide le catalogue; conserve la copie locale en cas d'échec."""
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        manifest_url = str(config.get("manifest_url", "")).strip()
        if not manifest_url:
            return False, "URL du manifest non configurée (NON CODÉ côté publication)."
        parsed = urllib.parse.urlparse(manifest_url)
        if parsed.scheme != "https" or not parsed.netloc:
            return False, "Le manifest doit être publié sur une adresse HTTPS."
        request = urllib.request.Request(manifest_url, headers={"User-Agent": "CREATARIA/1.0"})
        with urllib.request.urlopen(request, timeout=15) as response:
            raw_manifest = response.read(MAX_MANIFEST_BYTES + 1)
        if len(raw_manifest) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest trop volumineux")
        manifest = json.loads(raw_manifest.decode("utf-8"))
        if manifest.get("module") != "CREATARIA":
            raise ValueError("ce manifest n'est pas celui de CREATARIA")
        relative_file = str(manifest.get("catalog_file", ""))
        if not relative_file or Path(relative_file).name != relative_file:
            raise ValueError("nom de fichier catalogue invalide")
        digest = str(manifest.get("catalog_sha256", "")).lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("empreinte SHA-256 absente ou invalide")
        catalog_url = urllib.parse.urljoin(manifest_url, relative_file)
        with urllib.request.urlopen(urllib.request.Request(catalog_url, headers={"User-Agent": "CREATARIA/1.0"}), timeout=30) as response:
            catalog_bytes = response.read(MAX_CATALOG_BYTES + 1)
        if len(catalog_bytes) > MAX_CATALOG_BYTES:
            raise ValueError("catalogue trop volumineux")
        if hashlib.sha256(catalog_bytes).hexdigest() != digest:
            raise ValueError("l'empreinte du catalogue ne correspond pas au manifest")
        catalog = json.loads(catalog_bytes.decode("utf-8"))
        if not isinstance(catalog, dict) or not isinstance(catalog.get("creations"), list):
            raise ValueError("structure creations.json invalide")
        _atomic_write(CATALOG_PATH, catalog_bytes)
        _atomic_write(BASE_DIR / "manifest.json", raw_manifest)
        return True, "Catalogue actualisé."
    except Exception as exc:
        return False, f"Mise à jour impossible; catalogue hors ligne conservé. {type(exc).__name__}: {exc}"
