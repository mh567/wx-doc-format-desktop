# 银河麒麟 V10 ARM64 发布包

## 用户运行

1. 下载 Release 中的 `wx-doc-format-<版本号>-kylin-v10-arm64.tar.gz`。
2. 解压归档，进入解压后的 `MagicFormat-<版本号>` 目录。
3. 双击 `MagicFormat` 启动程序。桌面环境也可以双击 `MagicFormat.desktop`。
4. 如果文件管理器不允许直接启动，可在终端进入该目录后执行 `./start.sh`。
5. 程序启动后会打开本地操作页面，页面只监听本机地址。

目录中的 `双击 MagicFormat 运行.txt` 是给用户识别启动文件用的空提示文件。`MagicFormat` 是前台启动器，`MagicFormatServer` 是后台服务，`native_skill/` 保存经过校验的编译格式化运行时。

发布包自带运行所需的 Python 和文档格式化运行时，用户无需安装 Python、pip 或上游 Skill 源码。首次运行仍需要满足银河麒麟 V10 ARM64 的系统兼容性要求。

## 构建与验证

Kylin 包由 `.github/workflows/release.yml` 在 ARM64 runner 中调用 `build_in_container.sh` 生成。脚本会执行测试、下载并校验同版本编译 Skill、构建目录包，并生成 `双击 MagicFormat 运行.txt`。

发布前至少检查：

```bash
sha256sum -c SHA256SUMS.txt
tar -tzf wx-doc-format-<版本号>-kylin-v10-arm64.tar.gz
```

归档顶层应包含 `MagicFormat`、`MagicFormatServer`、`start.sh`、`MagicFormat.desktop`、`双击 MagicFormat 运行.txt` 和 `native_skill/`。
