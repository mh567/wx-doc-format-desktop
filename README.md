# Magic Format

Magic Format 用于在本机完成 DOCX、Markdown 文档的解析、规范化、模板渲染和审计。

## 首发平台

- macOS Apple Silicon arm64
- 银河麒麟 V10 arm64

## 使用

从 [GitHub Releases](https://github.com/mh567/wx-doc-format-desktop/releases) 下载对应系统的发布包。解压后启动程序，浏览器会自动打开本地操作页面。选择或拖放 `.docx`、`.md` 文件即可批量转换。结果默认保存到文稿目录下的 `Magic Format/转换结果`，可在页面中更改位置。

源码运行：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
export MAGIC_FORMAT_SKILL_ROOT=/path/to/extracted/compiled-skill
wx-doc-format
```

CLI 转换：

```bash
wx-doc-format convert source.docx
wx-doc-format convert one.docx two.md --output-dir output
wx-doc-format env --output environment-report.json
```

## 输出

每个任务生成：

- `原文件名_WX格式.docx`
- `原文件名_WX格式_报告.html`
- `原文件名_WX格式_报告.json`

报告分为已完成、已完成且建议复核、转换失败三类状态。

## 已知边界

- 文本框、形状、SmartArt、批注和修订记录可能需要人工复核。
- Markdown 中的本地图片不会自动嵌入。
- 目录域、页码和复杂分节需在 WPS 或 Word 中更新后查看。

## 开发

```bash
python -m pip install -e '.[test,build]'
pytest
python packaging/build.py
```

## 版本与同步

桌面应用嵌入 `wx-doc-format-skill` Release 中已经编译并通过 SHA256 校验的原生运行时。应用版本与 `UPSTREAM_VERSION` 保持一致。更新 Skill 后执行：

```bash
python tools/check_release.py
pytest
python packaging/build.py
```

构建命令会从 `mh567/wx-doc-format-skill` 的同版本 Release 下载当前平台离线包，核对 `SHA256SUMS.txt` 和包内 `manifest.json`，再把 `runtime/` 与模板嵌入 Desktop 程序。当前 Release 只生成已有编译运行时的 macOS ARM64 和银河麒麟 V10 ARM64 安装包。

## 许可

程序代码按 Apache-2.0 许可证发布。内置模板的资产许可见 `src/wxdoc_desktop/assets/LICENSE`。
