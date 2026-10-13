"""Comandos: init, preview, run-once, daily, status, dashboard."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .config import config_path, initialize_settings, load_settings, user_downloads
from .engine import FileTracker, scan
from .reports import daily_summary
from .runner import run_manual


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Organizador PC: serviço e relatórios de Downloads")
    parser.add_argument("--config", type=Path, default=config_path(), help="Caminho do config.json")
    actions = parser.add_subparsers(dest="command", required=True)
    init = actions.add_parser("init", help="Criar configuração (sem sobrescrever)")
    init.add_argument("--downloads", type=Path, default=None)
    init.add_argument("--storage", type=Path, default=None)
    actions.add_parser("preview", help="Visualizar organização sem mover arquivos")
    actions.add_parser("run-once", help="Organizar manualmente, gerando relatório")
    daily = actions.add_parser("daily", help="Consolidar relatórios de um dia")
    daily.add_argument("--date", type=date.fromisoformat, default=date.today())
    actions.add_parser("status", help="Ler último estado conhecido")
    actions.add_parser("dashboard", help="Abrir interface Tkinter")
    args = parser.parse_args(argv)
    if args.command == "init":
        path = initialize_settings(args.downloads or user_downloads(), path=args.config, storage=args.storage)
        print(f"Configuração criada: {path}")
        return 0
    settings = load_settings(args.config)
    if args.command == "dashboard":
        from .ui import Dashboard
        Dashboard(settings).mainloop()
        return 0
    if args.command == "preview":
        report = scan(settings, FileTracker(), preview=True)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif args.command == "run-once":
        report, filename = run_manual(settings)
        print(json.dumps({"resumo": report["resumo"], "relatorio": str(filename)}, indent=2, ensure_ascii=False))
    elif args.command == "status":
        if settings.status_path.exists():
            print(settings.status_path.read_text(encoding="utf-8-sig"))
        else:
            print("Ainda não há verificação registrada.")
    elif args.command == "daily":
        print(json.dumps(daily_summary(settings.reports_dir, args.date), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
