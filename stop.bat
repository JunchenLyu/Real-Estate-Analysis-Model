@echo off
chcp 65001 >nul
title 中国房地产产业链波动分析金融智能体 - 停止服务
echo 正在停止前后端服务...
taskkill /FI "WINDOWTITLE eq RE-Risk-Backend*" /T /F >nul 2>nul
taskkill /FI "WINDOWTITLE eq RE-Risk-Frontend*" /T /F >nul 2>nul
echo 已停止（若残留可手动关闭相关命令行窗口）
pause
