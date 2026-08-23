from pathlib import Path

import pytest

from wxdoc_desktop.service import ConversionError, validate_input


def test_markdown_extension_is_rejected(tmp_path: Path):
    source = tmp_path / "source.markdown"
    source.write_text("# 标题\n", encoding="utf-8")

    with pytest.raises(ConversionError, match=r"\.docx 和 \.md"):
        validate_input(source)
