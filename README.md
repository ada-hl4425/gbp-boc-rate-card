# BOC GBP Rate Card - 中行英镑汇率卡片生成器

自动抓取中国银行英镑现汇卖出价，生成美观的汇率信息卡片。

## ✨ 特性

- 🔄 每2小时自动更新
- 📊 显示汇率变化趋势
- 🎨 精美的网页卡片设计
- 🔔 自动失败通知（GitHub Issues）
- 💾 数据历史记录
- 🛡️ 完善的错误处理

## 📁 项目结构

```
gbp-boc-rate-card/
├── docs/
│   ├── index.html          # 前端页面
│   └── data.json           # 汇率数据（自动生成）
├── scripts/
│   └── fetch_boc_gbp.py    # 抓取脚本
├── .github/workflows/
│   └── update.yml          # GitHub Actions 配置
└── README.md
```

## 🚀 快速开始

### 1. 创建仓库

```bash
# 在 GitHub 上创建新仓库 gbp-boc-rate-card
git clone https://github.com/YOUR_USERNAME/gbp-boc-rate-card.git
cd gbp-boc-rate-card

# 创建目录结构
mkdir -p docs scripts .github/workflows
```

### 2. 复制文件

将以下文件复制到对应目录：
- `fetch_boc_gbp.py` → `scripts/fetch_boc_gbp.py`
- `index.html` → `docs/index.html`
- `update.yml` → `.github/workflows/update.yml`

### 3. 提交到 GitHub

```bash
git add .
git commit -m "Initial commit"
git push origin main
```

### 4. 开通 GitHub Pages

1. 进入仓库 Settings → Pages
2. Source 选择 "Deploy from a branch"
3. Branch 选择 `main` + `/docs` 目录
4. 保存后等待几分钟

访问：`https://YOUR_USERNAME.github.io/gbp-boc-rate-card/`

### 5. 手动触发首次更新

1. 进入仓库 Actions 标签
2. 选择 "Update BOC GBP Rate" 工作流
3. 点击 "Run workflow"

## 📝 主要改进

### 相比原版代码的优化：

1. **更稳健的解析**
   - 使用 BeautifulSoup 替代正则表达式
   - 不易因网页结构微调而崩溃

2. **完善的错误处理**
   - 网络请求重试机制（最多3次）
   - 数据范围验证（5-15 CNY/GBP）
   - 失败时保留旧数据

3. **更好的前端体验**
   - 加载状态显示
   - 错误提示
   - 响应式设计
   - 显示汇率变化趋势

4. **自动化监控**
   - 失败时自动创建 GitHub Issue
   - 恢复时自动关闭 Issue
   - Workflow Summary 报告

5. **时间处理**
   - 同时显示 UTC 和北京时间
   - 更清晰的时间戳格式

## 🔧 自定义

### 修改更新频率

编辑 `.github/workflows/update.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: "0 */2 * * *"  # 每2小时
  # - cron: "0 */1 * * *"  # 每1小时
  # - cron: "0 0,8,12,16,20 * * *"  # 指定时间点
```

### 更换图片

在 `docs/index.html` 中找到：

```html
<div class="illustration">
  <div>💷→💴</div>
</div>
```

替换为：

```html
<div class="illustration">
  <img src="hello-kitty.png" alt="装饰图片">
</div>
```

### 调整样式

修改 `docs/index.html` 中的 CSS 变量即可。

## 🐛 故障排查

### 数据未更新

1. 检查 Actions 页面是否有失败记录
2. 查看 Issues 是否有自动创建的错误报告
3. 手动运行 workflow 测试

### 本地测试

```bash
# 安装依赖
pip install beautifulsoup4

# 运行脚本
python scripts/fetch_boc_gbp.py

# 查看生成的数据
cat docs/data.json
```

### 网页显示错误

1. 打开浏览器开发者工具（F12）
2. 查看 Console 标签的错误信息
3. 确认 `data.json` 是否存在且格式正确

## 📊 数据格式

`data.json` 示例：

```json
{
  "currency": "英镑",
  "pair": "GBP/CNY",
  "boc_field": "现汇卖出价",
  "rate_cny_per_gbp": 9.3654,
  "rate_cny_per_100_gbp": 936.54,
  "publish_time_raw": "2026-01-17 10:30:00",
  "fetched_at_utc": "2026-01-17T10:35:22Z",
  "fetched_at_beijing": "2026-01-17 18:35:22",
  "source": "https://www.boc.cn/sourcedb/whpj/",
  "status": "success",
  "rate_change": 0.0123,
  "rate_change_percent": 0.13
}
```

## 📜 License

MIT

## 🙏 致谢

- 数据来源：[中国银行外汇牌价](https://www.boc.cn/sourcedb/whpj/)
- GitHub Actions
- BeautifulSoup4
