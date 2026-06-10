# Douyin Monitor

GitHub Actions 版抖音博主视频监控 - 每天自动抓取更新并发送邮件通知。

## 工作原理

1. 每天 08:00 (北京时间) 自动触发 GitHub Actions
2. 用 Playwright 无头浏览器访问抖音博主主页
3. 提取最新视频信息（标题、链接）
4. 过滤已发送视频，只通知新内容
5. 发送邮件到指定邮箱
6. 将发送记录提交回仓库，避免重复通知

## 快速部署

### 1. 创建 GitHub 仓库

在 GitHub 上创建一个 **Private** 仓库（推荐私有，避免泄露博主信息），例如 `douyin-monitor`。

### 2. 推送代码

```bash
cd douyin-monitor-github
git init
git add .
git commit -m "init: douyin monitor"
git remote add origin https://github.com/<你的用户名>/douyin-monitor.git
git push -u origin main
```

### 3. 配置 GitHub Secrets

进入仓库 → Settings → Secrets and variables → Actions → New repository secret

添加以下 4 个 Secret：

| Secret 名称 | 值 |
|---|---|
| `EMAIL_PROVIDER` | `qq` |
| `EMAIL_SMTP_USER` | `gupengfee@qq.com` |
| `EMAIL_SMTP_PASS` | 你的QQ邮箱授权码 |
| `EMAIL_RECIPIENT` | `262991250@qq.com` |

### 4. 添加博主

编辑 `config/creators.json`，在 `creators` 数组中添加/修改博主信息。

### 5. 手动测试

进入仓库 → Actions → Douyin Daily Monitor → Run workflow 手动触发一次测试。

## 文件说明

```
├── .github/workflows/
│   └── daily-monitor.yml    # GitHub Actions 定时任务
├── config/
│   └── creators.json         # 博主配置
├── data/
│   └── sent_history.json     # 已发送记录（自动更新）
├── scripts/
│   ├── run.py                # 主入口
│   ├── fetch_douyin.py       # 抖音抓取
│   └── send_email.py         # 邮件发送
└── requirements.txt
```

## 注意事项

- 抖音页面结构可能变化，如果抓取不到视频需要更新选择器
- GitHub Actions 的 cron 不保证精确时间，可能延迟几分钟
- 仓库必须至少有一个 commit 后 Actions 才能正常运行
