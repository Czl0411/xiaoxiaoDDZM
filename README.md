# 小小 DZMM 群聊机器人

这是 Windows 64 位桌面机器人源码。公开构建不包含真实数据或 API Key。

## 下载产物

- `DZMMBot-Portable-win64.zip`：完整解压后，双击 `DZMM群聊机器人.exe`。
- `DZMMBot-Setup-win64.exe`：安装到当前用户目录，可创建桌面快捷方式。

两个产物都包含程序依赖和 Playwright Chromium，不需要另外安装 Python。Windows 10/11 需要可用的 Microsoft Edge WebView2 Runtime。

## 导入当前业务数据

真实业务数据通过私下提供的 `DZMMBot-current-data.zip` 迁移，不会上传到本仓库或公开构建。

1. 完全关闭机器人。
2. 安装或解压新版程序，但暂时不要启动。
3. 将 `DZMMBot-current-data.zip` 解压到 EXE 所在目录，使该目录下出现 `data/bot.db` 和 `data/config.json`。
4. 启动机器人，在 Windows 上重新登录 DZMM。
5. 在后台填写使用者自己的 DeepSeek API Key。

升级前请备份整个 `data`。安装器只覆盖程序文件，不负责删除或覆盖运行中产生的 `data`。

## 自动构建

在 GitHub 的 Actions 页面手动运行 `Build Windows releases`，或向 `main` 分支推送。构建完成后可下载便携版 ZIP 和安装版 Setup.exe。

## 安全

禁止提交数据库、配置、浏览器登录资料、日志、密钥文件和内嵌密钥载荷。公开 EXE 不内置维护者的 DeepSeek API Key。
