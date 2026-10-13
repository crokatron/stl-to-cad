"""STL -> CAD Converter — desktop GUI.

Run:  python -m app.main      (inside the `stl2cad` conda env)
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import numpy as np

from OCC.Display.backend import load_backend

load_backend("pyside6")

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
from OCC.Display.qtDisplay import qtViewer3d  # noqa: E402

from stl2cad.config import PipelineConfig  # noqa: E402
from stl2cad import pipeline as pl  # noqa: E402
from stl2cad.export import export_all  # noqa: E402
from stl2cad.viewer_util import mesh_ais  # noqa: E402
from stl2cad.validate import tessellate  # noqa: E402
import trimesh  # noqa: E402


# --------------------------------------------------------------------------- #
class Worker(QtCore.QThread):
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    log = QtCore.Signal(str)

    def __init__(self, path: str, cfg: PipelineConfig):
        super().__init__()
        self.path, self.cfg = path, cfg

    def run(self):
        try:
            self.log.emit(f"Processing {Path(self.path).name} …")
            res = pl.run(self.path, self.cfg, do_export=False)
            self.done.emit(res)
        except Exception:
            self.failed.emit(traceback.format_exc())


# --------------------------------------------------------------------------- #
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("STL → CAD Converter")
        self.resize(1360, 880)
        self.setAcceptDrops(True)

        self.cfg = PipelineConfig()
        self.result: pl.PipelineResult | None = None
        self._ais_solid = None
        self._ais_mesh = None
        self._worker: Worker | None = None

        self._build_ui()

    # ---- UI ----------------------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        # left: files + params
        left = QtWidgets.QVBoxLayout()
        root.addLayout(left, 0)

        self.file_list = QtWidgets.QListWidget()
        self.file_list.setMaximumWidth(320)
        self.file_list.itemDoubleClicked.connect(lambda it: self._run(it.text()))
        left.addWidget(QtWidgets.QLabel("Files (double-click to run):"))
        left.addWidget(self.file_list, 1)

        row = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("Add STL…")
        b_add.clicked.connect(self._add_files)
        b_clear = QtWidgets.QPushButton("Clear")
        b_clear.clicked.connect(self.file_list.clear)
        row.addWidget(b_add)
        row.addWidget(b_clear)
        left.addLayout(row)

        params = QtWidgets.QFormLayout()
        left.addWidget(QtWidgets.QLabel("Parameters:"))
        self.sp_tol = QtWidgets.QDoubleSpinBox()
        self.sp_tol.setRange(0.02, 5.0)
        self.sp_tol.setSingleStep(0.05)
        self.sp_tol.setValue(self.cfg.fit.analytic_tol)
        self.sp_dih = QtWidgets.QDoubleSpinBox()
        self.sp_dih.setRange(3, 60)
        self.sp_dih.setValue(self.cfg.segment.dihedral_deg)
        self.sp_faces = QtWidgets.QSpinBox()
        self.sp_faces.setRange(5_000, 400_000)
        self.sp_faces.setSingleStep(5_000)
        self.sp_faces.setValue(self.cfg.heal.target_faces or 60_000)
        self.sp_unify = QtWidgets.QDoubleSpinBox()
        self.sp_unify.setRange(0.0, 10.0)
        self.sp_unify.setSingleStep(0.5)
        self.sp_unify.setValue(np.degrees(self.cfg.build.unify_angular_tol))
        self.cb_method = QtWidgets.QComboBox()
        self.cb_method.addItems(["faceted", "arcwise", "hybrid"])
        self.cb_refine = QtWidgets.QCheckBox("split/merge refinement")
        self.cb_refine.setChecked(True)
        params.addRow("Analytic tol (mm)", self.sp_tol)
        params.addRow("Dihedral (deg)", self.sp_dih)
        params.addRow("Decimate to (tris)", self.sp_faces)
        params.addRow("Planar merge (deg)", self.sp_unify)
        params.addRow("Method", self.cb_method)
        params.addRow("", self.cb_refine)
        left.addLayout(params)

        self.b_run = QtWidgets.QPushButton("▶  Run")
        self.b_run.clicked.connect(lambda: self._run(self._current_path()))
        left.addWidget(self.b_run)

        self.b_export = QtWidgets.QPushButton("Export STEP…")
        self.b_export.clicked.connect(self._export)
        self.b_export.setEnabled(False)
        left.addWidget(self.b_export)

        # view toggles
        vt = QtWidgets.QHBoxLayout()
        self.cb_show_mesh = QtWidgets.QCheckBox("input mesh")
        self.cb_show_solid = QtWidgets.QCheckBox("solid")
        self.cb_show_solid.setChecked(True)
        self.cb_heat = QtWidgets.QCheckBox("deviation")
        for c in (self.cb_show_solid, self.cb_show_mesh, self.cb_heat):
            c.stateChanged.connect(self._refresh_view)
            vt.addWidget(c)
        left.addLayout(vt)

        # centre: viewer
        self.viewer = qtViewer3d(self)
        root.addWidget(self.viewer, 1)
        self.viewer.InitDriver()
        self.display = self.viewer._display
        self.display.set_bg_gradient_color([32, 34, 38], [12, 12, 14])

        # right: report
        self.report = QtWidgets.QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumWidth(340)
        self.report.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        root.addWidget(self.report, 0)

        self.status = self.statusBar()

    # ---- drag & drop -----------------------------------------------------
    def dragEnterEvent(self, e: QtGui.QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QtGui.QDropEvent):
        for url in e.mimeData().urls():
            p = url.toLocalFile()
            if p.lower().endswith(".stl"):
                self._add_path(p)

    # ---- helpers -------------------------------------------------------
    def _add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add STL files", "", "STL (*.stl)")
        for p in paths:
            self._add_path(p)

    def _add_path(self, p: str):
        if not any(self.file_list.item(i).text() == p for i in range(self.file_list.count())):
            self.file_list.addItem(p)
        self.file_list.setCurrentRow(self.file_list.count() - 1)

    def _current_path(self) -> str | None:
        it = self.file_list.currentItem()
        return it.text() if it else None

    def _collect_cfg(self) -> PipelineConfig:
        c = PipelineConfig()
        c.fit.analytic_tol = self.sp_tol.value()
        c.segment.dihedral_deg = self.sp_dih.value()
        c.segment.refine = self.cb_refine.isChecked()
        c.heal.target_faces = self.sp_faces.value()
        c.build.unify_angular_tol = np.radians(self.sp_unify.value())
        c.build.method = self.cb_method.currentText()
        return c

    def _export(self):
        if self.result is None or self.result.shape is None:
            return
        src = Path(self.result.src)
        target, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export STEP", str(src.with_suffix(".stp")),
            "STEP (*.stp *.step);;BREP (*.brep);;IGES (*.igs)")
        if not target:
            return
        try:
            written = export_all(self.result.shape, Path(target).with_suffix(""),
                                 self._collect_cfg().export)
            self.status.showMessage("Wrote " + ", ".join(str(v) for v in written.values()))
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Export failed", str(exc))

    # ---- run -----------------------------------------------------------
    def _run(self, path: str | None):
        if not path:
            self.status.showMessage("Add and select an STL first.")
            return
        if self._worker and self._worker.isRunning():
            return
        self.b_run.setEnabled(False)
        self.b_export.setEnabled(False)
        self.report.setPlainText("Working …")
        self._worker = Worker(path, self._collect_cfg())
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.log.connect(self.status.showMessage)
        self._worker.start()

    def _on_failed(self, tb: str):
        self.b_run.setEnabled(True)
        self.report.setPlainText("FAILED\n\n" + tb)
        self.status.showMessage("Failed.")

    def _on_done(self, res: pl.PipelineResult):
        self.result = res
        self.b_run.setEnabled(True)
        self.b_export.setEnabled(res.shape is not None)
        v = res.validation
        txt = [
            res.summary(),
            "",
            "── validation ──",
            f"valid B-rep : {v.valid}",
            f"solids      : {v.n_solids}",
            f"volume      : {v.volume_solid:,.1f} mm³",
            f"vs mesh     : {v.volume_mesh:,.1f} mm³  ({v.volume_rel_err*100:.2f}%)",
            f"deviation   : max {v.dev_max:.3f} / rms {v.dev_rms:.3f} / p95 {v.dev_p95:.3f} mm",
            f"result      : {'PASS' if v.passed else 'FAIL'}",
            "",
            "── timings ──",
        ]
        txt += [f"{k:9s}: {val:.1f}s" for k, val in res.timings.items()]
        txt += ["", "── notes ──", *[str(n) for n in res.build.notes]]
        self.report.setPlainText("\n".join(txt))
        self._prepare_ais()
        self._refresh_view(fit=True)

    # ---- view --------------------------------------------------------
    def _prepare_ais(self):
        self._ais_solid = None
        self._ais_mesh = None
        res = self.result
        if res is None:
            return
        try:
            hm: trimesh.Trimesh = res.healed_mesh
            scal = None
            if res.shape is not None:
                pts = tessellate(res.shape)
                if len(pts):
                    _, d, _ = trimesh.proximity.closest_point(
                        trimesh.Trimesh(hm.vertices, hm.faces, process=False), hm.vertices)
                    # per-vertex distance from mesh vertex to reconstructed surface
                    tree = trimesh.proximity.ProximityQuery(
                        trimesh.Trimesh(pts, process=False)) if len(pts) > 3 else None
            # simpler: distance from each healed-mesh vertex to the solid tessellation
            if res.shape is not None:
                sp = tessellate(res.shape)
                if len(sp) > 3:
                    from scipy.spatial import cKDTree
                    scal = cKDTree(sp).query(hm.vertices)[0]
            self._ais_mesh = mesh_ais(hm.vertices, hm.faces, scalar=scal,
                                      vmax=max(self.cfg.validate.pass_max_dev, 1e-6))
            self._mesh_scalar = scal
        except Exception:
            traceback.print_exc()

    def _refresh_view(self, *_, fit: bool = False):
        self.display.EraseAll()
        res = self.result
        if res is None:
            return
        from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB

        if self.cb_show_solid.isChecked() and res.shape is not None:
            self.display.DisplayShape(res.shape, update=False,
                                      color=Quantity_Color(0.65, 0.68, 0.72, Quantity_TOC_RGB),
                                      transparency=0.0 if not self.cb_show_mesh.isChecked() else 0.4)
        if (self.cb_show_mesh.isChecked() or self.cb_heat.isChecked()) and self._ais_mesh is not None:
            ctx = self.display.Context
            ais = self._ais_mesh
            try:
                ctx.Display(ais, False)
                ctx.SetDisplayMode(ais, 1, False)
            except Exception:
                pass
        self.display.Context.UpdateCurrentViewer()
        if fit:
            self.display.FitAll()


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    for a in sys.argv[1:]:
        if a.lower().endswith(".stl") and Path(a).exists():
            w._add_path(a)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
