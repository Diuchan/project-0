"""PyQt6 GUI wrapper for the AIM web tool.

Usage: `python -m project0.gui` or run this module directly.
"""
from __future__ import annotations
import sys
import threading
from typing import Dict
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QDoubleSpinBox,
    QTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QFileDialog,
    QMessageBox,
    QProgressBar,
)

import pandas as pd

from .aim_client import run_and_parse


class AIMWorker(QThread):
    result_ready = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, temp: float, rh: float, species: Dict[str, float], solids: set | None = None):
        super().__init__()
        self.temp = temp
        self.rh = rh
        self.species = species
        self.solids = solids or set()

    def run(self) -> None:
        try:
            res = run_and_parse(self.temp, self.rh, self.species, solids=self.solids)
            self.result_ready.emit(res)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AIM GUI — Project 0")
        self.resize(900, 600)

        root = QWidget()
        self.setCentralWidget(root)

        main_layout = QHBoxLayout(root)

        # Sidebar
        sidebar = QWidget()
        sl = QVBoxLayout(sidebar)
        fl = QFormLayout()

        # Temperature
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(150.0, 2000.0)
        self.temp_spin.setValue(298.15)
        self.temp_spin.setSingleStep(1.0)
        fl.addRow(QLabel("Temperature (K)"), self.temp_spin)

        # Relative humidity (fraction)
        self.rh_spin = QDoubleSpinBox()
        self.rh_spin.setRange(0.1, 1.0)
        self.rh_spin.setSingleStep(0.01)
        self.rh_spin.setValue(0.5)
        fl.addRow(QLabel("Relative Humidity (0-1)"), self.rh_spin)

        sl.addLayout(fl)

        # Species input
        # Ionic composition section (moles): only four ionic species
        sl.addWidget(QLabel("Ionic composition (moles)"))
        ionic_layout = QFormLayout()
        # use QLineEdit so users can enter scientific notation
        from PyQt6.QtWidgets import QLineEdit

        self.hydrogen_input = QLineEdit("0.0")
        ionic_layout.addRow(QLabel("H+ (moles)"), self.hydrogen_input)
        self.ammonium_input = QLineEdit("0.0")
        ionic_layout.addRow(QLabel("NH4+ (moles)"), self.ammonium_input)
        self.sulphate_input = QLineEdit("0.0")
        ionic_layout.addRow(QLabel("SO42- (moles)"), self.sulphate_input)
        self.nitrate_input = QLineEdit("0.0")
        ionic_layout.addRow(QLabel("NO3- (moles)"), self.nitrate_input)
        sl.addLayout(ionic_layout)

        # Solids section: checkboxes for each solid listed on the site
        sl.addWidget(QLabel("Omit the following solids (check to include):"))
        self.solid_names = [
            "Ice",
            "H2SO4 · H2O",
            "H2SO4 · 2H2O",
            "H2SO4 · 3H2O",
            "H2SO4 · 4H2O",
            "H2SO4 · 6.5H2O",
            "HNO3 · H2O",
            "HNO3 · 2H2O",
            "HNO3 · 3H2O",
            "(NH4)2SO4",
            "(NH4)3H(SO4)2",
            "NH4HSO4",
            "NH4NO3",
            "2NH4NO3 · (NH4)2SO4",
            "3NH4NO3 · (NH4)2SO4",
            "NH4NO3 · NH4HSO4",
        ]
        self.solid_checkboxes = []
        for name in self.solid_names:
            cb = QPushButton(name)
            # use toggleable QPushButton to show checked state simply
            cb.setCheckable(True)
            self.solid_checkboxes.append(cb)
            sl.addWidget(cb)

        self.check_all_solids_btn = QPushButton("Check All Solids")
        self.check_all_solids_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self.solid_checkboxes])
        sl.addWidget(self.check_all_solids_btn)

        # Buttons + progress
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("Run Model")
        self.run_btn.clicked.connect(self.on_run)
        btn_layout.addWidget(self.run_btn)

        self.export_btn = QPushButton("Export to CSV")
        self.export_btn.clicked.connect(self.on_export)
        self.export_btn.setEnabled(False)
        btn_layout.addWidget(self.export_btn)

        sl.addLayout(btn_layout)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        sl.addWidget(self.progress)

        sl.addStretch()
        main_layout.addWidget(sidebar, 0)

        # Results table
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Parameter", "Value"])
        main_layout.addWidget(self.table, 1)

        self.current_results = None

    def add_species_row(self, name: str = "", conc: str = "", solid: bool = False) -> None:
        r = self.spec_table.rowCount()
        self.spec_table.insertRow(r)
        item_name = QTableWidgetItem(name)
        item_name.setFlags(item_name.flags() | Qt.ItemFlag.ItemIsEditable)
        self.spec_table.setItem(r, 0, item_name)

        item_conc = QTableWidgetItem(conc)
        item_conc.setFlags(item_conc.flags() | Qt.ItemFlag.ItemIsEditable)
        self.spec_table.setItem(r, 1, item_conc)

        item_solid = QTableWidgetItem()
        item_solid.setFlags(item_solid.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item_solid.setCheckState(Qt.CheckState.Checked if solid else Qt.CheckState.Unchecked)
        self.spec_table.setItem(r, 2, item_solid)

    def remove_selected_rows(self) -> None:
        selected = sorted({idx.row() for idx in self.spec_table.selectedIndexes()}, reverse=True)
        for r in selected:
            self.spec_table.removeRow(r)

    def check_all_solids(self) -> None:
        for r in range(self.spec_table.rowCount()):
            item = self.spec_table.item(r, 2)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def parse_species_table(self) -> (Dict[str, float], set):
        # Read ionic inputs and solid checkbox states
        species = {}
        solids = set()
        def to_float(text: str) -> float:
            try:
                return float(text)
            except Exception:
                return 0.0

        species['H+'] = to_float(self.hydrogen_input.text())
        species['NH4+'] = to_float(self.ammonium_input.text())
        species['SO42-'] = to_float(self.sulphate_input.text())
        species['NO3-'] = to_float(self.nitrate_input.text())

        for cb, name in zip(self.solid_checkboxes, self.solid_names):
            if cb.isChecked():
                solids.add(name)

        return species, solids

    def on_run(self) -> None:
        temp = float(self.temp_spin.value())
        rh = float(self.rh_spin.value())
        species, solids = self.parse_species_table()

        if rh < 0.1 or rh > 1:
            QMessageBox.warning(self, "Invalid input", "RH must be between 0.1 and 1.0.")
            return
        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # busy indicator

        self.worker = AIMWorker(temp, rh, species, solids)
        self.worker.result_ready.connect(self.on_result)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    def on_result(self, result: dict) -> None:
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        self.populate_table(result)
        self.current_results = result
        self.export_btn.setEnabled(True)

    def on_error(self, message: str) -> None:
        self.progress.setVisible(False)
        self.run_btn.setEnabled(True)
        QMessageBox.critical(self, "Request failed", f"Error: {message}")

    def populate_table(self, results: dict) -> None:
        # Flatten results into list of (k, v)
        rows = []
        for k, v in results.items():
            if k == "molarities" and isinstance(v, dict):
                rows.append(("-- Molarities --", ""))
                for sk, sv in v.items():
                    rows.append((sk, str(sv)))
            else:
                rows.append((k, str(v)))

        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(k))
            self.table.setItem(i, 1, QTableWidgetItem(v))

    def on_export(self) -> None:
        if not self.current_results:
            QMessageBox.information(self, "No results", "No results to export.")
            return

        # Flatten to rows
        rows = []
        for k, v in self.current_results.items():
            if k == "molarities" and isinstance(v, dict):
                for sk, sv in v.items():
                    rows.append({"parameter": sk, "value": sv})
            else:
                rows.append({"parameter": k, "value": v})

        df = pd.DataFrame(rows)

        desktop = Path.home() / "Desktop"
        default = desktop / "aim_results.csv"
        filename, _ = QFileDialog.getSaveFileName(self, "Save CSV", str(default), "CSV Files (*.csv)")
        if not filename:
            return
        try:
            df.to_csv(filename, index=False)
            QMessageBox.information(self, "Saved", f"Results saved to {filename}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
