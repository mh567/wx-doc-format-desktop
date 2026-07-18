# WX 文档格式桌面版

这是一个纯离线的 WX 文档格式转换程序。文档在当前电脑上完成解析、规范化、模板渲染和审计，运行时不访问外网。

## 首发平台

- macOS Apple Silicon arm64
- Windows 10/11 x86_64
- 银河麒麟 V10 x86_64
- 银河麒麟 V10 arm64

## 使用

发布包用户双击启动程序，浏览器会自动打开本地操作页面。选择或拖放 DOCX、Markdown 文件即可批量转换。

源码运行：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
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

## 架构边界

`wxdoc_core` 只包含确定性规则。引擎通过 `tools/sync_upstream.py` 从 `wx-doc-format-skill` 的指定版本允许列表导出。应用不包含 LLM、Agent、API Key、远程更新和命令桥接。

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

上游同步：

```bash
python tools/sync_upstream.py --source /path/to/wx-doc-format-skill
pytest
```

## 许可

程序代码按 Apache-2.0 许可证发布。内置模板的资产许可见 `src/wxdoc_desktop/assets/LICENSE`。
