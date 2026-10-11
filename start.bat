@echo off
chcp 65001 >nul
title 中国房地产产业链波动分析金融智能体 - 启动器
cd /d "%~dp0"

echo ============================================
echo   中国房地产产业链波动分析金融智能体 一键启动
echo ============================================
echo.

:: ---- 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause & exit /b 1
)

:: ---- 检查 Node ----
where npm >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 npm，请先安装 Node.js 18+
    pause & exit /b 1
)

:: ---- 后端依赖检查（app.db 存在说明跑过）----
if not exist "backend\app\data\io_table.json" (
    echo [错误] backend 目录不完整
    pause & exit /b 1
)
python -c "import fastapi" >nul 2>nul
if errorlevel 1 (
    echo [提示] 首次运行，安装后端依赖中...
    pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --quiet
)

:: ---- 前端依赖检查 ----
if not exist "frontend\node_modules" (
    echo [提示] 首次运行，安装前端依赖中（约1-2分钟）...
    cd frontend && call npm install --no-fund --no-audit && cd ..
)

echo.
echo [1/2] 启动后端  http://localhost:8000  （文档: /docs）
start "RE-Risk-Backend" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

timeout /t 5 /nobreak >nul

echo [2/2] 启动前端  http://localhost:5173
start "RE-Risk-Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

timeout /t 8 /nobreak >nul
start http://localhost:5173

echo.
echo ============================================
echo   启动完成！浏览器已打开 http://localhost:5173
echo   （首次加载知识库约需 30-90 秒）
echo   关闭本窗口不影响服务；停止服务请运行 stop.bat
echo ============================================
pause
