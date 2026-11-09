# regview · 注册表图形化查看器

一个**只读**的 Windows 注册表图形化查看工具：左侧树形导航、右侧值列表、搜索、收藏、导出，全部功能开箱可用。零第三方依赖，只需要 Python 3.9+ 与浏览器。

> 后端全部使用标准库（`winreg` + `http.server`），前端是随包附带的原生 HTML/CSS/JS 单页应用。
> 之所以用「本地浏览器界面」而不是 tkinter 窗口：很多精简版 Python 不带 tkinter，而浏览器界面不挑环境、能做出更现代的交互，同时完全离线、不访问外网。

## 快速开始

```bash
# 在项目根目录
python -m regview
```

命令会随机生成一个访问 token，只监听 `127.0.0.1`，并自动打开浏览器：

```
regview 1.0.0 | 只读注册表查看器
打开地址：http://127.0.0.1:54321/?token=xxxxxxxx
仅监听 127.0.0.1，按 Ctrl+C 停止。
```

指定端口 / 不自动开浏览器：

```bash
python -m regview serve --port 8765 --no-browser
# 然后用终端打印的完整地址（含 token）打开
```

安装成命令（可选）：

```bash
pip install -e .
regview                       # 等价于 python -m regview
```

## 界面功能

| 区域 | 说明 |
| --- | --- |
| 地址栏 | 直接输入 `HKLM\SOFTWARE\...` 或全名跳转；支持 `/` 与 `\`、大小写别名、上级、刷新、复制路径 |
| 注册表树 | 五个根键，**懒加载**子键（不会一打开就遍历整个注册表），可展开/折叠，左右分栏宽度可拖动 |
| 值列表 | 名称 / 类型徽章 / 数据 / 大小；默认值显示为 `(默认)` |
| 值详情 | 完整字符串、`REG_EXPAND_SZ` 环境变量展开结果、二进制值的带偏移 hex dump、一键复制 |
| 搜索 | 按子键名 / 值名 / 值数据搜索，可选范围（键+值 / 仅键 / 仅值）与起点（当前键或任一根键），可中途停止 |
| 收藏夹 | 常用路径一键收藏/取消，持久化到 `~/.regview/bookmarks.json` |
| 导出 | 当前键及其子键导出为 `.reg` / JSON / CSV |
| 视图切换 | 默认 / 64 位 / 32 位 WOW64 视图 |
| 其它 | 明暗主题（跟随系统）、状态栏、错误提示、加载态、空态 |

快捷键：`Ctrl+F` 搜索 · `F5` 刷新 · `Alt+↑` 上级 · `Ctrl+L` 定位地址栏 · `Esc` 关闭抽屉/详情 · 回车跳转。

支持全部常见值类型：`REG_SZ`、`REG_EXPAND_SZ`、`REG_MULTI_SZ`、`REG_DWORD`、`REG_QWORD`、`REG_BINARY`、`REG_NONE`、`REG_LINK` 及其它资源类型。

## 命令行（无界面）

适合脚本、远程终端或 CI 使用：

```bash
python -m regview roots
python -m regview list HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion
python -m regview get "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion" ProductName
python -m regview search Wallpaper --root HKCU --scope values --limit 20 --json
python -m regview export HKCU\Environment --format reg --output env-backup.reg
python -m regview export HKCU\Software\Acme --format csv --output acme.csv
python -m regview list HKLM\SOFTWARE --view 32
```

`list` / `get` / `search` 加 `--json` 输出结构化数据；`export` 不写 `--output` 时打印到 stdout。

## 安全设计

这个项目是**查看器**，不是编辑器。任何操作都不会修改注册表：

- 所有键都以 `winreg.KEY_READ`（+ 可选的 WOW64 视图标志）打开，源码中不存在 `SetValue` / `CreateKey` / `DeleteKey` 等写入调用，并有静态测试守着这条约束；
- 服务只绑定 `127.0.0.1`，显式拒绝其它 host 与非本地 `Origin`，防止 DNS rebinding / 跨站读取；
- 每次 API 请求都要带**启动时随机生成的一次性 token**，token 只出现在终端打印的地址里；
- 响应带 `no-store` CSP、`nosniff`、`no-referrer`；前端无外部资源、无 CDN，全部文本用 `textContent` 渲染（注册表键名不会被当成 HTML 执行）；
- 导出与收藏只写普通文件，不碰注册表。

**导出文件仍可能包含敏感信息**（如路径、用户名、序列号等），`.reg` 文件双击会导入注册表，请谨慎分享。

导出格式说明：

| 格式 | 编码 | 用途 |
| --- | --- | --- |
| `.reg` | UTF-16 LE + BOM，CRLF | Windows 注册表编辑器 5.00 格式，可被 `regedit` 识别；含 `dword:` / `hex(2)` / `hex(7)` / `hex(b)` 等 |
| `.json` | UTF-8 | 结构化备份、diff、脚本处理（含 `readonly: true` 与生成时间） |
| `.csv` | UTF-8 BOM | Excel 打开不乱码，逐行列出键路径 / 值名 / 类型 / 数据 / 大小 |

## 常见问题

- **「拒绝访问：该键受系统保护」**：部分键（如 `HKLM\SAM`、`HKLM\SECURITY`）需要管理员权限，或受系统保护。以管理员身份运行即可查看，查看器仍不会写入。树/搜索/导出都会跳过这类键并计数，不会中断。
- **搜索结果不全**：搜索有命中数、扫描键数和时间三重上限，界面会提示「已截断」。缩小起点范围或换更精确的关键字即可。
- **32 位看不到某个键**：在工具栏切换到 `64 位视图`（WOW64 重定向）。
- **端口被占用**：默认自动选空闲端口，也可用 `serve --port 8765` 指定。
- **要不要联网**：不需要。服务只在本机回环地址，前端资源随包附带。

## 项目结构

```
registry-viewer/
├── regview/
│   ├── paths.py       # 路径解析/规范化（纯函数，跨平台可测）
│   ├── values.py      # 值类型展示、hex dump、.reg 序列化
│   ├── registry.py    # winreg 只读封装、懒加载、遍历
│   ├── search.py      # 带上限/取消的搜索
│   ├── export.py      # .reg / JSON / CSV 导出
│   ├── bookmarks.py   # 收藏夹持久化
│   ├── server.py      # 本地 HTTP API + token/Host/Origin 校验
│   ├── cli.py         # GUI 启动 + headless 子命令
│   └── web/           # index.html / app.js / style.css / favicon.svg
├── tests/             # 单元测试 + 内存版注册表 + Windows 真机只读测试
└── .github/workflows/ci.yml
```

## 开发与测试

```bash
python -m unittest discover -s tests -t . -v
```

测试分两类：注入内存版 `FakeRegistry` 的纯逻辑测试（路径、值序列化、导出、搜索、HTTP API、安全边界）在所有平台运行；真机只读冒烟测试只在 Windows 上执行。CI 覆盖 Linux / macOS / Windows × Python 3.9 / 3.11 / 3.13。

## 限制

- 后端依赖 `winreg`，因此**读取注册表只能在 Windows**；其它平台可运行纯逻辑测试与 UI 服务（注入假数据）。
- 只读设计：不提供新增、修改、删除、重命名、导入、权限编辑，也不支持远程注册表。
- 单个键最多列出 10000 个子键 / 5000 个值，避免界面卡死；超大键请用命令行 `export` 并调 `--max-keys`。

## 许可证

MIT
