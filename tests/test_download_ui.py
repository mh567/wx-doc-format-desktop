from wxdoc_desktop.resources import static_text


def test_ui_uses_browser_downloads_without_result_directory_controls():
    app = static_text("app.js")
    html = static_text("index.html")
    combined = app + html

    for removed in (
        "resultDirectory",
        "openResultDirectory",
        "changeResultDirectory",
        "openDirectoryButton",
        "changeDirectoryButton",
        "打开结果目录",
        "打开文件夹",
        "更改位置",
        "结果目录",
    ):
        assert removed not in combined
    assert "downloads.document" in app
    assert "下载文档" in app
    assert "查看报告" in app
