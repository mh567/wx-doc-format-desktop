# Magic Format

Magic Format 用于在本机完成 DOCX、Markdown 文档的解析、规范化、模板渲染和审计。

## 首发平台

- macOS Apple Silicon arm64
- 银河麒麟 V10 arm64

## 使用

从 [GitHub Releases](https://github.com/mh567/wx-doc-format-desktop/releases) 下载对应系统的发布包。页面顶部可在「转换」与「审查」之间切换。转换页选择或拖放 `.docx`、`.md` 文件即可批量转换，完成后从页面下载排版文档和复核报告。审查页上传一个 `.docx`，按模板打分并给出分维度得分、问题清单与整改建议。

macOS 用户解压后打开 `MagicFormat.app`。银河麒麟用户进入解压后的 `MagicFormat-<版本号>` 目录，双击 `MagicFormat` 即可运行，也可以双击 `MagicFormat.desktop`，或在终端执行 `./start.sh`。目录中的 `双击 MagicFormat 运行.txt` 是随包提供的启动提示文件。详细的麒麟运行和构建说明见 [`packaging/kylin/README.md`](packaging/kylin/README.md)。

## 源码运行

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
export MAGIC_FORMAT_SKILL_ROOT=/path/to/ascii/compiled-skill
wx-doc-format
```

`MAGIC_FORMAT_SKILL_ROOT` 应指向与 `VERSION` 一致的已编译 Skill 目录。运行时目录和模板路径建议使用不含中文的路径，桌面发布包已经将传给原生运行时的输入、输出和报告路径统一放在 ASCII 临时目录中。

## CLI 转换

```bash
wx-doc-format convert source.docx
wx-doc-format convert one.docx two.md --output-dir output
wx-doc-format env --output environment-report.json
```

## CLI 审查

审查只接受 `.docx`，输出百分制评分与整改报告：

```bash
wx-doc-format review source.docx
wx-doc-format review source.docx --report-dir reports --json
```

## 输出

每个转换任务生成：

- `原文件名_WX格式.docx`
- `原文件名_WX格式_报告.html`
- `原文件名_WX格式_报告.json`

报告分为已完成、已完成且建议复核、转换失败三类状态。

每个审查任务生成：

- `原文件名_审查报告.json`（评分、分维度得分、问题清单与整改建议）
- `原文件名_审查报告.md`
- `原文件名_审查报告.html`

## 已知边界

- 文本框、形状、SmartArt、批注和修订记录可能需要人工复核。
- Markdown 中的本地图片不会自动嵌入。
- 目录域、页码和复杂分节需在 WPS 或 Word 中更新后查看。
