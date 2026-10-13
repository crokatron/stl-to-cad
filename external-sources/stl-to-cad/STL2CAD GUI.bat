@echo off
REM Launch the STL -> CAD Converter GUI.
setlocal
set HERE=%~dp0
call "%USERPROFILE%\miniforge3\condabin\conda.bat" activate stl2cad || (
  echo Could not activate the 'stl2cad' conda environment.
  echo Run:  conda env create -f "%HERE%environment.yml"
  pause
  exit /b 1
)
set PYTHONPATH=%HERE%
cd /d "%HERE%"
python -m app.main %*
