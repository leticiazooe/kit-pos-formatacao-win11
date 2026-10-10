"""Testes básicos sem alterações no computador real."""
import json
import csv
from unittest.mock import patch
import queue
import tempfile
import threading
import unittest
from pathlib import Path

from preparador_pc import (PreparadorPC, classify, make_move_plan, sha256, unique_destination,
                          run_downloads_organization, read_organization_report, export_organization_report, MovePlan,
                          save_installed_programs, export_installed_programs, export_vscode_environment,
                          vscode_extensions)


class PreparadorPCTests(unittest.TestCase):
    def test_organizer(self):
        with tempfile.TemporaryDirectory() as temp:
            downloads = Path(temp)
            (downloads / "contrato.pdf").write_text("original", encoding="utf-8")
            (downloads / "pagina.HTML").write_text("html", encoding="utf-8")
            (downloads / "arquivo.zip").write_text("zip", encoding="utf-8")
            (downloads / "baixe.crdownload").write_text("parcial", encoding="utf-8")
            (downloads / "uma_pasta").mkdir()
            (downloads / "PDF").mkdir()
            (downloads / "PDF" / "contrato.pdf").write_text("nao sobrescrever", encoding="utf-8")
            planned = make_move_plan(downloads)
            self.assertEqual(len(planned), 3)
            values = {plan.source.name: (plan.destination.parent.name, plan.destination.name) for plan in planned}
            self.assertEqual(values["contrato.pdf"], ("PDF", "contrato (1).pdf"))
            self.assertEqual(values["pagina.HTML"][0], "HTML")
            self.assertEqual(values["arquivo.zip"][0], "PASTAS ZIPADAS")
            self.assertEqual(classify(downloads / "novo.unknown"), "OUTROS")

    def test_organization_history_complete_and_exportable(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "Downloads"
            folder.mkdir()
            (folder / "contrato.pdf").write_text("contrato", encoding="utf-8")
            (folder / "pagina.HTML").write_text("pagina", encoding="utf-8")
            (folder / "comprimido.zip").write_text("arquivo", encoding="utf-8")
            (folder / "interrompido.crdownload").write_text("em progresso", encoding="utf-8")
            (folder / "uma_pasta").mkdir()
            (folder / "PDF").mkdir()
            (folder / "PDF" / "contrato.pdf").write_text("antigo", encoding="utf-8")
            plan = make_move_plan(folder)
            report, path = run_downloads_organization(folder, plan)
            self.assertIsNotNone(path)
            self.assertTrue(path.is_file())
            summary = report["resumo"]
            self.assertEqual(summary["arquivos_movidos"], 3)
            self.assertEqual(summary["pastas_criadas"], 2)
            self.assertEqual(summary["pastas_reutilizadas"], 1)
            self.assertEqual(summary["arquivos_ignorados"], 1)
            self.assertEqual(summary["pastas_preservadas"], 2)
            self.assertEqual(summary["erros"], 0)
            self.assertEqual(summary["por_categoria"], {"HTML": 1, "PASTAS ZIPADAS": 1, "PDF": 1})
            self.assertEqual((folder / "PDF" / "contrato.pdf").read_text(), "antigo")
            self.assertEqual((folder / "PDF" / "contrato (1).pdf").read_text(), "contrato")
            self.assertEqual((folder / "interrompido.crdownload").read_text(), "em progresso")
            self.assertTrue(any(e["tipo"] == "pasta_criada" and e["destino"].endswith("HTML") for e in report["eventos"]))
            self.assertTrue(any(e["tipo"] == "ignorado" and "incompleto" in e["detalhes"] for e in report["eventos"]))
            self.assertEqual(read_organization_report(path), report)
            for extension in ["txt", "csv", "json"]:
                output = folder / f"exportado.{extension}"
                export_organization_report(report, output, extension)
                self.assertTrue(output.is_file())
                self.assertGreater(output.stat().st_size, 100)
            self.assertIn("Origem", (folder / "exportado.txt").read_text(encoding="utf-8-sig"))
            self.assertIn(";", (folder / "exportado.csv").read_text(encoding="utf-8-sig"))
            self.assertEqual(read_organization_report(folder / "exportado.json"), report)

    def test_organization_failed_file_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            missing = folder / "ja_nao_existe.pdf"
            plan = [MovePlan(missing, folder / "PDF" / missing.name)]
            report, path = run_downloads_organization(folder, plan)
            self.assertIsNotNone(path)
            self.assertEqual(report["resumo"]["erros"], 1)
            self.assertEqual(report["resumo"]["arquivos_movidos"], 0)
            self.assertEqual(report["estado"], "concluido_com_erros")

    def test_organization_report_unavailable_keeps_results(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "a.pdf").write_text("original")
            (folder / "_RELATORIOS_PREPARADOR_PC").write_text("arquivo bloqueando pasta")
            report, path = run_downloads_organization(folder, make_move_plan(folder))
            self.assertIsNone(path)
            self.assertIn("aviso_salvamento", report)
            self.assertEqual(report["resumo"]["arquivos_movidos"], 1)

    def test_read_previous_report_format(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "organizacao_20260101_010101.json"
            path.write_text(json.dumps([{"status": "movido", "origem": "/tmp/a.pdf", "destino": "/tmp/PDF/a.pdf"},
                                        {"status": "erro", "origem": "/tmp/b.pdf", "mensagem": "Sem acesso"}]))
            report = read_organization_report(path)
            self.assertEqual(report["resumo"]["arquivos_movidos"], 1)
            self.assertEqual(report["resumo"]["erros"], 1)

    def test_hash_and_unique_names(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "backup.tar.gz").write_bytes(b"test")
            self.assertEqual(unique_destination(folder, "backup.tar.gz").name, "backup (1).tar.gz")
            self.assertEqual(sha256(folder / "backup.tar.gz"), "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08")

    def test_backup_copies_and_verifies(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            original = base / "origem"
            destination = base / "destino"
            (original / "subpasta").mkdir(parents=True)
            destination.mkdir()
            (original / "subpasta" / "foto.png").write_bytes(b"conteudo de teste")
            worker_app = PreparadorPC.__new__(PreparadorPC)
            worker_app.queue = queue.Queue()
            worker_app.cancel_event = threading.Event()
            worker_app.worker_backup(destination, [("Capturas de tela", original)])
            folder = next(destination.iterdir())
            report = json.loads((folder / "relatorio_backup.json").read_text(encoding="utf-8"))
            copy = folder / "Capturas de tela" / "subpasta" / "foto.png"
            self.assertEqual(copy.read_bytes(), b"conteudo de teste")
            self.assertEqual(report["estado"], "concluido")
            self.assertEqual(report["arquivos_verificados"], 1)
            self.assertEqual(sha256(copy), sha256(original / "subpasta" / "foto.png"))

    def test_organization_with_symlink_alias_has_no_false_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            actual = root / "Downloads"
            actual.mkdir()
            (actual / "arquivo.pdf").write_text("ok")
            alias = root / "Downloads_alias"
            try:
                alias.symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Links simbólicos indisponíveis")
            plans = make_move_plan(alias)
            report, _ = run_downloads_organization(alias, plans)
            self.assertEqual(report["resumo"]["arquivos_movidos"], 1)
            self.assertEqual(report["resumo"]["arquivos_ignorados"], 0)
            self.assertEqual(report["resumo"]["erros"], 0)

    def test_installed_programs_multiple_exports(self):
        apps = [{"nome": "Editor", "versao": "1.0", "fabricante": "Equipe"},
                {"nome": "Navegador", "versao": "2.0", "fabricante": "Fabricante"}]
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for ext in ("txt", "csv", "json"):
                target = folder / f"aplicativos.{ext}"
                save_installed_programs(target, apps)
                self.assertTrue(target.is_file())
            self.assertEqual(json.loads((folder / "aplicativos.json").read_text())["quantidade"], 2)
            with (folder / "aplicativos.csv").open(encoding="utf-8-sig", newline="") as stream:
                saved = list(csv.DictReader(stream, delimiter=";"))
            self.assertEqual(saved, apps)
            self.assertIn("Editor", (folder / "aplicativos.txt").read_text(encoding="utf-8-sig"))
            with self.assertRaises(ValueError):
                save_installed_programs(folder / "aplicativos.exe", apps)

    def test_vscode_export_selected_configs_and_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            user = base / "User"
            user.mkdir()
            (user / "settings.json").write_text('{"editor.fontSize": 16}', encoding="utf-8")
            (user / "keybindings.json").write_text('[]', encoding="utf-8")
            (user / "snippets").mkdir()
            (user / "snippets" / "python.json").write_text('{}', encoding="utf-8")
            extensions = base / "extensions"
            extension_dir = extensions / "publisher.extension-1.0.0"
            extension_dir.mkdir(parents=True)
            (extension_dir / "package.json").write_text(json.dumps({"publisher": "publisher", "name": "extension", "version": "1.0.0"}))
            output_root = base / "backup"
            output_root.mkdir()
            with patch("preparador_pc._extension_command", return_value=None):
                found, source, _ = vscode_extensions(extensions)
                self.assertEqual(found[0]["identificador"], "publisher.extension")
                self.assertEqual(source, "diretório local")
                report, export_folder = export_vscode_environment(output_root, user, {"keybindings.json", "snippets"}, extensions)
            self.assertEqual(report["extensoes"], 1)
            self.assertEqual(report["arquivos_salvos"], 2)
            self.assertTrue((export_folder / "configuracoes" / "snippets" / "python.json").is_file())
            self.assertFalse((export_folder / "configuracoes" / "settings.json").exists())
            self.assertIn("publisher.extension@1.0.0", (export_folder / "extensoes_vscode.txt").read_text())
            self.assertEqual(json.loads((export_folder / "relatorio_vscode.json").read_text())["arquivos_salvos"], 2)
            with self.assertRaises(ValueError):
                export_vscode_environment(user, user, set(), extensions)

    def test_vscode_reports_missing_selected_file(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            user = base / "User"
            user.mkdir()
            target = base / "dest"
            target.mkdir()
            with patch("preparador_pc._extension_command", return_value=None):
                report, _ = export_vscode_environment(target, user, {"settings.json"}, base / "extensiones")
            self.assertEqual(report["arquivos_ignorados"], 1)
            self.assertEqual(report["eventos"][1]["status"], "ignorado")

    def test_backup_report_logs_skipped_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "origem"
            output = base / "dest"
            source.mkdir()
            output.mkdir()
            (source / "arquivo.txt").write_text("ok")
            try:
                (source / "atalho.txt").symlink_to(source / "arquivo.txt")
            except (OSError, NotImplementedError):
                self.skipTest("Criar links simbólicos requer privilégio adicional neste Windows")
            worker = PreparadorPC.__new__(PreparadorPC)
            worker.queue = queue.Queue()
            worker.cancel_event = threading.Event()
            worker.worker_backup(output, [("Personalizada", source)])
            folder = next(output.iterdir())
            report = json.loads((folder / "relatorio_backup.json").read_text())
            self.assertEqual(report["arquivos_salvos"], 1)
            self.assertEqual(report["arquivos_ignorados"], 1)
            self.assertEqual({x["status"] for x in report["arquivos"]}, {"verificado", "ignorado"})
            with (folder / "relatorio_backup.csv").open(encoding="utf-8-sig", newline="") as stream:
                values = list(csv.DictReader(stream, delimiter=";"))
            self.assertEqual(len(values), 2)


if __name__ == "__main__":
    unittest.main()