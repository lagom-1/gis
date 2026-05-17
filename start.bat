@echo off
echo ========================================
echo   OpenGIS - 启动开发环境
echo ========================================

echo.
echo [1/2] 启动后端 API (端口 8000)...
start "OpenGIS-Backend" cmd /k "conda activate gdal_env && uvicorn api.app:app --reload --host 0.0.0.0 --port 8000"

echo [2/2] 启动前端 (端口 3000)...
start "OpenGIS-Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo ========================================
echo   启动完成！
echo   后端: http://localhost:8000/docs
echo   前端: http://localhost:3000
echo ========================================
echo.
echo 关闭此窗口不影响后端和前端运行。
pause
