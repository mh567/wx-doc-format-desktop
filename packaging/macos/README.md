# macOS 发布

## 当前工作流

1. 在 Apple Silicon GitHub runner 上安装测试和构建依赖。
2. 执行 `python packaging/build.py`，从 `wx-doc-format-skill` 同版本 Release 下载并校验编译运行时，将其嵌入 `MagicFormat.app`。
3. 对 `.app` 执行临时签名，并使用 `ditto` 生成 `wx-doc-format-<版本号>-macos-arm64.zip`。
4. 对解压后的应用执行代码签名校验、原生运行时版本校验和真实 Markdown 转换冒烟测试。

当前公开工作流提供可运行的 Apple Silicon ZIP 包，使用临时签名。它没有执行 Developer ID 签名、Hardened Runtime、公证、DMG 或 stapler 流程，用户可能需要在系统设置中允许首次启动。

## 正式发行前

正式发行前应在受控签名环境中完成：

1. 对 `.app` 内部 Mach-O 文件和最外层 `.app` 使用 Developer ID 签名，并开启 Hardened Runtime。
2. 生成 DMG，通过 `notarytool` 提交 Apple 公证。
3. 使用 `stapler` 附加公证凭证，执行 `spctl` 和断网启动验证。

签名凭据和公证凭据只能存放在 GitHub Actions Secrets 或受控签名环境。
