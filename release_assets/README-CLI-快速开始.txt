Stella CLI 快速开始（命令行控制台版）
========================================

本包 = Stella 完整程序 + 命令行控制台 stellacli（适合没有图形界面的设备）。

重要：stellacli 只是「编排层」——doctor / init / start / stop / status /
logs 等命令的领域逻辑由包内 Python deploy 模块提供。请把压缩包**完整解压**
后在本目录内使用，不能只拿出 stellacli 单文件运行。

【Windows】
1. 解压到任意目录（建议路径不含空格与中文）。
2. 首次使用先准备运行时（下载嵌入式 Python 并安装依赖，只需一次）：
   在命令行运行：  start.bat --prepare
3. 环境自检：      stellacli.exe doctor
4. 配置向导：      stellacli.exe init
5. 启动：          stellacli.exe start
6. 查看全部命令：  stellacli.exe --help

【Linux】
1. 解压：tar xzf Stella-CLI-version-v*-linux-amd64.tar.gz
2. 准备 Python 3.10+ 与依赖：
   python3 -m pip install -r requirements.txt
3. 环境自检：      ./stellacli doctor
4. 配置向导：      ./stellacli init
5. 启动：          ./stellacli start

【数据在哪】
用户数据（记忆、配置、日志）都在程序目录同级的 StellaData/ 里。
升级到新版本时：解压新版到新目录，把旧目录同级的 StellaData/ 保持在新目录
同级即可，全部记忆随之迁移。

【更多文档】
docs/ 目录（部署、配置说明）；docker 部署见 docs/deployment-docker.md。
