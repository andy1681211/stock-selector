@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
"C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe" "D:\股票分析\选股工具\run_selector.py" --mode limit-up >> "D:\股票分析\选股工具\output\limit_up_auto_run.log" 2>&1
