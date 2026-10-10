"""Preparador PC — assistente de organização e backup pré-formatação.

Python 3.10+; somente biblioteca padrão (Tkinter/ttk).
Não apaga arquivos, não formata o computador e não sobrescreve backups.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import END, BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
import tkinter as tk

APP = "Preparador PC"
APP_VERSION = "3.0.0"
PENDING_EXTENSIONS = {".crdownload", ".part", ".partial", ".download", ".tmp"}
CATEGORIES = {
    "PDF": {".pdf"},
    "HTML": {".html", ".htm"},
    "PASTAS ZIPADAS": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "IMAGENS": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".tif", ".tiff", ".heic"},
    "PLANILHAS": {".xlsx", ".xls", ".xlsm", ".csv", ".ods"},
    "WORD": {".doc", ".docx", ".odt", ".rtf"},
    "APRESENTACOES": {".ppt", ".pptx", ".odp"},
    "VIDEOS": {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".webm"},
    "AUDIOS": {".mp3", ".wav", ".flac", ".ogg", ".m4a"},
    "INSTALADORES": {".exe", ".msi", ".msix", ".msixbundle", ".appx"},
    "CODIGO": {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".css", ".sql", ".ipynb", ".xml", ".yaml", ".yml"},
    "TEXTO": {".txt", ".md", ".log"},
}
EXTENSION_TO_CATEGORY = {ext: category for category, extensions in CATEGORIES.items() for ext in extensions}
CHUNK_BYTES = 4 * 1024 * 1024


def known_folder(registry_name: str, fallback: str) -> Path:
    """Lê caminhos redirecionados do Explorer (inclusive OneDrive), quando disponíveis."""
    if sys.platform == "win32":
        try:
            import winreg
            keypath = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, keypath) as key:
                value = winreg.QueryValueEx(key, registry_name)[0]
            return Path(os.path.expandvars(value)).expanduser()
        except (OSError, ImportError, ValueError):
            pass
    return Path.home() / fallback


def existing_first(paths: list[Path]) -> Path:
    return next((p for p in paths if p.is_dir()), paths[0])


def default_folders() -> dict[str, Path]:
    home = Path.home()
    downloads = known_folder("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads")
    pictures = known_folder("My Pictures", "Pictures")
    desktop = known_folder("Desktop", "Desktop")
    documents = known_folder("Personal", "Documents")
    pictures = existing_first([pictures, home / "Imagens", home / "Pictures"])
    screens_candidates = [pictures / "Screenshots", pictures / "Capturas de Tela", pictures / "Capturas de tela"]
    for root in [home / "OneDrive", *home.glob("OneDrive - *")]:
        screens_candidates += [root / "Pictures" / "Screenshots", root / "Imagens" / "Capturas de Tela"]
    return {
        "Capturas de tela": existing_first(screens_candidates),
        "Área de Trabalho": desktop,
        "Documentos": documents,
        "Imagens": pictures,
        "Downloads": downloads,
    }


def classify(path: Path) -> str:
    return EXTENSION_TO_CATEGORY.get(path.suffix.lower(), "OUTROS")


def is_special_file(path: Path) -> bool:
    return path.suffix.lower() in PENDING_EXTENSIONS or path.is_symlink()


def unique_destination(folder: Path, name: str, reserved: set[Path] | None = None) -> Path:
    reserved = reserved if reserved is not None else set()
    candidate = folder / name
    original = Path(name)
    suffixes = "".join(original.suffixes) or original.suffix
    stem = name[:-len(suffixes)] if suffixes else name
    number = 1
    while candidate.exists() or candidate in reserved:
        candidate = folder / f"{stem} ({number}){suffixes}"
        number += 1
    return candidate


@dataclass
class MovePlan:
    source: Path
    destination: Path


def make_move_plan(downloads: Path) -> list[MovePlan]:
    if not downloads.is_dir():
        raise FileNotFoundError(f"Pasta não encontrada: {downloads}")
    plans: list[MovePlan] = []
    reserved: set[Path] = set()
    for path in sorted(downloads.iterdir(), key=lambda x: x.name.casefold()):
        if path.name == REPORTS_DIR or not path.is_file() or is_special_file(path):
            continue
        destination_folder = downloads / classify(path)
        destination = unique_destination(destination_folder, path.name, reserved)
        reserved.add(destination)
        plans.append(MovePlan(path, destination))
    return plans



REPORTS_DIR = "_RELATORIOS_PREPARADOR_PC"
REPORT_FIELDS = ("horario", "tipo", "nome", "categoria", "origem", "destino", "tamanho_bytes", "detalhes")
REPORT_LABELS = {
    "movido": "Arquivo movido",
    "pasta_criada": "Pasta criada",
    "pasta_reutilizada": "Pasta já existente",
    "ignorado": "Arquivo ignorado",
    "pasta_preservada": "Pasta preservada",
    "erro": "Erro",
}


def _organization_event(kind: str, source: Path | None = None, destination: Path | None = None,
                        category: str = "", size: int = 0, details: str = "") -> dict:
    return {
        "horario": datetime.now().isoformat(timespec="seconds"),
        "tipo": kind,
        "nome": source.name if source else (destination.name if destination else ""),
        "categoria": category,
        "origem": str(source) if source else "",
        "destino": str(destination) if destination else "",
        "tamanho_bytes": size,
        "detalhes": details,
    }


def run_downloads_organization(downloads: Path, plans: list[MovePlan]) -> tuple[dict, Path | None]:
    """Executa a prévia selecionada e cria auditoria, sem apagar/sobrescrever arquivos.

    A pasta de relatórios fica dentro da origem. Um erro ao gravá-la não esconde
    o resultado que continua disponível na interface e pode ser exportado.
    """
    downloads = downloads.expanduser().resolve()
    if not downloads.is_dir():
        raise FileNotFoundError(f"Pasta não encontrada: {downloads}")
    started = datetime.now().isoformat(timespec="seconds")
    events: list[dict] = []
    planned_sources = {plan.source for plan in plans}

    # Estado inicial: todos os arquivos não planejados e subpastas preservadas.
    for item in sorted(downloads.iterdir(), key=lambda x: x.name.casefold()):
        if item.name == REPORTS_DIR and item.is_dir() and not item.is_symlink():
            continue
        if item in planned_sources:
            continue
        if item.is_symlink():
            events.append(_organization_event("ignorado", item, details="Atalho ou link simbólico, preservado"))
        elif item.is_dir():
            events.append(_organization_event("pasta_preservada", item, details="Subpasta existente mantida sem alterações"))
        elif item.is_file():
            reason = "Download incompleto ou arquivo temporário" if item.suffix.lower() in PENDING_EXTENSIONS else "Arquivo não incluído na prévia; preservado"
            events.append(_organization_event("ignorado", item, details=reason))
        else:
            events.append(_organization_event("ignorado", item, details="Tipo não reconhecido; preservado"))

    accounted_folders: set[Path] = set()
    for move in plans:
        source, folder = move.source, move.destination.parent
        try:
            # Impede o uso de uma prévia manipulada com origem ou destino externo.
            if source.parent.resolve() != downloads or folder.parent.resolve() != downloads:
                raise ValueError("Origem ou pasta de destino fora de Downloads")
            if source.is_symlink():
                events.append(_organization_event("ignorado", source, details="Tornou-se um link simbólico; preservado"))
                continue
            if not source.is_file():
                raise FileNotFoundError("Arquivo original não existe mais")
            if source.suffix.lower() in PENDING_EXTENSIONS:
                events.append(_organization_event("ignorado", source, details="Arquivo tornou-se download incompleto"))
                continue
            if folder.is_symlink():
                raise ValueError("Pasta de destino é um link simbólico")
            if folder not in accounted_folders:
                if folder.exists():
                    if not folder.is_dir():
                        raise NotADirectoryError(f"Destino existe, mas não é pasta: {folder}")
                    events.append(_organization_event("pasta_reutilizada", destination=folder,
                                                      category=folder.name, details="Pasta já existia; conteúdo preservado"))
                else:
                    folder.mkdir(exist_ok=False)
                    events.append(_organization_event("pasta_criada", destination=folder,
                                                      category=folder.name, details="Pasta criada para organizar os arquivos"))
                accounted_folders.add(folder)
            file_bytes = source.stat().st_size
            target = unique_destination(folder, move.destination.name)
            shutil.move(str(source), str(target))
            note = (f"Nome ajustado para evitar sobrescrita: {target.name}"
                    if target.name != source.name else "Movido com o nome original")
            events.append(_organization_event("movido", source, target, folder.name, file_bytes, note))
        except (OSError, shutil.Error, ValueError) as error:
            events.append(_organization_event("erro", source, move.destination, folder.name,
                                              details=str(error)))

    counts = Counter(entry["tipo"] for entry in events)
    moved = [entry for entry in events if entry["tipo"] == "movido"]
    report = {
        "versao_relatorio": 2,
        "aplicacao": APP,
        "operacao": "organizar_downloads",
        "inicio": started,
        "fim": datetime.now().isoformat(timespec="seconds"),
        "pasta_downloads": str(downloads),
        "estado": "concluido_com_erros" if counts["erro"] else "concluido",
        "resumo": {
            "previstos": len(plans),
            "arquivos_movidos": counts["movido"],
            "pastas_criadas": counts["pasta_criada"],
            "pastas_reutilizadas": counts["pasta_reutilizada"],
            "arquivos_ignorados": counts["ignorado"],
            "pastas_preservadas": counts["pasta_preservada"],
            "erros": counts["erro"],
            "bytes_movidos": sum(entry["tamanho_bytes"] for entry in moved),
            "por_categoria": dict(sorted(Counter(entry["categoria"] for entry in moved).items())),
        },
        "eventos": events,
    }
    report_path = None
    try:
        directory = downloads / REPORTS_DIR
        if directory.is_symlink():
            raise ValueError("Diretório de relatórios não pode ser um link simbólico")
        directory.mkdir(exist_ok=True)
        report_path = unique_destination(directory, f"organizacao_{datetime.now():%Y%m%d_%H%M%S}.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except (OSError, ValueError) as error:
        report["aviso_salvamento"] = str(error)
        report_path = None
    return report, report_path


def read_organization_report(filename: Path) -> dict:
    """Aceita histórico da versão 1 (lista) e o formato rico da versão 2."""
    raw = json.loads(filename.read_text(encoding="utf-8-sig"))
    if isinstance(raw, list):
        events = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            source = Path(entry["origem"]) if entry.get("origem") else None
            destination = Path(entry["destino"]) if entry.get("destino") else None
            kind = "movido" if entry.get("status") == "movido" else "erro"
            events.append(_organization_event(kind, source, destination,
                          destination.parent.name if destination else "", details=entry.get("mensagem", "Registro antigo (v1)")))
        counts = Counter(event["tipo"] for event in events)
        return {
            "versao_relatorio": 1,
            "inicio": "Histórico anterior",
            "pasta_downloads": str(filename.parent.parent),
            "estado": "concluido_com_erros" if counts["erro"] else "concluido",
            "resumo": {
                "previstos": len(events), "arquivos_movidos": counts["movido"],
                "pastas_criadas": 0, "pastas_reutilizadas": 0,
                "arquivos_ignorados": 0, "pastas_preservadas": 0,
                "erros": counts["erro"], "bytes_movidos": 0,
                "por_categoria": dict(Counter(event["categoria"] for event in events if event["tipo"] == "movido")),
            },
            "eventos": events,
        }
    if not isinstance(raw, dict) or not isinstance(raw.get("eventos"), list) or not isinstance(raw.get("resumo"), dict):
        raise ValueError("O arquivo não é um relatório válido de organização.")
    return raw


def export_organization_report(report: dict, filename: Path, format_name: str) -> None:
    """Exporta um relatório visível para JSON, CSV (Excel) ou TXT."""
    if format_name == "json":
        filename.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    elif format_name == "csv":
        with filename.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=REPORT_FIELDS, extrasaction="ignore", delimiter=";")
            writer.writeheader()
            writer.writerows(report["eventos"])
    elif format_name == "txt":
        summary = report["resumo"]
        lines = ["PREPARADOR PC — RELATÓRIO DE ORGANIZAÇÃO", "",
                 f"Data: {report.get('inicio', '-')}", f"Downloads: {report.get('pasta_downloads', '-')}",
                 f"Estado: {report.get('estado', '-')}",
                 f"Arquivos movidos: {summary.get('arquivos_movidos', 0)}",
                 f"Pastas criadas: {summary.get('pastas_criadas', 0)}",
                 f"Pastas já existentes: {summary.get('pastas_reutilizadas', 0)}",
                 f"Arquivos ignorados: {summary.get('arquivos_ignorados', 0)}",
                 f"Subpastas preservadas: {summary.get('pastas_preservadas', 0)}",
                 f"Erros: {summary.get('erros', 0)}", "",
                 "POR CATEGORIA"]
        lines.extend(f"{cat}: {count} arquivo(s)" for cat, count in summary.get("por_categoria", {}).items())
        lines.extend(["", "DETALHES", ""])
        for entry in report["eventos"]:
            lines.extend([f"[{entry.get('horario', '-')}] {REPORT_LABELS.get(entry.get('tipo'), entry.get('tipo', '-'))}",
                          f"  Nome: {entry.get('nome', '-')}",
                          f"  Origem: {entry.get('origem', '-') or '-'}",
                          f"  Destino: {entry.get('destino', '-') or '-'}",
                          f"  Categoria: {entry.get('categoria', '-') or '-'}",
                          f"  Tamanho (bytes): {entry.get('tamanho_bytes', 0)}",
                          f"  Observações: {entry.get('detalhes', '-')}", ""])
        filename.write_text("\n".join(lines), encoding="utf-8-sig")
    else:
        raise ValueError("Formato de relatório não suportado")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def is_cloud_placeholder(path: Path) -> bool:
    """Evita baixar silenciosamente conteúdo que está somente na nuvem."""
    try:
        attrs = getattr(path.stat(), "st_file_attributes", 0)
        return bool(attrs & (0x1000 | 0x00040000 | 0x00400000))
    except OSError:
        return False


def iter_source_files(source: Path, on_error, on_skip):
    def fail(error):
        on_error(str(error))
    for current, dirs, files in os.walk(source, topdown=True, onerror=fail, followlinks=False):
        current_path = Path(current)
        allowed_dirs = []
        for dirname in dirs:
            folder = current_path / dirname
            try:
                attrs = getattr(folder.stat(), "st_file_attributes", 0)
                if folder.is_symlink() or attrs & 0x400:  # Windows reparse point / junction
                    on_skip({"arquivo": str(folder), "motivo": "Pasta de link simbólico/junção ignorada"})
                    continue
                allowed_dirs.append(dirname)
            except OSError as error:
                on_error(str(error))
        dirs[:] = allowed_dirs
        for filename in files:
            file = current_path / filename
            if file.is_symlink():
                on_skip({"arquivo": str(file), "motivo": "Link simbólico ignorado"})
            elif file.is_file():
                yield file


def installed_programs() -> list[dict]:
    """Consulta entradas de desinstalação (64/32 bits, sistema/usuário)."""
    if sys.platform != "win32":
        raise RuntimeError("O inventário de programas instalados é exclusivo do Windows.")
    import winreg

    uninstall_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    flags = (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY)
    programs: set[tuple[str, str, str]] = set()
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for flag in flags:
            try:
                with winreg.OpenKey(hive, uninstall_path, 0, winreg.KEY_READ | flag) as key:
                    for index in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            subkey = winreg.EnumKey(key, index)
                            with winreg.OpenKey(key, subkey) as item:
                                def read(name):
                                    try:
                                        return str(winreg.QueryValueEx(item, name)[0]).strip()
                                    except OSError:
                                        return ""
                                name = read("DisplayName")
                                if name and read("SystemComponent") != "1" and not read("ParentKeyName"):
                                    programs.add((name, read("DisplayVersion"), read("Publisher")))
                        except OSError:
                            continue
            except OSError:
                continue
    return [{"nome": name, "versao": version, "fabricante": publisher}
            for name, version, publisher in sorted(programs, key=lambda x: (x[0].casefold(), x[1]))]


def save_installed_programs(filename: Path, programs: list[dict]) -> None:
    """Grava inventário local em TXT, CSV ou JSON; nunca inclui serial/licença."""
    extension = filename.suffix.lower()
    if extension == ".json":
        payload = {"aplicacao": APP, "gerado_em": datetime.now().isoformat(timespec="seconds"),
                   "quantidade": len(programs), "programas": programs}
        filename.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    elif extension == ".csv":
        with filename.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=("nome", "versao", "fabricante"), delimiter=";")
            writer.writeheader()
            writer.writerows(programs)
    elif extension == ".txt":
        lines = [f"PROGRAMAS INSTALADOS - {datetime.now():%d/%m/%Y %H:%M}",
                 "Lista de referência para reinstalação. Não contém instaladores, licenças ou senhas.", ""]
        lines.extend(f"{app['nome']} | versão: {app['versao'] or '-'} | fabricante: {app['fabricante'] or '-'}"
                     for app in programs)
        filename.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    else:
        raise ValueError("Formato inválido: escolha TXT, CSV ou JSON")


def export_installed_programs(filename: Path) -> int:
    programs = installed_programs()
    save_installed_programs(filename, programs)
    return len(programs)


def vscode_user_folder() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Code" / "User"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User"
    return Path.home() / ".config" / "Code" / "User"


def _extension_command() -> str | None:
    for executable in ("code", "code.cmd"):
        found = shutil.which(executable)
        if found:
            return found
    if sys.platform == "win32":
        candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd",
                      Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft VS Code" / "bin" / "code.cmd"]
        return str(next((x for x in candidates if x.is_file()), "")) or None
    return None


def vscode_extensions(extensions_dir: Path | None = None, cli: str | None = None) -> tuple[list[dict], str, list[str]]:
    """Prioriza o comando oficial do VS Code, com leitura local como contingência."""
    found: dict[str, dict] = {}
    warnings: list[str] = []
    source = "diretório local"
    command = cli if cli is not None else _extension_command()
    if command:
        try:
            done = subprocess.run([command, "--list-extensions", "--show-versions"],
                                  capture_output=True, text=True, timeout=20, check=True)
            for line in done.stdout.splitlines():
                identifier, sep, version = line.strip().partition("@")
                if identifier and "." in identifier and all(c.isalnum() or c in "-_." for c in identifier):
                    found[identifier.casefold()] = {"identificador": identifier, "versao": version if sep else ""}
            source = "VS Code CLI"
        except (OSError, subprocess.SubprocessError) as error:
            warnings.append(f"Não foi possível consultar a CLI do VS Code: {error}")
    root = extensions_dir if extensions_dir is not None else Path.home() / ".vscode" / "extensions"
    if not found and root.is_dir():
        try:
            for folder in root.iterdir():
                if not folder.is_dir() or folder.is_symlink():
                    continue
                manifest = folder / "package.json"
                if not manifest.is_file() or manifest.is_symlink():
                    continue
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8-sig"))
                    identifier = f"{data.get('publisher', '')}.{data.get('name', '')}"
                    if identifier.count(".") >= 1 and all(c.isalnum() or c in "-_." for c in identifier):
                        found[identifier.casefold()] = {"identificador": identifier, "versao": str(data.get("version", ""))}
                except (OSError, ValueError, UnicodeError):
                    warnings.append(f"Manifesto de extensão não lido: {manifest.name}")
        except OSError as error:
            warnings.append(f"Não foi possível analisar as extensões locais: {error}")
    if not found:
        warnings.append("Nenhuma extensão encontrada; confirme se o VS Code está instalado e o perfil correto está selecionado.")
    return sorted(found.values(), key=lambda x: x["identificador"].casefold()), source, warnings


VSCODE_CONFIGS = {"settings.json": "settings.json", "keybindings.json": "keybindings.json",
                  "snippets": "snippets"}


def export_vscode_environment(destination: Path, user_dir: Path,
                              selected_configs: set[str], extensions_dir: Path | None = None,
                              cli: str | None = None) -> tuple[dict, Path]:
    """Exporta extensões e SOMENTE configurações selecionadas, sem apagar originais.

    Atenção: settings.json pode conter tokens/chaves. É material privado, nunca para GitHub.
    """
    if not destination.is_dir():
        raise FileNotFoundError(f"Pasta de destino inexistente: {destination}")
    if any(choice not in VSCODE_CONFIGS for choice in selected_configs):
        raise ValueError("Configuração do VS Code não reconhecida")
    dest_real = destination.resolve()
    if dest_real == user_dir.resolve() or dest_real.is_relative_to(user_dir.resolve()):
        raise ValueError("O destino não pode ficar dentro do diretório de configurações do VS Code")
    output = unique_destination(destination, f"VSCode_{datetime.now():%Y%m%d_%H%M%S}")
    output.mkdir()
    entries: list[dict] = []
    errors: list[str] = []
    extension_list, ext_source, warnings = vscode_extensions(extensions_dir, cli)
    lines = [f"{x['identificador']}@{x['versao']}" if x["versao"] else x["identificador"] for x in extension_list]
    (output / "extensoes_vscode.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (output / "extensoes_vscode.json").write_text(json.dumps(extension_list, ensure_ascii=False, indent=2), encoding="utf-8")
    entries.append({"status": "salvo", "origem": ext_source, "destino": str(output / "extensoes_vscode.txt"),
                    "detalhes": f"{len(extension_list)} extensões"})
    config_output = output / "configuracoes"
    for key in sorted(selected_configs):
        original = user_dir / VSCODE_CONFIGS[key]
        if original.is_symlink() or is_cloud_placeholder(original):
            entries.append({"status": "ignorado", "origem": str(original), "destino": "",
                            "detalhes": "Link simbólico ou item disponível apenas na nuvem"})
            continue
        if not original.exists():
            entries.append({"status": "ignorado", "origem": str(original), "destino": "",
                            "detalhes": "Configuração selecionada não encontrada"})
            continue
        if original.is_file():
            candidates = [original]
        elif original.is_dir() and key == "snippets":
            candidates = list(iter_source_files(original, errors.append,
                          lambda entry: entries.append({"status": "ignorado", "origem": entry["arquivo"],
                                                        "destino": "", "detalhes": entry["motivo"]})))
        else:
            errors.append(f"Configuração não é arquivo/diretório válido: {original}")
            continue
        for file in candidates:
            target = config_output / key if original.is_file() else config_output / key / file.relative_to(original)
            try:
                if file.is_symlink() or is_cloud_placeholder(file):
                    entries.append({"status": "ignorado", "origem": str(file), "destino": "",
                                    "detalhes": "Link ou arquivo apenas na nuvem"})
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
                if sha256(file) != sha256(target):
                    raise IOError("Falha na verificação SHA-256")
                entries.append({"status": "salvo", "origem": str(file), "destino": str(target),
                                "detalhes": "SHA-256 verificado"})
            except OSError as error:
                errors.append(f"{file}: {error}")
                entries.append({"status": "erro", "origem": str(file), "destino": str(target), "detalhes": str(error)})
    report = {"aplicacao": APP, "versao": APP_VERSION, "operacao": "exportar_vscode",
              "data": datetime.now().isoformat(timespec="seconds"),
              "origem_configuracoes": str(user_dir), "destino": str(output),
              "extensoes": len(extension_list), "fonte_extensoes": ext_source,
              "configuracoes_selecionadas": sorted(selected_configs),
              "arquivos_salvos": sum(x["status"] == "salvo" for x in entries) - 1,
              "arquivos_ignorados": sum(x["status"] == "ignorado" for x in entries),
              "erros": errors, "avisos": warnings, "eventos": entries}
    (output / "relatorio_vscode.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "LEIA-ME.txt").write_text(
        "EXPORTAÇÃO VS CODE\n\nA lista de extensões está em extensoes_vscode.txt.\n"
        "Após instalar o VS Code, restaure cada extensão com: code --install-extension IDENTIFICADOR\n"
        "As configurações selecionadas estão na pasta configuracoes.\n"
        "CUIDADO: settings.json pode conter credenciais! Guarde em mídia privada, nunca publique no GitHub.\n",
        encoding="utf-8")
    return report, output


class PreparadorPC(Tk):
    def __init__(self):
        super().__init__()
        self.title("Preparador PC | Antes de formatar")
        self.geometry("1000x740")
        self.minsize(800, 600)
        self.configure(bg="#F3F4F8")
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("TFrame", background="#F3F4F8")
        self.style.configure("TLabel", background="#F3F4F8", foreground="#263044", font=("Segoe UI", 10))
        self.style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"), foreground="#17213B")
        self.style.configure("Info.TLabel", font=("Segoe UI", 10), foreground="#58647B")
        self.style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        self.style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), foreground="#FFFFFF", background="#4958A8")
        self.style.map("Accent.TButton", background=[("active", "#35438A"), ("disabled", "#A4A8C4")])
        self.style.configure("TNotebook", background="#F3F4F8", borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(16, 10), font=("Segoe UI", 10))
        self.style.configure("Treeview", font=("Segoe UI", 9), rowheight=26)
        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

        self.folders = default_folders()
        self.download_var = StringVar(value=str(self.folders["Downloads"]))
        self.screenshot_var = StringVar(value=str(self.folders["Capturas de tela"]))
        self.backup_dest_var = StringVar()
        self.vscode_dest_var = StringVar()
        self.vscode_user_var = StringVar(value=str(vscode_user_folder()))
        self.vscode_config_vars = {"settings.json": BooleanVar(value=False),
                                   "keybindings.json": BooleanVar(value=True),
                                   "snippets": BooleanVar(value=False)}
        self.move_plan: list[MovePlan] = []
        self.last_organization_report: dict | None = None
        self.last_organization_path: Path | None = None
        self.history_files: dict[str, Path | None] = {}
        self.history_report: dict | None = None
        self.extra_sources: list[Path] = []
        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.backup_running = False
        self.folder_options = {name: BooleanVar(value=(name == "Capturas de tela")) for name in self.folders}

        container = ttk.Frame(self, padding=20)
        container.pack(fill="both", expand=True)
        ttk.Label(container, text="Preparador PC", style="Title.TLabel").pack(anchor="w")
        ttk.Label(container, text="Organize seus arquivos, faça backup e confira tudo antes de formatar.", style="Info.TLabel").pack(anchor="w", pady=(2, 14))
        self.tabs = ttk.Notebook(container)
        self.tabs.pack(fill="both", expand=True)
        downloads = ttk.Frame(self.tabs, padding=16)
        backup = ttk.Frame(self.tabs, padding=16)
        history = ttk.Frame(self.tabs, padding=16)
        inventory = ttk.Frame(self.tabs, padding=16)
        checklist = ttk.Frame(self.tabs, padding=16)
        self.history_tab = history
        self.tabs.add(downloads, text="1  Organizar Downloads")
        self.tabs.add(backup, text="2  Fazer backup")
        self.tabs.add(history, text="3  Histórico")
        self.tabs.add(inventory, text="4  Inventário e VS Code")
        self.tabs.add(checklist, text="5  Checklist")
        self.setup_downloads(downloads)
        self.download_var.trace_add("write", lambda *_: self.clear_move_preview())
        self.setup_backup(backup)
        self.setup_history(history)
        self.setup_inventory(inventory)
        self.setup_checklist(checklist)
        self.refresh_history()
        self.status = StringVar(value="Pronto. Nenhuma alteração foi realizada.")
        ttk.Label(container, textvariable=self.status, style="Info.TLabel").pack(anchor="w", pady=(10, 0))
        self.after(120, self.process_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def row_picker(self, parent, title, variable, callback):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(8, 5))
        ttk.Label(frame, text=title).pack(anchor="w", pady=(0, 4))
        inner = ttk.Frame(frame)
        inner.pack(fill="x")
        ttk.Entry(inner, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(inner, text="Selecionar pasta", command=callback).pack(side="right")

    def pick_folder(self, variable):
        existing = variable.get()
        picked = filedialog.askdirectory(initialdir=existing if Path(existing).is_dir() else str(Path.home()))
        if picked:
            variable.set(picked)

    def setup_downloads(self, tab):
        ttk.Label(tab, text="Organizar por extensão", style="Title.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Move apenas arquivos soltos. Não altera subpastas nem arquivos de downloads incompletos.", style="Info.TLabel").pack(anchor="w", pady=(4, 8))
        self.row_picker(tab, "Pasta Downloads", self.download_var, lambda: self.pick_folder(self.download_var))
        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=(8, 10))
        ttk.Button(bar, text="Ver prévia", command=self.preview_moves).pack(side="left")
        self.move_button = ttk.Button(bar, text="Organizar arquivos", style="Accent.TButton", command=self.execute_moves)
        self.move_button.pack(side="left", padx=8)
        ttk.Button(bar, text="Ver o que foi feito", command=self.show_history).pack(side="left")
        self.move_summary = StringVar(value="Gere a prévia antes de organizar.")
        ttk.Label(bar, textvariable=self.move_summary, style="Info.TLabel").pack(side="right")
        columns = ("arquivo", "pasta", "destino")
        table_frame = ttk.Frame(tab)
        table_frame.pack(fill="both", expand=True)
        self.move_tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for key, heading, width in [("arquivo", "Arquivo", 280), ("pasta", "Categoria", 170), ("destino", "Novo nome", 290)]:
            self.move_tree.heading(key, text=heading)
            self.move_tree.column(key, width=width, stretch=True)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.move_tree.yview)
        self.move_tree.configure(yscrollcommand=scrollbar.set)
        self.move_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Label(tab, text="Segurança: os nomes duplicados ganham numeração; nenhum arquivo é excluído ou substituído.", style="Info.TLabel").pack(anchor="w", pady=(10, 0))

    def clear_move_preview(self):
        self.move_plan.clear()
        self.move_tree.delete(*self.move_tree.get_children())
        self.move_summary.set("Gere uma nova prévia.")

    def preview_moves(self):
        try:
            path = Path(self.download_var.get()).expanduser()
            self.move_plan = make_move_plan(path)
            self.move_tree.delete(*self.move_tree.get_children())
            for move in self.move_plan:
                self.move_tree.insert("", END, values=(move.source.name, move.destination.parent.name, move.destination.name))
            categories = len({move.destination.parent.name for move in self.move_plan})
            self.move_summary.set(f"{len(self.move_plan)} arquivos • {categories} categorias")
            self.status.set("Prévia gerada. Nenhum arquivo foi movido.")
        except (OSError, ValueError) as error:
            self.move_plan = []
            messagebox.showerror("Não foi possível ler Downloads", str(error))

    def execute_moves(self):
        if not self.move_plan:
            self.preview_moves()
            if not self.move_plan:
                messagebox.showinfo(APP, "Nenhum arquivo solto para organizar. Consulte a aba Histórico para ver execuções anteriores.")
                return
        downloads = Path(self.download_var.get()).expanduser()
        if any(plan.source.parent.resolve() != downloads.resolve() for plan in self.move_plan):
            self.clear_move_preview()
            messagebox.showwarning(APP, "A pasta Downloads mudou. Gere uma nova prévia.")
            return
        if not messagebox.askyesno("Confirmar organização", f"Mover {len(self.move_plan)} arquivos para pastas por categoria?\n\nAs subpastas existentes serão preservadas.\nUm relatório detalhado será gerado."):
            return
        try:
            report, report_path = run_downloads_organization(downloads, self.move_plan)
        except (OSError, ValueError) as error:
            messagebox.showerror("Falha ao organizar", str(error))
            return
        self.last_organization_report = report
        self.last_organization_path = report_path
        self.move_plan.clear()
        self.preview_moves()
        summary = report["resumo"]
        moved = summary["arquivos_movidos"]
        errors = summary["erros"]
        self.status.set(f"Organização concluída: {moved} arquivos movidos, {summary['pastas_criadas']} pastas criadas, {errors} erro(s).")
        self.refresh_history(select_path=report_path, show_current=True)
        self.tabs.select(self.history_tab)
        note = f"\nRelatório salvo em:\n{report_path}" if report_path else (
            f"\nAtenção: relatório não salvo automaticamente. Exporte-o pela aba Histórico.\n{report.get('aviso_salvamento', '')}")
        messagebox.showinfo("Organização finalizada", f"Arquivos movidos: {moved}\n"
                             f"Pastas criadas: {summary['pastas_criadas']}\n"
                             f"Arquivos ignorados: {summary['arquivos_ignorados']}\n"
                             f"Erros: {errors}\n\n"
                             f"Os detalhes estão na aba Histórico.{note}")

    def show_history(self):
        self.refresh_history(select_path=self.last_organization_path, show_current=True)
        self.tabs.select(self.history_tab)

    def setup_history(self, tab):
        ttk.Label(tab, text="Histórico da organização", style="Title.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Consulte pastas criadas, arquivos movidos, origem, destino, ignorados e falhas. Os relatórios ficam na pasta Downloads.", style="Info.TLabel").pack(anchor="w", pady=(4, 12))
        chooser = ttk.Frame(tab)
        chooser.pack(fill="x", pady=(0, 8))
        ttk.Label(chooser, text="Execução:").pack(side="left", padx=(0, 8))
        self.history_choice = StringVar(value="")
        self.history_combo = ttk.Combobox(chooser, textvariable=self.history_choice, state="readonly", width=43)
        self.history_combo.pack(side="left", fill="x", expand=True)
        self.history_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_selected_history())
        ttk.Button(chooser, text="Atualizar", command=self.refresh_history).pack(side="left", padx=(8, 0))
        ttk.Button(chooser, text="Abrir JSON...", command=self.import_history).pack(side="left", padx=(8, 0))

        self.history_summary = StringVar(value="Selecione uma execução para consultar.")
        ttk.Label(tab, textvariable=self.history_summary, style="Info.TLabel", wraplength=880).pack(anchor="w", pady=(3, 4))
        self.history_categories = StringVar(value="")
        ttk.Label(tab, textvariable=self.history_categories, style="Info.TLabel", wraplength=880).pack(anchor="w", pady=(0, 8))
        filters = ttk.Frame(tab)
        filters.pack(fill="x", pady=(0, 8))
        ttk.Label(filters, text="Mostrar:").pack(side="left", padx=(0, 8))
        self.history_filter = StringVar(value="Tudo")
        choices = ["Tudo", "Arquivos movidos", "Pastas criadas", "Pastas existentes", "Arquivos ignorados", "Pastas preservadas", "Erros"]
        filter_control = ttk.Combobox(filters, values=choices, textvariable=self.history_filter, width=22, state="readonly")
        filter_control.pack(side="left")
        filter_control.bind("<<ComboboxSelected>>", lambda _event: self.populate_history())
        ttk.Label(filters, text="Buscar:").pack(side="left", padx=(16, 8))
        self.history_search = StringVar(value="")
        self.history_search.trace_add("write", lambda *_: self.populate_history())
        ttk.Entry(filters, textvariable=self.history_search).pack(side="left", fill="x", expand=True)
        self.history_visible_count = StringVar(value="")
        ttk.Label(filters, textvariable=self.history_visible_count, style="Info.TLabel").pack(side="right", padx=(12, 0))

        list_area = ttk.Frame(tab)
        list_area.pack(fill="both", expand=True)
        columns = ("acao", "arquivo", "categoria", "origem", "destino", "detalhes")
        self.history_tree = ttk.Treeview(list_area, columns=columns, show="headings", selectmode="browse", height=10)
        for column, heading, width in [
            ("acao", "Ação", 145), ("arquivo", "Arquivo / pasta", 205),
            ("categoria", "Categoria", 120), ("origem", "Origem", 255),
            ("destino", "Destino", 255), ("detalhes", "Observações", 270),
        ]:
            self.history_tree.heading(column, text=heading)
            self.history_tree.column(column, width=width, stretch=False)
        yscroll = ttk.Scrollbar(list_area, orient="vertical", command=self.history_tree.yview)
        xscroll = ttk.Scrollbar(list_area, orient="horizontal", command=self.history_tree.xview)
        self.history_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        list_area.columnconfigure(0, weight=1)
        list_area.rowconfigure(0, weight=1)
        self.history_tree.tag_configure("erro", foreground="#A12736")
        self.history_tree.tag_configure("ignorado", foreground="#765B2C")
        self.history_tree.tag_configure("pasta_criada", foreground="#246A56")
        self.history_tree.bind("<<TreeviewSelect>>", lambda _event: self.show_history_detail())

        ttk.Label(tab, text="Detalhes do item selecionado:").pack(anchor="w", pady=(8, 3))
        self.history_detail = tk.Text(tab, height=5, state="disabled", bg="#FFFFFF", fg="#263044", relief="flat",
                                      font=("Consolas", 9), wrap="word", padx=8, pady=6)
        self.history_detail.pack(fill="x")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=(9, 0))
        ttk.Button(actions, text="Exportar relatório...", style="Accent.TButton", command=self.export_history).pack(side="left")
        ttk.Button(actions, text="Abrir pasta dos relatórios", command=self.open_history_folder).pack(side="left", padx=8)
        ttk.Button(actions, text="Copiar detalhes", command=self.copy_history_detail).pack(side="left")
        ttk.Label(actions, text="Exporte para outro disco antes de formatar.", style="Info.TLabel").pack(side="right")

    def refresh_history(self, select_path: Path | None = None, show_current: bool = False):
        """Pesquisa execuções em Downloads, inclusive de sessões anteriores."""
        old_path = self.history_files.get(self.history_choice.get())
        directory = Path(self.download_var.get()).expanduser() / REPORTS_DIR
        discovered = {}
        try:
            if directory.is_dir() and not directory.is_symlink():
                for path in sorted(directory.glob("organizacao_*.json"), key=lambda p: p.name, reverse=True):
                    if path.is_file():
                        discovered[path.name] = path
        except OSError as error:
            messagebox.showwarning(APP, f"Não foi possível listar relatórios: {error}")
        self.history_files = discovered
        if show_current and self.last_organization_report is not None:
            self.history_files = {"Execução atual": self.last_organization_path, **self.history_files}
        self.history_combo.configure(values=list(self.history_files))
        wanted = select_path if select_path is not None else old_path
        selection = next((name for name, path in self.history_files.items()
                          if path == wanted and (path is not None or name == "Execução atual")), None)
        if selection is None:
            selection = next(iter(self.history_files), "")
        self.history_choice.set(selection)
        self.load_selected_history()

    def import_history(self):
        chosen = filedialog.askopenfilename(title="Abrir relatório de organização", filetypes=[("Relatório JSON", "*.json")])
        if not chosen:
            return
        try:
            report = read_organization_report(Path(chosen))
        except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
            messagebox.showerror(APP, f"Não foi possível abrir o relatório:\n{error}")
            return
        label = f"Arquivo externo: {Path(chosen).name}"
        self.history_files[label] = Path(chosen)
        self.history_combo.configure(values=list(self.history_files))
        self.history_choice.set(label)
        self.history_report = report
        self.populate_history()

    def load_selected_history(self):
        label = self.history_choice.get()
        path = self.history_files.get(label)
        if label == "Execução atual" and self.last_organization_report is not None:
            self.history_report = self.last_organization_report
        elif path is not None:
            try:
                self.history_report = read_organization_report(path)
            except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as error:
                self.history_report = None
                messagebox.showerror(APP, f"Não foi possível ler o relatório:\n{error}")
        else:
            self.history_report = None
        self.populate_history()

    def populate_history(self):
        self.history_tree.delete(*self.history_tree.get_children())
        self.set_history_detail("")
        report = self.history_report
        if report is None:
            self.history_summary.set("Nenhum relatório nesta pasta Downloads. Organize arquivos ou abra um relatório JSON.")
            self.history_categories.set("")
            self.history_visible_count.set("0 registros")
            return
        summary = report["resumo"]
        self.history_summary.set(
            f"{report.get('inicio', 'Execução anterior')}  |  "
            f"Movidos: {summary.get('arquivos_movidos', 0)}  •  "
            f"Pastas criadas: {summary.get('pastas_criadas', 0)}  •  "
            f"Já existentes: {summary.get('pastas_reutilizadas', 0)}  •  "
            f"Ignorados: {summary.get('arquivos_ignorados', 0)}  •  "
            f"Erros: {summary.get('erros', 0)}  |  "
            f"Total: {summary.get('bytes_movidos', 0) / 1024**2:.2f} MB")
        categories = summary.get("por_categoria", {})
        self.history_categories.set("Movidos por categoria: " + ("  •  ".join(f"{name}: {count}" for name, count in categories.items()) if categories else "nenhum arquivo"))
        filters = {"Arquivos movidos": "movido", "Pastas criadas": "pasta_criada",
                   "Pastas existentes": "pasta_reutilizada", "Arquivos ignorados": "ignorado",
                   "Pastas preservadas": "pasta_preservada", "Erros": "erro"}
        kind = filters.get(self.history_filter.get())
        search = self.history_search.get().strip().casefold()
        for index, entry in enumerate(report["eventos"]):
            if kind and entry.get("tipo") != kind:
                continue
            if search and not any(search in str(value).casefold() for value in entry.values()):
                continue
            self.history_tree.insert("", END, iid=str(index), values=(
                REPORT_LABELS.get(entry.get("tipo", ""), entry.get("tipo", "")),
                entry.get("nome", ""), entry.get("categoria", ""),
                entry.get("origem", ""), entry.get("destino", ""), entry.get("detalhes", ""),
            ), tags=(entry.get("tipo", ""),))
        self.history_visible_count.set(f"{len(self.history_tree.get_children())} registros")

    def show_history_detail(self):
        selected = self.history_tree.selection()
        if not selected or self.history_report is None:
            self.set_history_detail("")
            return
        entry = self.history_report["eventos"][int(selected[0])]
        self.set_history_detail("\n".join([
            f"Ação: {REPORT_LABELS.get(entry.get('tipo', ''), entry.get('tipo', ''))}",
            f"Hora: {entry.get('horario', '-')}",
            f"Origem: {entry.get('origem', '-') or '-'}",
            f"Destino: {entry.get('destino', '-') or '-'}",
            f"Tamanho: {entry.get('tamanho_bytes', 0)} bytes",
            f"Observação: {entry.get('detalhes', '-')}",
        ]))

    def set_history_detail(self, message: str):
        self.history_detail.configure(state="normal")
        self.history_detail.delete("1.0", END)
        self.history_detail.insert("1.0", message)
        self.history_detail.configure(state="disabled")

    def copy_history_detail(self):
        detail = self.history_detail.get("1.0", "end-1c")
        if detail:
            self.clipboard_clear()
            self.clipboard_append(detail)
            self.status.set("Detalhes copiados para a área de transferência.")

    def export_history(self):
        report = self.history_report
        if not report:
            messagebox.showinfo(APP, "Selecione um relatório antes de exportar.")
            return
        formats = [("Relatório de texto", "*.txt"), ("Planilha CSV", "*.csv"), ("Relatório JSON", "*.json")]
        filename = filedialog.asksaveasfilename(
            title="Exportar histórico para guardar com seu backup", defaultextension=".txt",
            filetypes=formats, initialfile=f"relatorio_organizacao_{datetime.now():%Y%m%d_%H%M%S}.txt")
        if not filename:
            return
        target = Path(filename)
        format_name = target.suffix.lower().lstrip(".")
        try:
            export_organization_report(report, target, format_name)
            self.status.set(f"Relatório exportado: {target}")
            messagebox.showinfo(APP, f"Relatório exportado com sucesso para:\n{target}")
        except (OSError, ValueError) as error:
            messagebox.showerror(APP, f"Falha ao exportar:\n{error}")

    def open_history_folder(self):
        selected_path = self.history_files.get(self.history_choice.get())
        target = (selected_path.parent if selected_path is not None else
                  Path(self.download_var.get()).expanduser() / REPORTS_DIR)
        if not target.is_dir():
            messagebox.showwarning(APP, "A pasta de relatórios ainda não existe.")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(target))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as error:
            messagebox.showerror(APP, f"Não foi possível abrir a pasta:\n{error}")

    def setup_backup(self, tab):
        ttk.Label(tab, text="Backup de arquivos pessoais", style="Title.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Copia os arquivos para um novo diretório e confere o SHA-256 de cada cópia.", style="Info.TLabel").pack(anchor="w", pady=(4, 8))
        self.row_picker(tab, "Destino do backup (preferencialmente HD externo ou pendrive)", self.backup_dest_var, lambda: self.pick_folder(self.backup_dest_var))
        self.row_picker(tab, "Local das capturas de tela", self.screenshot_var, lambda: self.pick_folder(self.screenshot_var))
        ttk.Label(tab, text="O que copiar?").pack(anchor="w", pady=(10, 4))
        options = ttk.Frame(tab)
        options.pack(fill="x")
        for i, (name, variable) in enumerate(self.folder_options.items()):
            ttk.Checkbutton(options, text=name, variable=variable).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 26), pady=4)
        ttk.Label(tab, text="Pastas adicionais").pack(anchor="w", pady=(10, 4))
        extra = ttk.Frame(tab)
        extra.pack(fill="x")
        self.extra_list = tk.Listbox(extra, height=3, selectmode=tk.SINGLE, borderwidth=1, relief="solid", font=("Segoe UI", 9))
        self.extra_list.pack(side="left", fill="x", expand=True, padx=(0, 8))
        side = ttk.Frame(extra)
        side.pack(side="right")
        ttk.Button(side, text="Adicionar pasta", command=self.add_extra).pack(fill="x", pady=(0, 6))
        ttk.Button(side, text="Remover seleção", command=self.remove_extra).pack(fill="x")
        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(12, 5))
        self.backup_button = ttk.Button(controls, text="Iniciar backup", style="Accent.TButton", command=self.start_backup)
        self.backup_button.pack(side="left")
        self.cancel_button = ttk.Button(controls, text="Cancelar", command=self.cancel_backup, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        ttk.Button(controls, text="Visualizar relatório de backup", command=self.view_backup_report).pack(side="right")
        self.progress = ttk.Progressbar(tab, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 6))
        self.progress_text = StringVar(value="Nenhum backup iniciado.")
        ttk.Label(tab, textvariable=self.progress_text, style="Info.TLabel").pack(anchor="w")
        self.log = tk.Text(tab, height=9, state="disabled", bg="#FFFFFF", fg="#283148", relief="flat", font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", expand=True, pady=(8, 0))

    def add_extra(self):
        chosen = filedialog.askdirectory(initialdir=str(Path.home()))
        if chosen:
            path = Path(chosen)
            if path not in self.extra_sources:
                self.extra_sources.append(path)
                self.extra_list.insert(END, str(path))

    def remove_extra(self):
        selected = self.extra_list.curselection()
        if selected:
            del self.extra_sources[selected[0]]
            self.extra_list.delete(selected[0])

    def gather_sources(self) -> list[tuple[str, Path]]:
        selected = []
        for name, checked in self.folder_options.items():
            if checked.get():
                path = Path(self.screenshot_var.get()).expanduser() if name == "Capturas de tela" else self.folders[name]
                selected.append((name, path))
        selected += [(f"Personalizada {i:02d} - {path.name}", path) for i, path in enumerate(self.extra_sources, 1)]
        return selected

    def start_backup(self):
        if self.backup_running:
            return
        destination_text = self.backup_dest_var.get().strip()
        if not destination_text:
            messagebox.showwarning(APP, "Selecione a pasta onde o backup será salvo.")
            return
        destination = Path(destination_text).expanduser()
        if not destination.is_dir():
            messagebox.showwarning(APP, "O destino precisa ser uma pasta existente e acessível.")
            return
        sources = self.gather_sources()
        if not sources:
            messagebox.showwarning(APP, "Marque pelo menos uma pasta ou adicione uma pasta personalizada.")
            return
        missing = [str(path) for _, path in sources if not path.is_dir()]
        if missing:
            messagebox.showwarning("Pasta não encontrada", "Corrija estas pastas antes de continuar:\n" + "\n".join(missing))
            return
        dest_resolved = destination.resolve()
        for label, path in sources:
            src_resolved = path.resolve()
            if dest_resolved == src_resolved or dest_resolved.is_relative_to(src_resolved):
                messagebox.showerror("Destino inválido", f"O destino do backup está dentro da pasta de origem '{label}'.\nEscolha um local fora das pastas copiadas.")
                return
        if sys.platform == "win32" and any(os.path.splitdrive(str(path.resolve()))[0].casefold() == os.path.splitdrive(str(dest_resolved))[0].casefold() for _, path in sources):
            if not messagebox.askyesno("Backup na mesma unidade", "Origem e destino estão na mesma letra de unidade. Isso NÃO protege os arquivos caso a unidade seja formatada.\n\nDeseja continuar mesmo assim?"):
                return
        if not messagebox.askyesno("Confirmar backup", f"Copiar {len(sources)} pasta(s) para:\n{destination}\n\nOs arquivos originais serão mantidos e as cópias serão verificadas."):
            return
        self.cancel_event.clear()
        self.backup_running = True
        self.backup_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.progress.configure(value=0, maximum=100)
        self.progress_text.set("Preparando backup...")
        worker = threading.Thread(target=self.worker_backup, args=(destination, sources), daemon=True)
        worker.start()

    def worker_backup(self, destination: Path, sources: list[tuple[str, Path]]):
        started = datetime.now().isoformat(timespec="seconds")
        output = None
        records = []
        errors = []
        skipped = []

        def record_error(message):
            errors.append(message)
            records.append({"status": "erro", "origem": "", "destino": "", "erro": message})

        def record_skip(entry):
            skipped.append(entry)
            records.append({"status": "ignorado", "origem": entry.get("arquivo", ""),
                            "destino": "", "motivo": entry.get("motivo", "")})

        total_bytes = 0
        total_files = 0
        copied = 0
        bytes_copied = 0
        try:
            base = f"PreparadorPC_{datetime.now():%Y%m%d_%H%M%S}"
            output = destination / base
            number = 1
            while True:
                try:
                    output.mkdir(exist_ok=False)
                    break
                except FileExistsError:
                    output = destination / f"{base}_{number}"
                    number += 1
            self.queue.put(("log", f"Backup em: {output}"))
            self.queue.put(("status", "Analisando arquivos e espaço disponível..."))
            planned = []
            for label, source in sources:
                if self.cancel_event.is_set():
                    break
                for file in iter_source_files(source, record_error, record_skip):
                    if self.cancel_event.is_set():
                        break
                    try:
                        if is_cloud_placeholder(file):
                            record_skip({"arquivo": str(file), "motivo": "Somente na nuvem / não disponível localmente"})
                            continue
                        file_size = file.stat().st_size
                        planned.append((label, source, file, file_size))
                        total_bytes += file_size
                    except OSError as error:
                        record_error(f"{file}: {error}")
            stopped_for_space = False
            if not self.cancel_event.is_set():
                reserve = 50 * 1024 * 1024
                space_free = shutil.disk_usage(output).free
                if total_bytes + reserve > space_free:
                    record_error(f"Espaço insuficiente: arquivos somam {total_bytes:,} bytes, disponíveis {space_free:,} bytes.")
                    stopped_for_space = True
                    self.cancel_event.set()
            total_files = len(planned)
            self.queue.put(("log", f"Encontrados: {total_files} arquivos; {total_bytes / 1024**3:.2f} GB"))
            processed = 0
            for label, source, file, size in planned:
                if self.cancel_event.is_set():
                    break
                target = output / label / file.relative_to(source)
                try:
                    if not file.exists():
                        raise FileNotFoundError("Arquivo removido durante o backup")
                    if is_cloud_placeholder(file):
                        record_skip({"arquivo": str(file), "motivo": "Ficou somente na nuvem durante a execução"})
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        raise FileExistsError("Cópia já existente, preservada")
                    shutil.copy2(file, target)
                    original_hash = sha256(file)
                    copied_hash = sha256(target)
                    if original_hash != copied_hash:
                        raise IOError("SHA-256 diferente entre origem e cópia")
                    copied += 1
                    bytes_copied += size
                    records.append({"status": "verificado", "origem": str(file), "destino": str(target), "bytes": size, "sha256": copied_hash})
                except (OSError, IOError) as error:
                    errors.append(f"{file}: {error}")
                    records.append({"status": "erro", "origem": str(file), "destino": str(target), "erro": str(error)})
                processed += 1
                self.queue.put(("progress", (min(100, round(processed * 100 / max(total_files, 1))), f"Verificados: {copied} / {total_files} arquivos")))
            state = "erro_espaco_insuficiente" if stopped_for_space else ("cancelado" if self.cancel_event.is_set() else ("concluido_com_pendencias" if errors or skipped else "concluido"))
            report = {
                "aplicacao": APP,
                "inicio": started,
                "fim": datetime.now().isoformat(timespec="seconds"),
                "estado": state,
                "origens": [{"categoria": name, "caminho": str(p)} for name, p in sources],
                "destino": str(output),
                "arquivos_previstos": total_files,
                "arquivos_verificados": copied,
                "arquivos_salvos": copied,
                "arquivos_ignorados": len(skipped),
                "bytes_verificados": bytes_copied,
                "erros": errors,
                "arquivos_nao_copiados": skipped,
                "arquivos": records,
            }
            try:
                (output / "relatorio_backup.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                with (output / "relatorio_backup.csv").open("w", newline="", encoding="utf-8-sig") as csv_stream:
                    writer = csv.DictWriter(csv_stream, fieldnames=("status", "origem", "destino", "bytes", "sha256", "erro", "motivo"),
                                            extrasaction="ignore", delimiter=";")
                    writer.writeheader()
                    writer.writerows(records)
                lines = [f"PREPARADOR PC - {datetime.now():%d/%m/%Y %H:%M}", f"Estado: {state}", f"Backup: {output}", f"Arquivos verificados: {copied} de {total_files}", f"Erros: {len(errors)}", f"Somente na nuvem / ignorados: {len(skipped)}", "", "A formatação deve ocorrer SOMENTE após validar os arquivos no destino."]
                if errors:
                    lines.extend(["", "ERROS", *errors[:200]])
                if skipped:
                    lines.extend(["", "IGNORADOS", *(f"{item['arquivo']}: {item['motivo']}" for item in skipped[:200])])
                if len(errors) > 200 or len(skipped) > 200:
                    lines.append("Lista abreviada: consulte relatorio_backup.json para todos os itens.")
                (output / "resumo_backup.txt").write_text("\n".join(lines), encoding="utf-8")
            except OSError as error:
                errors.append(f"Não foi possível gravar o relatório: {error}")
            self.queue.put(("finished", (state, output, copied, total_files, len(errors), len(skipped))))
        except Exception as error:
            self.queue.put(("finished", ("erro", output, copied, total_files, len(errors) + 1, len(skipped))))
            self.queue.put(("log", f"Falha geral: {error}"))

    def cancel_backup(self):
        self.cancel_event.set()
        self.progress_text.set("Cancelamento solicitado. Os arquivos já copiados serão preservados.")

    def process_queue(self):
        try:
            for _ in range(200):
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self.log.config(state="normal")
                    self.log.insert(END, payload + "\n")
                    self.log.see(END)
                    self.log.config(state="disabled")
                elif kind == "status":
                    self.progress_text.set(payload)
                elif kind == "progress":
                    amount, details = payload
                    self.progress.configure(value=amount)
                    self.progress_text.set(details)
                elif kind == "finished":
                    state, folder, copied, planned, errors, skipped = payload
                    self.backup_running = False
                    self.backup_button.config(state="normal")
                    self.cancel_button.config(state="disabled")
                    self.status.set(f"Backup: {state}. Arquivos conferidos: {copied} de {planned}.")
                    self.progress_text.set(f"Estado: {state} • verificados: {copied}/{planned} • erros: {errors} • não copiados: {skipped}")
                    self.log.config(state="normal")
                    self.log.insert(END, f"Finalizado: {folder}\n")
                    self.log.see(END)
                    self.log.config(state="disabled")
                    messagebox.showinfo("Resultado do backup", f"Estado: {state}\nArquivos verificados: {copied}/{planned}\nErros: {errors}\nNão copiados: {skipped}\n\nLocal: {folder}\n\nConfira o relatório e abra arquivos de teste antes de formatar.")
        except queue.Empty:
            pass
        self.after(120, self.process_queue)

    def setup_inventory(self, tab):
        ttk.Label(tab, text="Programas e ambiente de desenvolvimento", style="Title.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Crie um inventário para reinstalar aplicativos e reconstruir o VS Code após a formatação.",
                  style="Info.TLabel").pack(anchor="w", pady=(5, 15))
        ttk.Label(tab, text="1. Programas instalados", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(tab, text="Lê o Registro do Windows sem alterar programas. Exporta nome, versão e fabricante.",
                  style="Info.TLabel").pack(anchor="w", pady=(3, 7))
        ttk.Button(tab, text="Exportar inventário (TXT, CSV ou JSON)", command=self.export_apps).pack(anchor="w")
        ttk.Separator(tab, orient="horizontal").pack(fill="x", pady=19)
        ttk.Label(tab, text="2. Extensões e configurações do VS Code", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(tab, text="Exporta a lista de extensões e copia apenas as configurações marcadas.",
                  style="Info.TLabel").pack(anchor="w", pady=(3, 7))
        self.row_picker(tab, "Pasta de configurações do VS Code", self.vscode_user_var,
                        lambda: self.pick_folder(self.vscode_user_var))
        self.row_picker(tab, "Salvar exportação em (preferencialmente unidade externa)", self.vscode_dest_var,
                        lambda: self.pick_folder(self.vscode_dest_var))
        ttk.Label(tab, text="Configurações que deseja preservar:").pack(anchor="w", pady=(10, 5))
        row = ttk.Frame(tab)
        row.pack(anchor="w")
        for name, variable in self.vscode_config_vars.items():
            ttk.Checkbutton(row, text=name, variable=variable).pack(side="left", padx=(0, 20))
        ttk.Label(tab, text="Atenção: settings.json pode conter tokens e chaves de acesso. Guarde o backup fora de repositórios públicos.",
                  style="Info.TLabel", wraplength=780).pack(anchor="w", pady=(11, 9))
        ttk.Button(tab, text="Exportar ambiente VS Code", style="Accent.TButton", command=self.export_vscode).pack(anchor="w")
        self.inventory_status = StringVar(value="Nenhum inventário exportado nesta sessão.")
        ttk.Label(tab, textvariable=self.inventory_status, style="Info.TLabel", wraplength=800).pack(anchor="w", pady=(14, 0))

    def export_apps(self):
        filename = filedialog.asksaveasfilename(
            title="Salvar lista de programas", defaultextension=".csv",
            filetypes=[("Planilha CSV", "*.csv"), ("Texto", "*.txt"), ("Dados JSON", "*.json")],
            initialfile="programas_instalados.csv")
        if not filename:
            return
        try:
            count = export_installed_programs(Path(filename))
            self.inventory_status.set(f"Programas exportados: {count} em {filename}")
            messagebox.showinfo(APP, f"Inventário de {count} programas salvo em:\n{filename}\n\n"
                                     "Verifique também apps portáteis, Microsoft Store e licenças separadamente.")
        except (OSError, RuntimeError, ValueError) as error:
            messagebox.showerror(APP, str(error))

    def export_vscode(self):
        path = Path(self.vscode_dest_var.get().strip()).expanduser()
        if not self.vscode_dest_var.get().strip() or not path.is_dir():
            messagebox.showwarning(APP, "Selecione uma pasta de destino existente para a exportação.")
            return
        user = Path(self.vscode_user_var.get().strip()).expanduser()
        selected = {name for name, enabled in self.vscode_config_vars.items() if enabled.get()}
        if selected and not user.is_dir():
            messagebox.showwarning(APP, "A pasta de configurações não existe. Corrija-a ou desmarque as configurações.")
            return
        if not messagebox.askyesno("Confirmar exportação", "Salvar extensões e configurações selecionadas?\n\n"
                                   "Configurações podem conter dados sensíveis. Não publique os arquivos em repositórios públicos."):
            return
        try:
            report, output = export_vscode_environment(path, user, selected)
            self.inventory_status.set(f"VS Code: {report['extensoes']} extensões, "
                                      f"{report['arquivos_salvos']} configurações. Salvo em {output}")
            messagebox.showinfo(APP, f"Exportação concluída em:\n{output}\n\n"
                                     f"Extensões: {report['extensoes']}\n"
                                     f"Arquivos copiados: {report['arquivos_salvos']}\n"
                                     f"Ignorados: {report['arquivos_ignorados']}\n"
                                     f"Erros: {len(report['erros'])}\n\nConsulte relatorio_vscode.json antes de formatar.")
        except (OSError, ValueError) as error:
            messagebox.showerror(APP, str(error))

    def view_backup_report(self):
        filename = filedialog.askopenfilename(title="Abrir relatório de backup",
                                              filetypes=[("Relatórios JSON", "*.json")],
                                              initialfile="relatorio_backup.json")
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or "arquivos" not in data or "estado" not in data:
                raise ValueError("Não é um relatório válido de backup")
        except (OSError, ValueError) as error:
            messagebox.showerror(APP, str(error))
            return
        window = tk.Toplevel(self)
        window.title("Auditoria do backup | Preparador PC")
        window.geometry("1050x610")
        frame = ttk.Frame(window, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Backup: {data['estado']} | "
                  f"Verificados: {data.get('arquivos_verificados', 0)} | "
                  f"Ignorados: {len(data.get('arquivos_nao_copiados', []))} | "
                  f"Erros: {len(data.get('erros', []))}", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        columns = ("status", "origem", "destino", "detalhes")
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        for key, width in (("status", 115), ("origem", 310), ("destino", 310), ("detalhes", 270)):
            tree.heading(key, text=key.capitalize())
            tree.column(key, width=width, stretch=key != "status")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for index, entry in enumerate(data["arquivos"]):
            tree.insert("", END, iid=str(index), values=(entry.get("status", ""), entry.get("origem", ""),
                                                           entry.get("destino", ""), entry.get("erro", entry.get("motivo", ""))))
        ttk.Label(frame, text="Todos os registros ficam salvos no JSON do backup. Inclui arquivos verificados, ignorados e falhas.",
                  style="Info.TLabel").pack(anchor="w", pady=(9, 3))
        ttk.Button(frame, text="Exportar CSV", command=lambda: self.export_backup_csv(data)).pack(anchor="e")

    def export_backup_csv(self, report: dict):
        output = filedialog.asksaveasfilename(title="Exportar auditoria do backup", defaultextension=".csv",
                                             filetypes=[("Planilha CSV", "*.csv")], initialfile="auditoria_backup.csv")
        if not output:
            return
        try:
            with Path(output).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["status", "origem", "destino", "bytes", "sha256", "erro", "motivo"],
                                        delimiter=";", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(report["arquivos"])
            messagebox.showinfo(APP, f"Auditoria exportada para: {output}")
        except OSError as error:
            messagebox.showerror(APP, str(error))

    def setup_checklist(self, tab):
        ttk.Label(tab, text="Checklist pré-formatação", style="Title.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Esta conferência é manual. Marcar um item não executa nenhuma ação no Windows.", style="Info.TLabel").pack(anchor="w", pady=(5, 16))
        items = [
            "Organizei Downloads e conferi arquivos importantes.",
            "Salvei capturas de tela, Documentos, Desktop e outras pastas necessárias.",
            "Salvei meus projetos/códigos e configurações importantes.",
            "Revisei favoritos e sincronização de Chrome, Edge ou Firefox.",
            "Exportei a lista de programas para reinstalar.",
            "Exportei minhas extensões e configurações selecionadas do VS Code.",
            "Conferi licenças, contas de acesso e chave de recuperação do BitLocker (em local seguro).",
            "Verifiquei se todos os arquivos do OneDrive estavam disponíveis para backup.",
            "Conferi os relatórios e abri arquivos copiados no destino.",
            "Confirmei que o destino está em unidade que NÃO será formatada.",
            "Tenho a mídia de instalação do Windows e drivers necessários.",
        ]
        self.checklist_vars = []
        for line in items:
            var = BooleanVar(value=False)
            self.checklist_vars.append(var)
            ttk.Checkbutton(tab, text=line, variable=var).pack(anchor="w", pady=6)
        ttk.Label(tab, text="Atenção: a lista não guarda suas marcações após fechar o aplicativo.", style="Info.TLabel").pack(anchor="w", pady=(16, 0))

    def on_close(self):
        if self.backup_running:
            messagebox.showwarning(APP, "Há um backup em execução. Use Cancelar e aguarde o encerramento antes de fechar.")
            return
        self.destroy()


if __name__ == "__main__":
    app = PreparadorPC()
    app.mainloop()