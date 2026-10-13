"""Executa ciclo periódico. Não há loop de GUI no serviço."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import Settings
from .engine import FileTracker, scan, timestamp
from .reports import atomic_json, exclusive_lock, save_report


def run_cycle(settings: Settings, tracker: FileTracker, *, preview: bool = False,
              force_report: bool = False, stop: Callable[[], bool] | None = None) -> tuple[dict, Path | None]:
    with exclusive_lock(settings.storage / "scan.lock"):
        try:
            report = scan(settings, tracker, preview=preview, stop=stop)
            totals = report["resumo"]
            important = totals["arquivos_movidos"] or totals["pastas_criadas"] or totals["erros"]
            # Execuções vazias não geram arquivos a cada 5 minutos.
            saved = save_report(report, settings.reports_dir) if force_report or important else None
            atomic_json(settings.status_path, {
                "estado": "ativo", "ultima_verificacao": timestamp(),
                "downloads": str(settings.downloads), "modo_simulacao": settings.dry_run,
                "ultimo_resumo": totals,
                "ultimo_relatorio": str(saved) if saved else None,
                "aviso": "Relatório só é salvo ao ocorrer movimentação/erro ou execução manual",
            })
            return report, saved
        except Exception as exc:
            atomic_json(settings.status_path, {
                "estado": "erro", "ultima_verificacao": timestamp(),
                "downloads": str(settings.downloads), "erro": f"{type(exc).__name__}: {exc}"})
            raise


def run_manual(settings: Settings) -> tuple[dict, Path | None]:
    tracker = FileTracker()
    # Observa duas vezes, mas ainda respeita min_age_seconds e arquivos incompletos.
    with exclusive_lock(settings.storage / "scan.lock"):
        scan(settings, tracker, preview=False)  # primeira observação, nenhum arquivo movido
        report = scan(settings, tracker, preview=False)  # segunda observação estável
        saved = save_report(report, settings.reports_dir)
        atomic_json(settings.status_path, {"estado": "ativo", "ultima_verificacao": timestamp(),
                                           "downloads": str(settings.downloads),
                                           "modo_simulacao": settings.dry_run,
                                           "ultimo_resumo": report["resumo"], "ultimo_relatorio": str(saved)})
    return report, saved
