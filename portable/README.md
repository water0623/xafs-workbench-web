# XAFS Workbench

本地优先的 XAFS 数据处理、FEFF 路径拟合与小波分析网页工作台。

## 计算后端

- 数据处理：直接调用本机 **Demeter/IFEFFIT**，使用与 Athena 相同的 `Demeter::Data` 预边、归一化、AUTOBK 和傅里叶变换流程。
- 桌面连接器：分别检测“已安装”和“正在运行”，支持 Athena、Artemis、Hephaestus（Demeter）和 HAMA Fortran；页面每 5 秒刷新一次运行态。
- 拟合：网页通过本机 Demeter/IFEFFIT 执行 Artemis 方法的 FEFF 路径拟合；XrayLarch 数据处理和拟合均已禁用。
- 小波：网页调用 ESRF 官方 HAMA Fortran，以等间隔 χ(k) ASCII 数据执行 Morlet 变换并返回实验、拟合和残差矩阵。
- 小波：界面仅提供 HAMA 工作流；未检测到 HAMA 时不会把其他实现标成 HAMA 原生输出。

> 仓库不包含 Demeter 或 HAMA 可执行文件。请只从第三方官方主页下载，并遵守各自许可证。

## 安装

需要 Python 3.11 或更高版本，并先安装 Demeter（包含 Athena、Artemis、Hephaestus 和 IFEFFIT）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-xafs-workbench.txt
```

主依赖不再安装 XrayLarch。当前 CIF → FEFF 路径生成器若仍需旧的辅助接口，可选择安装
`requirements-optional-feff-helper.txt`；该可选包不会被数据处理或拟合接口调用。

仅在服务机本地使用：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_xafs_workbench.ps1
```

浏览器会使用这台电脑上的服务。

## 跨电脑网络模式

只需在一台 Windows 计算服务机安装 Python、Demeter/IFEFFIT 和 HAMA。首次完成上述安装后，在服务机运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_xafs_workbench_network.ps1
```

脚本会显示主机名地址（例如 `http://LAB-PC:8765/`）和一次随机生成的访问密钥。
其他电脑无需 Python、Codex 或 VS Code：在浏览器打开该主机名地址，在页面顶部填写访问密钥即可处理和拟合数据。
独立桌面版用户也可以直接双击 `launch_network_workbench.cmd`，无需安装 Python。
服务窗口关闭后网络服务停止；需要固定密钥时可使用：

```powershell
$env:XAFS_ACCESS_TOKEN = '请替换为足够长的随机密钥'
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_xafs_workbench_network.ps1
```

若客户端无法连接，请允许服务机 Windows 防火墙访问所用 TCP 端口。局域网以外使用时必须配置 HTTPS、可信身份认证和反向代理；不要直接把 8765 端口映射到公网。

如需退出 Codex 或关闭终端后仍保持服务，并在 Windows 登录时自动启动，可执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install_xafs_autostart.ps1
```

不再需要时运行 `uninstall_xafs_autostart.ps1` 即可移除该登录任务。

如果 Windows Store Python 无法从中文路径启动，可复制
`xafs_workbench.local.example.ps1` 为 `xafs_workbench.local.ps1`，并填写本机
Python 3.11+ 路径。本地配置不会进入 Git。

## GitHub Pages 前端

本仓库可通过 `scripts/build_pages.py` 构建同一套处理界面，公开版本发布在：

<https://water0623.github.io/xafs-workbench-web/>

公开页面代码单独发布在
[water0623/xafs-workbench-web](https://github.com/water0623/xafs-workbench-web)，
本仓库继续保持私有，以免把本机集成与后续实验资料意外公开。

GitHub Pages 只托管公开入口，不运行 Python、Demeter/IFEFFIT、FEFF 或 HAMA。现代浏览器会阻止 HTTPS
公开页在后台读取本机 HTTP 服务，因此公开页不进行容易失败的自动探测，也会锁定计算控件，避免请求
GitHub Pages 而产生 HTTP 405。首次使用建议下载 Windows 桌面版，解压并运行 `XAFS-Workbench.exe`；
桌面版会打开本机工作台并自动搜索四个原生程序。以后也可先启动桌面版，再点击公开页的“打开本机工作台”，即可查看 Athena、Artemis、
Hephaestus 与 HAMA 的安装/运行状态并执行处理。其他电脑通过局域网使用时，请直接打开
`launch_network_workbench.cmd` 显示的主机名地址，并在需要时填写脚本生成的访问密钥。
出于安全考虑，跨来源或远程客户端不能启动服务机上的桌面程序；如需启动，请在服务机本地操作。

若前端部署在其他域名，可设置环境变量 `XAFS_ALLOWED_ORIGINS`（多个来源用逗号分隔）
后再启动服务。网络模式会通过 `XAFS_ACCESS_TOKEN` 启用 API 访问控制。

## 连接原生软件

1. 从 [Demeter 官方主页](https://bruceravel.github.io/demeter/)安装 Athena、Artemis 和 Hephaestus。
2. 按 [ESRF HAMA 说明](https://www.esrf.fr/files/live/sites/www/files/UsersAndScience/Experiments/CRG/BM20/Software/Wavelets/HAMA/hamareadmepdf.pdf)获取并安装 HAMA Fortran。
3. 复制 `native_tools.example.json` 为 `native_tools.local.json`，填入本机程序路径；该文件已被 Git 忽略。

也可以配置：`XAFS_ATHENA_EXE`、`XAFS_ARTEMIS_EXE`、`XAFS_HEPHAESTUS_EXE`、`XAFS_HAMA_EXE`。检测顺序为环境变量、本地配置文件、系统 PATH。

当前连接器会自动搜索常见的 `DemeterPerl` 安装目录，并通过 Windows 进程命令行区分共用 `perl.exe` 的三个 Demeter 程序。状态卡的“已安装”和“正在运行”是两个独立状态。

数据处理与 FEFF 定量拟合均采用 Demeter/IFEFFIT；HAMA 使用其原生 ASCII 输入/输出桥接。程序不会回退到 XrayLarch 处理或拟合，也不会通过屏幕抓取伪造结果。

## 输出

拟合结果可导出实验/拟合的能量、K、R 空间数据，小波矩阵，GDS/路径参数，误差、相关性、Nind、R-factor 以及论文格式表格。经验范围仅用于复核，不替代样品结构和统计判断。

## 隐私与发布

`raw_data/`、`tutorial_fit_results/`、`xas_batch_results/`、本地程序路径和日志默认不进入 Git。发布示例数据前，请确认数据所有权、脱敏状态和再分发许可。

## 测试

```powershell
py -3.11 -m unittest discover -s public_tests -v
```

公开测试不包含实验数据，只验证核心 HAMA、输入校验、元素数据库和原生连接器。项目维护者可在本地运行未发布的实验集成测试。
