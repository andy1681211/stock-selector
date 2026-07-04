# 海哥选股器 - Vercel 部署配置

## 快速部署

### 方法 1: 一键部署（推荐）

点击这个按钮一键部署：

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/YOUR_USERNAME/web_stock_picker)

### 方法 2: 命令行部署

```bash
# 安装 Vercel CLI
npm i -g vercel

# 登录 Vercel
vercel login

# 部署到预览环境
vercel --prod
```

## 环境变量

在 Vercel 后台配置以下环境变量：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `TDX_PATH` | 通达信数据路径（仅本地部署需要） | `/home/user/TDX` |
| `NEWS_API_KEY` | 新闻 API 密钥（可选） | `your_key_here` |

## 功能验证

部署后访问以下地址验证功能：

- **首页**: `https://your-app.vercel.app/`
- **选股 API**: `https://your-app.vercel.app/api/daily_picker.py`
- **股票分析**: `https://your-app.vercel.app/api/analyze.py`

## 自定义域名

在 Vercel 后台 → Settings → Domains 添加你的域名：

1. 添加域名（如 `xuanguru.com`）
2. 配置 DNS 解析（CNAME 或 A 记录）
3. 等待 SSL 证书自动签发

## 故障排除

### 404 错误
- 检查 `vercel.json` 配置是否正确
- 确认构建产物在 `dist/` 目录

### API 超时
- 增加 Vercel 函数超时时间（默认 10s）
- 考虑升级到 Vercel Pro 计划（30s 超时）

### 数据库连接失败
- 检查环境变量配置
- 确认数据库服务可用
