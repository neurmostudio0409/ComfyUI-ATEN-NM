@echo off
REM 安裝 ComfyUI-ATEN-NM 依賴（使用 ComfyUI portable 附帶的 python_embeded）
set PYTHON_EXE=%~dp0..\..\..\python_embeded\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERROR] 找不到 python_embeded，改用系統 python
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" -m pip install -r "%~dp0requirements.txt"

echo.
echo 安裝完成！請記得：
echo 1. 複製 .env.example 為 .env
echo 2. 在 .env 中設定 ATEN_API_TOKEN
echo 3. 重啟 ComfyUI
pause
