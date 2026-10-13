"""Painel nativo Tkinter. Não é executado dentro do serviço Windows."""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from tkinter import Tk, filedialog, messagebox, ttk
import tkinter as tk

from .config import Settings
from .engine import FileTracker, scan
from .reports import daily_summary


class Dashboard(Tk):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.title("Organizador PC | Downloads monitorados")
        self.geometry("1170x740")
        self.minsize(890, 580)
        self.configure(bg="#F4F6FA")
        self.current = None
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#F4F6FA")
        style.configure("TLabel", background="#F4F6FA", foreground="#26344B", font=("Segoe UI", 12))
        style.configure("Title.TLabel", background="#F4F6FA", font=("Segoe UI", 20, "bold"), foreground="#101E34")
        style.configure("TButton", font=("Segoe UI", 12), padding=(12, 9))
        style.configure("Treeview", font=("Segoe UI", 12), rowheight=34)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        self.banner = tk.StringVar(value="Consultando atividade...")
        self.details = tk.StringVar(value="")
        self._build()
        self.refresh()

    def _build(self):
        main = ttk.Frame(self, padding=24)
        main.pack(fill="both", expand=True)
        ttk.Label(main, text="Organizador PC", style="Title.TLabel").pack(anchor="w")
        ttk.Label(main, text="Monitoramento contínuo de Downloads, com relatórios e histórico de movimentações.").pack(anchor="w", pady=(2, 16))
        ttk.Label(main, textvariable=self.banner, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(main, text=f"Pasta monitorada: {self.settings.downloads}", wraplength=1020).pack(anchor="w", pady=(4, 2))
        ttk.Label(main, textvariable=self.details, wraplength=1020).pack(anchor="w", pady=(0, 12))
        controls = ttk.Frame(main)
        controls.pack(fill="x", pady=(0, 14))
        for label, callback in (("Atualizar", self.refresh), ("Prévia sem mover", self.preview),
                                ("Abrir relatório", self.open_report), ("Exportar resumo diário", self.export_daily)):
            ttk.Button(controls, text=label, command=callback).pack(side="left", padx=(0, 10))
        body = ttk.PanedWindow(main, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=4)
        ttk.Label(left, text="Histórico de execuções", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        self.reports = tk.Listbox(left, font=("Segoe UI", 12), width=30, exportselection=False)
        self.reports.pack(fill="both", expand=True)
        self.reports.bind("<<ListboxSelect>>", self._selected_report)
        ttk.Label(right, text="Movimentações, pastas e ocorrências", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 6))
        columns = ("tipo", "nome", "categoria", "destino", "detalhes")
        table_wrap = ttk.Frame(right)
        table_wrap.pack(fill="both", expand=True)
        self.table = ttk.Treeview(table_wrap, columns=columns, show="headings", selectmode="browse")
        for col, width in (("tipo", 110), ("nome", 160), ("categoria", 120),
                           ("destino", 240), ("detalhes", 280)):
            self.table.heading(col, text=col.capitalize())
            self.table.column(col, width=width, minwidth=85, stretch=True)
        self.table.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(table_wrap, orient="vertical", command=self.table.yview)
        bar.pack(side="right", fill="y")
        self.table.configure(yscrollcommand=bar.set)
        ttk.Label(main, text="O serviço roda sem interface. Este painel apenas consulta relatórios e faz prévias; não altera arquivos.",
                  wraplength=1030).pack(anchor="w", pady=(14, 0))

    def refresh(self):
        try:
            status = json.loads(self.settings.status_path.read_text(encoding="utf-8-sig"))
            self.banner.set(f"Estado da última varredura: {status.get('estado', 'desconhecido').upper()}")
            last = status.get("ultima_verificacao", "não disponível")
            summary = status.get("ultimo_resumo", {})
            self.details.set(f"Última verificação: {last} | Movidos: {summary.get('arquivos_movidos', 0)} | "
                             f"Aguardando: {summary.get('arquivos_aguardando', 0)} | Erros: {summary.get('erros', 0)}"
                             + (f" | {status.get('erro')}" if status.get("erro") else ""))
        except (OSError, ValueError) as exc:
            self.banner.set("Nenhuma atividade registrada nesta instalação")
            self.details.set(f"O serviço pode não estar iniciado. {exc}")
        self.files = sorted(self.settings.reports_dir.glob("organizacao_*.json"), reverse=True)[:300]
        self.reports.delete(0, "end")
        for file in self.files:
            self.reports.insert("end", file.stem.replace("organizacao_", ""))

    def _show(self, report: dict):
        self.current = report
        for item in self.table.get_children():
            self.table.delete(item)
        for event in report.get("eventos", []):
            self.table.insert("", "end", values=tuple(event.get(c, "") for c in
                                                        ("tipo", "nome", "categoria", "destino", "detalhes")))
        summary = report.get("resumo", {})
        self.details.set(f"Relatório: {report.get('inicio', '')} | Movidos: {summary.get('arquivos_movidos', 0)} | "
                         f"Pastas criadas: {summary.get('pastas_criadas', 0)} | "
                         f"Ignorados: {summary.get('arquivos_ignorados', 0)} | "
                         f"Aguardando: {summary.get('arquivos_aguardando', 0)} | Erros: {summary.get('erros', 0)}")

    def _selected_report(self, _event=None):
        selected = self.reports.curselection()
        if not selected:
            return
        try:
            self._show(json.loads(self.files[selected[0]].read_text(encoding="utf-8-sig")))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Não foi possível abrir", str(exc), parent=self)

    def preview(self):
        try:
            self._show(scan(self.settings, FileTracker(), preview=True))
            self.banner.set("Prévia exibida: nenhum arquivo foi movido")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erro na prévia", str(exc), parent=self)

    def open_report(self):
        filename = filedialog.askopenfilename(parent=self, title="Abrir relatório JSON",
                                               initialdir=str(self.settings.reports_dir),
                                               filetypes=[("Relatórios JSON", "*.json")])
        if filename:
            try:
                self._show(json.loads(Path(filename).read_text(encoding="utf-8-sig")))
            except (OSError, ValueError) as exc:
                messagebox.showerror("Relatório inválido", str(exc), parent=self)

    def export_daily(self):
        filename = filedialog.asksaveasfilename(parent=self, title="Salvar resumo diário",
                                                initialfile=f"resumo_{date.today():%Y%m%d}.json",
                                                defaultextension=".json", filetypes=[("JSON", "*.json")])
        if filename:
            try:
                report = daily_summary(self.settings.reports_dir, date.today())
                Path(filename).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                messagebox.showinfo("Exportado", f"Resumo salvo em:\n{filename}", parent=self)
            except (OSError, ValueError) as exc:
                messagebox.showerror("Falha ao exportar", str(exc), parent=self)
