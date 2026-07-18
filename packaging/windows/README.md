# Windows 发布

1. 在 Windows x86_64 runner 上执行 `python packaging/build.py`。
2. 对 `WXDocFormat.exe` 和安装包执行 Authenticode 签名。
3. 生成便携 ZIP，计算 SHA-256，在 Windows 10/11 断网环境启动并转换样本。

符合条件的开源项目可评估 SignPath Foundation 签名服务。
