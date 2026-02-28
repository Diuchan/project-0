"""PyQt6 GUI wrapper for the AIM web tool.

Usage: `python -m project0.gui` or run this module directly.
"""
from __future__ import annotations
import sys
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
    QPushButton,
    QLineEdit,
    QCheckBox,
    QFileDialog,
    QMessageBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
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
        fl.addRow(QLabel("Relative Humidity (0.1 - 1.0)"), self.rh_spin)

        sl.addLayout(fl)

        # Ionic composition section (moles): only four ionic species
        sl.addWidget(QLabel("Ionic composition (moles)"))
        ionic_layout = QFormLayout()
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
        # exclude Ice from main solids list; handled by separate checkbox
        self.solid_names = [
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

        # separate control for equilibrating over ice
        self.equilibrate_ice_cb = QCheckBox("Equilibrate over ice?")
        sl.addWidget(self.equilibrate_ice_cb)

        for name in self.solid_names:
            cb = QCheckBox(name)
            self.solid_checkboxes.append(cb)
            sl.addWidget(cb)

        # Check / Uncheck controls
        btns = QHBoxLayout()
        self.check_all_solids_btn = QPushButton("Check All Solids")
        self.check_all_solids_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self.solid_checkboxes])
        btns.addWidget(self.check_all_solids_btn)
        self.uncheck_all_solids_btn = QPushButton("Uncheck All Solids")
        self.uncheck_all_solids_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in self.solid_checkboxes])
        btns.addWidget(self.uncheck_all_solids_btn)
        sl.addLayout(btns)

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

    def parse_species_table(self) -> (Dict[str, float], set):
        # Read ionic inputs and solid checkbox states
        species = {}
        solids = set()

        def to_float(text: str) -> float:
            try:
                return float(text)
            except Exception:
                return 0.0

        species["H+"] = to_float(self.hydrogen_input.text())
        species["NH4+"] = to_float(self.ammonium_input.text())
        species["SO42-"] = to_float(self.sulphate_input.text())
        species["NO3-"] = to_float(self.nitrate_input.text())

        for cb, name in zip(self.solid_checkboxes, self.solid_names):
            if cb.isChecked():
                solids.add(name)
        # include ice selection if checked
        if self.equilibrate_ice_cb.isChecked():
            solids.add("Ice")

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
