# macOS 发布

1. 在 Apple Silicon GitHub runner 上执行 `python packaging/build.py`。
2. 对 `.app` 内部所有 Mach-O 文件执行 Developer ID 签名。
3. 对最外层 `.app` 开启 Hardened Runtime 并签名。
4. 生成 DMG，通过 `notarytool` 提交 Apple 公证。
5. 使用 `stapler` 附加凭证，执行 `spctl` 和断网启动验证。

签名凭据和公证凭据只能存放在 GitHub Actions Secrets 或受控签名环境。
