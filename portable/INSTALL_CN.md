# XAFS Workbench Windows 安装与启动

本发布包既可在单台 Windows 电脑本地运行，也可由一台装有科研软件的计算服务机
供同一网络内的其他电脑使用。GitHub Pages 提供前端入口，拟合计算仍由计算服务机完成。

## 推荐：独立桌面版

从 GitHub Releases 下载 `XAFS-Workbench-Windows-Standalone.zip`，解压后双击
`XAFS-Workbench.exe`。桌面版自带 Python 运行时，会自动启动本地服务并打开浏览器，
不依赖 Codex、VS Code 或系统 Python。拟合记录保存在
`%LOCALAPPDATA%\XAFS Workbench\fit-results`，重启后仍可下载。

Athena、Artemis、IFEFFIT/FEFF 和 HAMA 属于独立科研软件，仍需按官方方式安装。

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
4. 双击 `launch_workbench.cmd` 后，在“原生软件连接”中确认 Athena、Artemis、Hephaestus 和 HAMA 的状态。

如果 PowerShell 阻止脚本，可在解压目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1
```

## 3. 日常启动

双击 `launch_workbench.cmd`。此模式只供当前电脑使用，关闭 Codex不会影响通过登录任务启动的工作台。

## 4. 其他电脑通过浏览器使用

在已经安装并配置好 Demeter/IFEFFIT 的计算服务机运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_xafs_workbench_network.ps1
```

脚本会显示类似 `http://LAB-PC:8765/` 的地址和随机访问密钥。保持窗口运行；其他电脑打开该地址，
在页面顶部填入访问密钥即可。客户端电脑不需要 Python、Codex、VS Code、Demeter 或 HAMA。
若使用独立桌面版，在计算服务机直接双击 `launch_network_workbench.cmd` 即可启动相同的网络模式。
如无法连接，请在服务机的 Windows 防火墙中允许所用 TCP 端口。不要把该 HTTP 端口直接暴露到公网；
跨互联网使用必须由管理员配置 HTTPS 反向代理和更完整的身份认证。

## 5. 原生软件路径

工具按环境变量、`native_tools.local.json`、系统 `PATH` 的顺序检测程序。
若未自动识别，请复制 `native_tools.example.json` 为
`native_tools.local.json`，把各项改为本机实际可执行文件路径后重新启动。

## 6. 数据与拟合原则

- 上传数据后先点击“诊断当前数据”。没有连续异常前段时保持截取下限为空；只有诊断给出明确建议并经原始计数通道复核后，才应用建议下限。
- `11115 eV` 只适用于此前确认异常的 Ir 数据，不得用于其他元素、其他吸收边或其他扫描。
- 数据处理：Demeter/Athena。
- FEFF 路径与 EXAFS 拟合：Demeter/Artemis + IFEFFIT/FEFF。
- 小波变换：HAMA Fortran（Morlet/Cauchy）。
- 从第一壳扩展至第二壳时，先固定已校准的 S0² 和稳定的第一壳参数，
  再按第二壳的 ΔR、σ²、CN 顺序逐项释放；每一步检查独立点数、参数误差、
  参数相关性、R-factor/AIC 以及 K/R 空间残差。

完整图文步骤见 `docs/XAFS_Workbench_data_processing_and_staged_fitting_CN.pdf`。

## 7. 隐私与公开网页限制

公开网页不能直接启动访客电脑或服务机上的桌面程序。网络模式上传的数据会发送到你指定的计算服务机，
不会上传到 GitHub；拟合结果保存在服务机的用户数据目录中。
