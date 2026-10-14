from pathlib import Path


CATEGORIES: dict[str, frozenset[str]] = {
    "图片": frozenset(".png .jpg .jpeg .gif .webp .bmp .tif .tiff .svg .heic .avif .ico".split()),
    "文档": frozenset(".pdf .doc .docx .xls .xlsx .ppt .pptx .txt .md .rtf .odt .ods .csv .epub".split()),
    "视频": frozenset(".mp4 .mov .mkv .avi .webm .wmv .m4v .flv".split()),
    "音频": frozenset(".mp3 .wav .flac .aac .m4a .ogg .opus .aiff .wma".split()),
    "压缩包": frozenset(".zip .7z .rar .tar .gz .bz2 .xz .zst .tgz".split()),
    "代码": frozenset(".py .js .ts .tsx .jsx .html .css .scss .json .yaml .yml .toml .xml .sql .rs .go .java .c .cpp .h .sh .ps1".split()),
    "安装包": frozenset(".exe .msi .msix .appx .iso".split()),
}


def classify(path: Path) -> str:
    suffix = path.suffix.casefold()
    return next((name for name, extensions in CATEGORIES.items() if suffix in extensions), "其他")
