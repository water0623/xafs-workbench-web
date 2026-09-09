# XAFS Workbench Windows 安装与启动

本发布包用于在每台 Windows 电脑上建立独立的本地运行环境。GitHub Pages
只提供公开入口和下载，实验数据与拟合计算均在用户自己的电脑上完成。

## 1. 必需软件

1. 安装 64 位 Python 3.11 或更新版本，并勾选 Python Launcher。
2. 从 Demeter 官方页面安装 Athena、Artemis、Hephaestus 和 IFEFFIT/FEFF。
3. 如需小波变换，从 ESRF 官方页面下载并安装 HAMA Fortran。

本工具不会使用 XrayLarch 处理数据或执行拟合。XrayLarch 仅保留为可选的
CIF 到 FEFF 辅助工具，未安装时不影响 Athena/Artemis 原生流程。

## 2. 首次安装

1. 解压 `XAFS-Workbench-Windows.zip` 到只含英文或数字的目录。
2. 右键 `setup_windows.ps1`，选择“使用 PowerShell 运行”。
3. 脚本会创建独立的 `.venv`、安装网页后端依赖，并注册当前用户登录时自动启动。
4. 浏览器打开 `http://127.0.0.1:8765/` 后，在“原生软件连接”中确认
   Athena、Artemis、Hephaestus 和 HAMA 的状态。

如果 PowerShell 阻止脚本，可在解压目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

## 3. 日常启动

双击 `launch_workbench.cmd`。服务只监听本机 `127.0.0.1:8765`，关闭 Codex
不会影响通过登录任务启动的工作台。

## 4. 原生软件路径

工具按环境变量、`native_tools.local.json`、系统 `PATH` 的顺序检测程序。
若未自动识别，请复制 `native_tools.example.json` 为
`native_tools.local.json`，把各项改为本机实际可执行文件路径后重新启动。

## 5. 数据与拟合原则

- 数据处理：Demeter/Athena。
- FEFF 路径与 EXAFS 拟合：Demeter/Artemis + IFEFFIT/FEFF。
- 小波变换：HAMA Fortran（Morlet/Cauchy）。
- 从第一壳扩展至第二壳时，先固定已校准的 S0² 和稳定的第一壳参数，
  再按第二壳的 ΔR、σ²、CN 顺序逐项释放；每一步检查独立点数、参数误差、
  参数相关性、R-factor/AIC 以及 K/R 空间残差。

完整图文步骤见 `docs/XAFS_Workbench_data_processing_and_staged_fitting_CN.pdf`。

## 6. 隐私与公开网页限制

公开网页不能直接启动访客电脑上的桌面程序。必须先在该电脑安装本地包，
网页界面才能连接本机后端。默认情况下原始数据不会上传到 GitHub。
