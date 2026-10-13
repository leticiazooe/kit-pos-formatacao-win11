import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from organizador_pc.config import Settings, initialize_settings, load_settings
from organizador_pc.engine import FileTracker, is_cloud_only, scan
from organizador_pc.runner import run_manual, run_cycle
from organizador_pc.reports import daily_summary, exclusive_lock


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        downloads = root / "Downloads"
        downloads.mkdir()
        self.settings = Settings(downloads=downloads, storage=root / "storage", min_age_seconds=0, interval_seconds=10)

    def write(self, name, content="content"):
        path = self.settings.downloads / name
        path.write_text(content, encoding="utf-8")
        return path


class EngineTests(BaseCase):
    def test_requires_two_scans_before_automatic_move(self):
        src = self.write("documento.pdf")
        tracker = FileTracker()
        first = scan(self.settings, tracker)
        self.assertTrue(src.exists())
        self.assertEqual(first["resumo"]["arquivos_aguardando"], 1)
        second = scan(self.settings, tracker)
        self.assertFalse(src.exists())
        self.assertEqual(second["resumo"]["arquivos_movidos"], 1)
        self.assertEqual((self.settings.downloads / "PDF" / "documento.pdf").read_text(), "content")
        self.assertEqual(second["resumo"]["pastas_criadas"], 1)

    def test_classifies_extensions_and_preserves_folders(self):
        self.write("index.html")
        self.write("arquivo.zip")
        self.write("desconhecido.xyz")
        (self.settings.downloads / "Projetos").mkdir()
        (self.settings.downloads / "Projetos" / "notas.pdf").write_text("stay")
        tracker = FileTracker()
        scan(self.settings, tracker)
        report = scan(self.settings, tracker)
        self.assertTrue((self.settings.downloads / "HTML" / "index.html").exists())
        self.assertTrue((self.settings.downloads / "PASTAS ZIPADAS" / "arquivo.zip").exists())
        self.assertTrue((self.settings.downloads / "OUTROS" / "desconhecido.xyz").exists())
        self.assertTrue((self.settings.downloads / "Projetos" / "notas.pdf").exists())
        self.assertEqual(report["resumo"]["arquivos_movidos"], 3)

    def test_ignores_temporary_and_windows_metadata(self):
        self.write("tarefa.crdownload")
        self.write("parte.part")
        self.write("desktop.ini")
        tracker = FileTracker()
        scan(self.settings, tracker)
        report = scan(self.settings, tracker)
        self.assertEqual(report["resumo"]["arquivos_movidos"], 0)
        self.assertEqual(report["resumo"]["arquivos_ignorados"], 3)

    def test_collision_uses_suffix_without_overwrite(self):
        folder = self.settings.downloads / "PDF"
        folder.mkdir()
        (folder / "livro.pdf").write_text("original")
        self.write("livro.pdf", "new")
        tracker = FileTracker()
        scan(self.settings, tracker)
        report = scan(self.settings, tracker)
        self.assertEqual((folder / "livro.pdf").read_text(), "original")
        self.assertEqual((folder / "livro (1).pdf").read_text(), "new")
        self.assertEqual(report["resumo"]["pastas_criadas"], 0)

    def test_preview_never_moves(self):
        src = self.write("arquivo.sql")
        report = scan(self.settings, FileTracker(), preview=True)
        self.assertTrue(src.exists())
        self.assertEqual(report["resumo"]["previstos"], 1)
        self.assertFalse((self.settings.downloads / "CODIGO").exists())

    def test_age_guard(self):
        src = self.write("documento.docx")
        settings = replace(self.settings, min_age_seconds=60)
        tracker = FileTracker()
        scan(settings, tracker, now=src.stat().st_mtime + 5)
        report = scan(settings, tracker, now=src.stat().st_mtime + 8)
        self.assertTrue(src.exists())
        self.assertEqual(report["resumo"]["arquivos_aguardando"], 1)

    def test_change_between_scans_requires_new_stability(self):
        src = self.write("video.mp4")
        tracker = FileTracker()
        scan(self.settings, tracker)
        src.write_text("a much longer content for another signature")
        report = scan(self.settings, tracker)
        self.assertTrue(src.exists())
        self.assertEqual(report["resumo"]["arquivos_aguardando"], 1)
        scan(self.settings, tracker)
        self.assertFalse(src.exists())

    def test_cloud_only_windows_file_attributes_are_ignored(self):
        self.assertTrue(is_cloud_only(SimpleNamespace(st_file_attributes=0x00400000)))
        self.assertTrue(is_cloud_only(SimpleNamespace(st_file_attributes=0x1000)))
        self.assertFalse(is_cloud_only(SimpleNamespace(st_file_attributes=0)))

    def test_symlink_category_is_blocked(self):
        self.write("arquivo.pdf")
        outside = Path(self.temp.name) / "external"
        outside.mkdir()
        try:
            (self.settings.downloads / "PDF").symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("Sem permissão para symlink")
        tracker = FileTracker()
        scan(self.settings, tracker)
        report = scan(self.settings, tracker)
        self.assertEqual(report["resumo"]["erros"], 1)
        self.assertFalse((outside / "arquivo.pdf").exists())


class ReportsTests(BaseCase):
    def test_manual_saves_json_csv_txt(self):
        self.write("manual.pdf")
        report, saved = run_manual(self.settings)
        self.assertEqual(report["resumo"]["arquivos_movidos"], 1)
        self.assertTrue(saved.exists())
        self.assertTrue(saved.with_suffix(".csv").exists())
        self.assertTrue(saved.with_suffix(".txt").exists())
        self.assertIn("movido", saved.with_suffix(".csv").read_text(encoding="utf-8-sig"))
        self.assertEqual(json.loads(self.settings.status_path.read_text())["estado"], "ativo")

    def test_empty_periodic_scan_does_not_create_report(self):
        tracker = FileTracker()
        _, saved = run_cycle(self.settings, tracker)
        self.assertIsNone(saved)
        self.assertFalse(self.settings.reports_dir.exists())
        self.assertTrue(self.settings.status_path.exists())

    def test_daily_aggregate(self):
        self.write("a.pdf")
        run_manual(self.settings)
        self.write("b.jpg")
        run_manual(self.settings)
        report = daily_summary(self.settings.reports_dir, __import__("datetime").date.today())
        self.assertEqual(report["execucoes_registradas"], 2)
        self.assertEqual(report["resumo"]["arquivos_movidos"], 2)
        self.assertEqual(report["por_categoria"], {"IMAGENS": 1, "PDF": 1})

    def test_lock_rejects_simultaneous_processing(self):
        lock = self.settings.storage / "scan.lock"
        with exclusive_lock(lock):
            with self.assertRaises(RuntimeError):
                with exclusive_lock(lock):
                    pass

    def test_config_saved_without_overwriting(self):
        path = self.settings.storage / "config.json"
        initialize_settings(self.settings.downloads, path=path, storage=self.settings.storage)
        settings = load_settings(path)
        self.assertEqual(settings.downloads, self.settings.downloads)
        with self.assertRaises(FileExistsError):
            initialize_settings(self.settings.downloads, path=path, storage=self.settings.storage)

    def test_config_rejects_reports_inside_downloads(self):
        wrong = replace(self.settings, storage=self.settings.downloads / "_relatorios")
        with self.assertRaises(ValueError):
            wrong.validate()


if __name__ == "__main__":
    unittest.main()
