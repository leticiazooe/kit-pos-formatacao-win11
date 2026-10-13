"""Auditoria em JSON/CSV/TXT e consolidação diária sem coletar conteúdo dos arquivos."""
from __future__ import annotations

import csv
import json
import os
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

FIELDS = ("horario", "tipo", "nome", "categoria", "origem", "destino", "tamanho_bytes", "detalhes")


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def save_report(report: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    json_path = directory / f"organizacao_{prefix}.json"
    atomic_json(json_path, report)
    csv_path = json_path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(report["eventos"])
    summary = report["resumo"]
    rows = ["RELATÓRIO DE ORGANIZAÇÃO", "", f"Data: {report['inicio']}",
            f"Downloads: {report['downloads']}", f"Estado: {report['estado']}", "",
            f"Movidos: {summary['arquivos_movidos']}", f"Pastas criadas: {summary['pastas_criadas']}",
            f"Ignorados: {summary['arquivos_ignorados']}", f"Aguardando: {summary['arquivos_aguardando']}",
            f"Erros: {summary['erros']}", f"Bytes movidos: {summary['bytes_movidos']}", "",
            "Categorias:"]
    rows.extend(f"- {k}: {v}" for k, v in summary["por_categoria"].items())
    rows.extend(["", "Histórico:"])
    rows.extend(f"[{e['tipo']}] {e['origem']} -> {e['destino']} | {e['detalhes']}" for e in report["eventos"])
    json_path.with_suffix(".txt").write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
    return json_path


def daily_summary(directory: Path, day: date) -> dict:
    """Consolida somente JSON de execuções gravadas naquele dia."""
    reports = []
    for path in sorted(directory.glob(f"organizacao_{day:%Y%m%d}_*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8-sig"))
            if report.get("operacao") == "organizacao_automatica":
                reports.append(report)
        except (OSError, ValueError, TypeError):
            continue
    categories: dict[str, int] = {}
    for report in reports:
        for category, amount in report["resumo"].get("por_categoria", {}).items():
            categories[category] = categories.get(category, 0) + amount
    metrics = ("arquivos_movidos", "pastas_criadas", "arquivos_ignorados", "erros", "bytes_movidos")
    return {"dia": day.isoformat(), "execucoes_registradas": len(reports),
            "resumo": {metric: sum(r["resumo"].get(metric, 0) for r in reports) for metric in metrics},
            "por_categoria": dict(sorted(categories.items()))}


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Bloqueio interprocessos (serviço + linha de comando), não depende de pacotes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Outra execução está processando Downloads") from exc
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
