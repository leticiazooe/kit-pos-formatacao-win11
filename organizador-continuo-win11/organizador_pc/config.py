"""Configuração explícita: serviços Windows não devem descobrir Downloads via SYSTEM."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

CATEGORIES: dict[str, tuple[str, ...]] = {
    "PDF": (".pdf",),
    "HTML": (".html", ".htm"),
    "PASTAS ZIPADAS": (".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"),
    "IMAGENS": (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tif", ".tiff", ".heic"),
    "PLANILHAS": (".xlsx", ".xls", ".xlsm", ".csv", ".ods"),
    "WORD": (".doc", ".docx", ".odt", ".rtf"),
    "APRESENTACOES": (".ppt", ".pptx", ".odp"),
    "VIDEOS": (".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm"),
    "AUDIOS": (".mp3", ".wav", ".flac", ".ogg", ".m4a"),
    "INSTALADORES": (".exe", ".msi", ".msix", ".msixbundle", ".appx"),
    "CODIGO": (".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".css", ".sql", ".ipynb", ".xml", ".yaml", ".yml"),
    "TEXTO": (".txt", ".md", ".log"),
    "ATALHOS": (".url", ".lnk"),
}
EXTENSION_TO_CATEGORY = {ext: category for category, extensions in CATEGORIES.items() for ext in extensions}
PENDING_EXTENSIONS = frozenset({".crdownload", ".part", ".partial", ".download", ".tmp", ".temp"})
IGNORED_NAMES = frozenset({"desktop.ini", "thumbs.db", ".ds_store"})


def is_link_or_junction(path: Path) -> bool:
    """Rejeita symlinks e junctions NTFS usados para desviar arquivos da pasta."""
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def data_dir() -> Path:
    root = os.environ.get("PROGRAMDATA") if sys.platform == "win32" else None
    return (Path(root) / "OrganizadorPC") if root else (Path.home() / ".organizador-pc")


def config_path() -> Path:
    return data_dir() / "config.json"


def user_downloads() -> Path:
    """Só deve ser chamado no instalador/CLI em sessão de usuário, nunca no serviço."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                raw = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")[0]
            return Path(os.path.expandvars(raw)).expanduser().resolve()
        except (OSError, ValueError, ImportError):
            pass
    return (Path.home() / "Downloads").resolve()


@dataclass(frozen=True)
class Settings:
    downloads: Path
    storage: Path
    interval_seconds: int = 300
    min_age_seconds: int = 120
    dry_run: bool = False
    unknown_category: str = "OUTROS"

    @property
    def reports_dir(self) -> Path:
        return self.storage / "reports"

    @property
    def status_path(self) -> Path:
        return self.storage / "status.json"

    def validate(self) -> None:
        if not self.downloads.is_absolute() or not self.storage.is_absolute():
            raise ValueError("Downloads e armazenamento devem ter caminhos absolutos")
        if self.downloads.parent == self.downloads:
            raise ValueError("Downloads não pode ser a raiz do volume")
        if is_link_or_junction(self.downloads):
            raise ValueError("Downloads não pode ser link simbólico")
        if self.storage.resolve() == self.downloads.resolve() or self.storage.resolve().is_relative_to(self.downloads.resolve()):
            raise ValueError("Relatórios/configuração não podem ficar dentro de Downloads")
        if self.interval_seconds < 10 or self.min_age_seconds < 0:
            raise ValueError("Intervalo deve ser >= 10 segundos e idade mínima >= 0")
        if not self.unknown_category or any(c in self.unknown_category for c in r'\/:*?"<>|.'):
            raise ValueError("Nome inválido para a categoria de arquivos desconhecidos")

    def as_dict(self) -> dict:
        return {
            "downloads_path": str(self.downloads),
            "storage_path": str(self.storage),
            "interval_seconds": self.interval_seconds,
            "min_age_seconds": self.min_age_seconds,
            "dry_run": self.dry_run,
            "unknown_category": self.unknown_category,
        }


def load_settings(path: Path | None = None) -> Settings:
    filename = path or config_path()
    content = json.loads(filename.read_text(encoding="utf-8-sig"))
    if not isinstance(content, dict):
        raise ValueError("Configuração deve ser objeto JSON")
    settings = Settings(
        downloads=Path(content["downloads_path"]).expanduser(),
        storage=Path(content.get("storage_path", str(data_dir()))).expanduser(),
        interval_seconds=int(content.get("interval_seconds", 300)),
        min_age_seconds=int(content.get("min_age_seconds", 120)),
        dry_run=content.get("dry_run", False),
        unknown_category=content.get("unknown_category", "OUTROS"),
    )
    if not isinstance(settings.dry_run, bool):
        raise ValueError("dry_run deve ser booleano")
    settings.validate()
    return settings


def initialize_settings(downloads: Path, *, path: Path | None = None, storage: Path | None = None,
                        replace: bool = False) -> Path:
    destination = path or config_path()
    settings = Settings(downloads=downloads.expanduser().resolve(), storage=(storage or data_dir()).resolve())
    settings.validate()
    if not settings.downloads.is_dir():
        raise FileNotFoundError(f"Downloads não encontrada: {settings.downloads}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w" if replace else "x", encoding="utf-8") as out:
        json.dump(settings.as_dict(), out, ensure_ascii=False, indent=2)
        out.write("\n")
    return destination
