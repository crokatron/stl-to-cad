# Building a standalone `STL2CAD.exe`

PyInstaller bundles the conda env into a one-folder app that runs without Python.

```bash
conda activate stl2cad
pip install pyinstaller
python -m PyInstaller packaging/stl2cad.spec --noconfirm
# -> dist/STL2CAD/STL2CAD.exe
```

Notes
* Build **inside the `stl2cad` conda env** so PyInstaller sees pythonocc / PySide6.
* pythonocc ships large `.pyd` + OpenCASCADE DLLs; the collected folder is ~500 MB.
* First launch of the packaged app can take a few seconds (DLL load).
* If the OCC viewer window is black, copy the `OCC` package's `Display` shaders —
  the spec already forces `--collect-all OCC`.
