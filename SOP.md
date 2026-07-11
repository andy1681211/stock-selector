# 选股 Web 发布 SOP

## 项目位置
- 前端源码: `C:\Users\Administrator\.openclaw\workspace\web_stock_picker\`
- 部署目录: `C:\Users\Administrator\.openclaw\workspace\web_stock_picker\docs\`
- GitHub 仓库: `andy1681211/stock-selector` (main 分支)
- 线上地址: `https://andy1681211.github.io/stock-selector/`

## 每日发布步骤（选股后执行）

### 1. 同步选股数据到 web 目录
```bash
python web_stock_picker\sync_data.py
```
作用：把 `data/daily_pick_YYYY-MM-DD.json` 复制到 `web_stock_picker/docs/data/latest_pick.json`

### 2. 提交并推送
```bash
cd C:\Users\Administrator\.openclaw\workspace\web_stock_picker
git add -A
git commit -m "更新选股数据 YYYY-MM-DD"
git push origin main
```

### 3. GitHub Pages 自动更新
推送后 1-2 分钟，GitHub Pages 自动构建完成。
刷新 `https://andy1681211.github.io/stock-selector/` 即可看到最新数据。

## 注意事项
- sync_data.py 只复制 JSON 数据，不包含通达信 .day 文件（浏览器无法读取）
- 个股技术分析功能：需要在本地运行 tdx_analyzer 后将结果放到 `docs/data/tdx_analysis_*.json`
- 板块数据：需要将 sectors.txt 放到 `docs/data/` 目录下
- 更新数据后 git commit message 带上日期方便追溯
