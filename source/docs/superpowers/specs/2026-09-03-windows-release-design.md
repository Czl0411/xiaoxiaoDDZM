# DZMMBot Windows 发布设计

## 目标

在公开 GitHub 仓库 `Czl0411/xiaoxiaoDDZM` 中维护不含真实用户数据和密钥的源码，并通过 GitHub Actions 的 Windows Runner 同时生成：

- `DZMMBot-Portable-win64.zip`：便携版程序包。
- `DZMMBot-Setup-win64.exe`：Windows 安装包。

实际 Windows 用户安装后使用当前 Mac 机器人中的业务数据，而不是沿用该用户旧电脑上的数据。

## 发布边界

公开仓库只包含源码、测试、公共素材、构建工作流和安装脚本。以下内容不得进入 Git 历史、Actions Artifact 或公开 Release：

- `data/bot.db`
- `data/config.json`
- `data/secrets.json`
- `data/browser_profile/`
- `data/logs/`
- `app/_embedded_secret_payload.py`
- 本地构建目录、缓存、旧备份和现有可执行文件

当前 `_embedded_secret_payload.py` 保留在本机供现有机器人使用，但由 `.gitignore` 排除。Actions 在构建工作区临时生成空载荷版本，发布程序不内置任何私人 API Key。

## Windows 构建

GitHub Actions 使用 `windows-latest`，执行以下流程：

1. 检出公开源码。
2. 安装指定版本的 Python 和项目依赖。
3. 安装 PyInstaller。
4. 安装 Playwright Chromium，并将浏览器文件放入最终程序目录的 `ms-playwright`。
5. 临时生成空的 `app/_embedded_secret_payload.py`。
6. 使用 `DZMMBot.spec` 构建 PyInstaller 目录版应用。
7. 复制公共素材和运行所需文件。
8. 压缩完整程序目录为便携版 ZIP。
9. 使用 Inno Setup 将同一程序目录制作成 Setup.exe。
10. 上传两个构建产物。

工作流支持手动触发。普通分支构建将产物保存为 Actions Artifacts；版本标签构建可以进一步发布到 GitHub Releases。

## 便携版行为

便携版包含程序文件、`_internal`、Playwright Chromium 和公共素材，不包含真实 `data`。用户必须先完整解压，再运行 `DZMM群聊机器人.exe`。

首次运行时程序能够自行创建空的 `data` 目录。本次实际交付会在首次启动前导入单独提供的当前数据包。

## 安装版行为

安装版默认安装到当前用户可写目录，不要求管理员权限。安装器只安装或覆盖程序文件，不安装、不覆盖、也不删除 `data`。升级安装选择同一目录时，已存在的 `data` 必须保持原样。

卸载器也不主动删除运行后生成的 `data`，避免误删业务数据库。若用户需要彻底清理，应由用户手动删除剩余数据目录。

## 当前数据包

在 Mac 本地额外生成 `DZMMBot-current-data.zip`，并确保它永远不被 Git 跟踪。该数据包只通过私下渠道发送给唯一的 Windows 用户。

数据包包含：

- `data/bot.db`
- `data/config.json`
- `data/shop_images/`
- `data/image_generation/` 中业务需要保留的文件

数据包不包含：

- `data/browser_profile/`：Mac 浏览器资料不能可靠迁移到 Windows。
- `data/secrets.json`：不向对方传递本机 API Key。
- `data/logs/`：没有迁移价值，且可能包含运行信息。

Windows 用户应在机器人完全关闭时导入该数据包，然后重新登录 DZMM，并在后台填写自己的 DeepSeek API Key。

## WebView2 与包体积

Playwright Chromium是消息收发所需运行依赖，必须随两个发布包提供。现有固定 WebView2 Runtime 约 850MB，不直接打入发布包；程序优先使用 Windows 10/11 通常已有的 WebView2 Runtime。安装说明会提供缺失时的安装提示。

## 仓库结构

```text
.github/workflows/build-windows.yml
installer/DZMMBot.iss
source/
盲盒小游戏素材/
.gitignore
README.md
```

仓库从当前工作目录初始化，但编译产物、真实数据、密钥和无关本地文件均通过白名单式提交检查排除。

## 验证标准

- 敏感文件扫描确认 Git 暂存区中不存在数据库、配置、登录资料、密钥载荷和日志。
- Python 测试在构建前通过；已知历史旧测试若与当前产品规则冲突，必须单独列出，不能伪装为通过。
- PyInstaller 构建成功，输出目录含 EXE、`_internal`、`ms-playwright` 和公共素材。
- 便携版 ZIP 可以解压并启动。
- Setup.exe 可以安装到当前用户目录，并在覆盖安装时保留已有 `data`。
- 本地当前数据包包含约定的业务数据，不包含浏览器资料、密钥和日志。

