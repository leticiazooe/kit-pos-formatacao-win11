"""Motor de movimentação conservador e testável sem Windows/GUI."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .config import EXTENSION_TO_CATEGORY, IGNORED_NAMES, PENDING_EXTENSIONS, Settings, is_link_or_junction


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def event(kind: str, *, source: Path | None = None, destination: Path | None = None,
          category: str = "", size: int = 0, details: str = "") -> dict:
    return {"horario": timestamp(), "tipo": kind, "nome": source.name if source else (destination.name if destination else ""),
            "categoria": category, "origem": str(source) if source else "",
            "destino": str(destination) if destination else "", "tamanho_bytes": size,
            "detalhes": details}


def is_cloud_only(stat: os.stat_result) -> bool:
    """Evita hidratar/mover placeholders do OneDrive ainda não baixados."""
    attrs = getattr(stat, "st_file_attributes", 0)
    return bool(attrs & (0x00001000 | 0x00040000 | 0x00400000))


def classify(path: Path, settings: Settings) -> str:
    return EXTENSION_TO_CATEGORY.get(path.suffix.lower(), settings.unknown_category)


def destination_for(folder: Path, filename: str) -> Path:
    """Garante nomes previsíveis como 'arquivo (1).pdf', sem sobrescrever."""
    candidate = folder / filename
    suffix = "".join(Path(filename).suffixes)
    stem = filename[:-len(suffix)] if suffix else filename
    i = 1
    while candidate.exists() or is_link_or_junction(candidate):
        candidate = folder / f"{stem} ({i}){suffix}"
        i += 1
    return candidate


@dataclass
class FileTracker:
    """Exige duas varreduras estáveis para excluir downloads ainda em escrita."""
    known: dict[str, tuple[int, int]] = field(default_factory=dict)

    def update(self, discovered: dict[str, tuple[int, int]]) -> set[str]:
        stable = {name for name, signature in discovered.items() if self.known.get(name) == signature}
        self.known = discovered
        return stable


def scan(settings: Settings, tracker: FileTracker, *, now: float | None = None,
         preview: bool = False, stop: Callable[[], bool] | None = None) -> dict:
    """Varre só arquivos no nível raiz. Preview nunca altera nada.

    Com preview=True, indica até candidatos novos sem exigir duas varreduras.
    Na execução automática são necessárias duas observações (tamanho/mtime iguais).
    """
    settings.validate()
    started = timestamp()
    current = time.time() if now is None else now
    events: list[dict] = []
    discovered: dict[str, tuple[int, int]] = {}
    files: list[tuple[Path, os.stat_result]] = []
    for file in sorted(settings.downloads.iterdir(), key=lambda p: p.name.casefold()):
        if stop and stop():
            break
        if is_link_or_junction(file):
            events.append(event("ignorado", source=file, details="Link simbólico/atalho de sistema preservado"))
            continue
        if file.is_dir():
            # Pasta existente preservada, sem entrar recursivamente.
            continue
        if not file.is_file():
            events.append(event("ignorado", source=file, details="Item não é arquivo regular"))
            continue
        if file.name.casefold() in IGNORED_NAMES or file.suffix.lower() in PENDING_EXTENSIONS:
            events.append(event("ignorado", source=file, details="Temporário, metadado do sistema ou download incompleto"))
            continue
        try:
            stat = file.stat()
            if is_cloud_only(stat):
                events.append(event("ignorado", source=file, details="Arquivo disponível apenas na nuvem (não hidratado)"))
                continue
            discovered[str(file)] = (stat.st_size, stat.st_mtime_ns)
            files.append((file, stat))
        except OSError as exc:
            events.append(event("erro", source=file, details=f"Não foi possível consultar o arquivo: {exc}"))
    stable = tracker.update(discovered) if not preview else set(discovered)
    for file, stat in files:
        if stop and stop():
            break
        category = classify(file, settings)
        folder = settings.downloads / category
        if current - stat.st_mtime < settings.min_age_seconds:
            events.append(event("aguardando", source=file, category=category, size=stat.st_size,
                                details="Arquivo muito recente; aguardando segurança"))
            continue
        if str(file) not in stable:
            events.append(event("aguardando", source=file, category=category, size=stat.st_size,
                                details="Aguardando segunda verificação de tamanho/data"))
            continue
        if is_link_or_junction(folder):
            events.append(event("erro", source=file, category=category,
                                details=f"Pasta de destino é link simbólico: {folder}"))
            continue
        if folder.exists() and not folder.is_dir():
            events.append(event("erro", source=file, category=category,
                                details="Existe um arquivo com o nome da categoria"))
            continue
        destination = destination_for(folder, file.name)
        if preview or settings.dry_run:
            events.append(event("previsto", source=file, destination=destination,
                                category=category, size=stat.st_size, details="Prévia, nenhuma alteração aplicada"))
            continue
        try:
            # Reconsulta a origem imediatamente antes da operação.
            latest = file.stat()
            if (latest.st_size, latest.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                events.append(event("aguardando", source=file, category=category,
                                    details="Arquivo foi alterado durante a varredura"))
                continue
            if is_link_or_junction(file):
                events.append(event("ignorado", source=file, details="Origem tornou-se link simbólico"))
                continue
            new_folder = not folder.exists()
            folder.mkdir(exist_ok=True)
            if new_folder:
                events.append(event("pasta_criada", destination=folder, category=category))
            # No Windows, os.rename não substitui destino existente. Renomeia no mesmo volume.
            target = destination_for(folder, file.name)
            os.rename(file, target)
            events.append(event("movido", source=file, destination=target, category=category,
                                size=stat.st_size,
                                details="Nome ajustado para evitar conflito" if target.name != file.name else "Movido sem renomear"))
        except OSError as exc:
            events.append(event("erro", source=file, destination=destination, category=category,
                                details=f"Falha ao mover (mantido na origem): {exc}"))
    types = {t: sum(e["tipo"] == t for e in events) for t in
             ("movido", "pasta_criada", "aguardando", "ignorado", "erro", "previsto")}
    summary = {"arquivos_movidos": types["movido"], "pastas_criadas": types["pasta_criada"],
               "arquivos_aguardando": types["aguardando"], "arquivos_ignorados": types["ignorado"],
               "erros": types["erro"], "previstos": types["previsto"],
               "bytes_movidos": sum(e["tamanho_bytes"] for e in events if e["tipo"] == "movido"),
               "por_categoria": {c: sum(e["tipo"] == "movido" and e["categoria"] == c for e in events)
                                 for c in sorted({e["categoria"] for e in events if e["tipo"] == "movido"})}}
    return {"schema": 1, "aplicacao": "Organizador PC", "versao": "1.0.0",
            "operacao": "preview" if preview or settings.dry_run else "organizacao_automatica",
            "inicio": started, "fim": timestamp(), "downloads": str(settings.downloads),
            "estado": "concluido_com_erros" if summary["erros"] else "concluido",
            "resumo": summary, "eventos": events}
