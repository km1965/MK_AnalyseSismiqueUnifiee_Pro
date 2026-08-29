@echo off
REM ============================================================================
REM  Build de l'executable autonome (PyInstaller) - MK_AnalyseSismiqueUnifiee_Pro
REM  Utilise le .spec versionne (nom ..._V01). Pour une nouvelle version :
REM  dupliquer le .spec et changer le champ name= de l'EXE().
REM ============================================================================
setlocal
cd /d "%~dp0"

if not exist env\Scripts\pyinstaller.exe (
    echo [ERREUR] Environnement virtuel introuvable.
    echo   Créez-le puis installez les dependances :
    echo     python -m venv env
    echo     env\Scripts\pip install -r requirements.txt
    exit /b 1
)

env\Scripts\pyinstaller.exe MK_AnalyseSismiqueUnifiee_Pro_V01.spec --noconfirm
if errorlevel 1 (
    echo [ERREUR] La compilation a echoue. Voir la sortie ci-dessus.
    exit /b 1
)
echo.
echo [OK] Executable genere : dist\MK_AnalyseSismiqueUnifiee_Pro_V01.exe
endlocal
