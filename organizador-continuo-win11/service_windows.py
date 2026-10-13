"""Serviço Windows via pywin32. Instalação exige terminal como administrador.

Comandos (opções ANTES do verbo):
python service_windows.py --startup delayed install
python service_windows.py start
python service_windows.py stop
python service_windows.py remove
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import servicemanager
import win32event
import win32service
import win32serviceutil

from organizador_pc.config import load_settings
from organizador_pc.engine import FileTracker
from organizador_pc.runner import run_cycle


class OrganizadorPCService(win32serviceutil.ServiceFramework):
    _svc_name_ = "OrganizadorPC"
    _svc_display_name_ = "Organizador PC | Downloads"
    _svc_description_ = "Organiza Downloads periodicamente, sem apagar arquivos, e registra relatórios detalhados."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = True
        self.tracker = FileTracker()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        settings = load_settings()  # Caminho fixado no momento da instalação, NÃO SYSTEM/Downloads.
        settings.storage.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("organizador_pc")
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(settings.storage / "service.log", maxBytes=2_000_000,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        servicemanager.LogInfoMsg("OrganizadorPC: iniciado")
        try:
            while self.running:
                try:
                    report, path = run_cycle(settings, self.tracker, stop=lambda: not self.running)
                    result = report["resumo"]
                    logger.info("varredura: %s | relatorio=%s", result, path or "nenhum")
                except Exception:
                    logger.exception("Erro na varredura; o serviço continuará ativo")
                if win32event.WaitForSingleObject(self.stop_event,
                                                   settings.interval_seconds * 1000) == win32event.WAIT_OBJECT_0:
                    break
        finally:
            logger.info("serviço encerrado")
            handler.close()
            logger.removeHandler(handler)
            servicemanager.LogInfoMsg("OrganizadorPC: parado")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(OrganizadorPCService)
