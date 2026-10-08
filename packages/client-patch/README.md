# OpenXiaoAI Patch

> [!CAUTION]
> 刷机有风险，操作需谨慎。请勿下载使用不明来历的固件！

小爱音箱 Pro 补丁固件制作流程：

- 固件提取（登录小米账号获取 OTA 链接）
- 开启固化 SSH（支持自定义登录密码）
- 禁用系统自动更新（系统更新后需要重新刷机打补丁）
- 添加开机启动脚本 `/data/init.sh`（方便执行一些初始化脚本）

## 下载固件

你可以直接在 [Github Releases](https://github.com/OwnDing/open-xiaoai/releases) 页面下载打包好的固件：

- [Xiaomi 智能音箱 Pro v1.62.2](https://github.com/OwnDing/open-xiaoai/releases/tag/OH2P_1.62.2)
- [Xiaomi 智能音箱 Pro v1.58.6](https://github.com/idootop/open-xiaoai/releases/tag/OH2P_1.58.6)
- [小爱音箱 Pro v1.94.13](https://github.com/idootop/open-xiaoai/releases/tag/LX06_1.94.13)

LX06 已有机型支持；对于 **1.94.14**，另有[同版本校验构建与验证记录](../../docs/lx06-1.94.14.md)。这是本地构建入口，不是已经发布的固件下载链接，不应使用 1.94.13 代替。

> [!TIP]
> 里面有两个文件，下载 `patched` 那个：
>
> - `xxx_patched.squashfs` 打补丁后的固件
> - `xxx.squashfs` 原版固件（可用来刷回原系统）

> [!NOTE]
> 默认 SSH 登录密码为 `open-xiaoai`，如需修改请自行制作固件。

> [!IMPORTANT]
> 请下载和你当前小爱音箱版本一致的固件，跨版本刷机可能会出现未知错误，导致设备变砖。
> 如果上面没有你的版本，请升级设备固件到最新版本，或者按照下面的教程自行制作固件。

> [!CAUTION]
> 本节当前列出的预制固件下载版本为：
>
> - Xiaomi 智能音箱 Pro 👉 [v1.62.2](https://github.com/OwnDing/open-xiaoai/releases/tag/OH2P_1.62.2)
> - 小爱音箱 Pro 👉 [v1.94.13](https://github.com/idootop/open-xiaoai/releases/tag/LX06_1.94.13)
>
> 更新版本的固件可能存在变化，导致刷机失败，设备变砖，请自行评估风险。

### 已校验的本地构建版本

| 机型 / ROM | 入口 | 状态 |
| --- | --- | --- |
| LX06 / 1.94.14 | `python3 src/build_verified.py --ota /absolute/input.bin --output /absolute/new-output` | 官方 OTA 摘要、补丁与音频库偏移检查；离线复解包/重复打包通过；历史单机启动验证见[说明](../../docs/lx06-1.94.14.md) |

新入口不访问小米账号、不刷写设备，不替代下文的通用构建流程。它只接受指定 profile，失败时停止，不强行应用模糊补丁。SSH 密码随机生成并保存在私密输出目录，不能沿用预制固件的默认密码说明。

## 制作固件

你可以按照下面的 2 种方法，制作自定义固件。

### 基础配置

修改 `.env.example` 文件里的配置，然后重命名为 `.env`。

```shell
# 你的小米账号/密码
MI_USER=23333333
MI_PASS=xxxxxxxxx

# 你的小爱音箱名称/DID
MI_DID=小爱音箱Pro

# 你的 SSH 登录密码（默认为 open-xiaoai）
SSH_PASSWORD=open-xiaoai
```

### 1. 使用 Docker 打包固件（推荐）

[![Docker Image Version](https://img.shields.io/docker/v/idootop/open-xiaoai?color=%23086DCD&label=docker%20image)](https://hub.docker.com/r/idootop/open-xiaoai)

为了能够正常编译运行该项目，你需要安装以下依赖：

- Docker：https://www.docker.com/get-started/

> [!NOTE]
> Windows 系统请在 [Git Bash](https://git-scm.com/downloads) 终端中运行以下命令。

> [!TIP]
> 如果你是 Apple Silicon 芯片，请先在 Docker Desktop - Settings - General - Virtual Machine Options 中打开 Apple Virtual framework 选项，然后开启 `Use Rosetta for x86_64/amd64 emulation on Apple Silicon`

```shell
# 克隆代码
git clone https://github.com/idootop/open-xiaoai.git

# 进入当前项目根目录
cd packages/client-patch

# 使用 Docker 进行构建
docker run -it --rm \
    --platform linux/amd64 \
    --env-file $(pwd)/.env \
    -v $(pwd)/assets:/app/assets \
    -v $(pwd)/patches:/app/patches \
    idootop/open-xiaoai:latest

# ✅ 打包完成，固件文件已复制到 assets 目录...
# /app/assets/mico_all_92db90ed6_1.88.197/root-patched.squashfs
```

### 2. 本地构建（macOS、Linux）

为了能够正常编译运行该项目，你需要安装以下依赖：

- Python 3.x：https://www.python.org/downloads/
- Node.js 22.x: https://nodejs.org/zh-cn/download

```bash
# 克隆代码
git clone https://github.com/idootop/open-xiaoai.git

# 进入当前项目根目录
cd packages/client-patch

# 安装依赖
npm install

# 打包固件
npm run build

# ✅ 打包成功后，原始固件和补丁固件会保存在 assets 目录下
```

> [!TIP]
> 如果你想要更进一步的定制自己的固件，可以参考 `src/build.sh` 脚本里的构建流程：在提取固件后自行修改固件内的脚本、配置和应用程序，然后重新打包即可。

## 高级选项

### 1. 自定义启动脚本

默认修改后的补丁固件，会将 `/data/init.sh` 文件作为启动脚本，开机时自动运行。如果你需要自定义开机启动脚本，可自行创建和修改该文件。

示例：

```bash
#!/bin/sh

/usr/sbin/tts_play.sh '初始化成功'
```
