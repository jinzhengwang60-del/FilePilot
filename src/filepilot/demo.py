from __future__ import annotations

import base64
import io
import json
import wave
import zipfile
from pathlib import Path

from .safety import SafetyError, SafetyPolicy, absolute


def create_demo(path: Path | str) -> Path:
    root = absolute(path)
    SafetyPolicy().check_path(root)
    marker = root / ".filepilot-demo.json"
    if root.exists():
        if marker.is_file():
            return root
        raise SafetyError("演示目录已存在且不是 FilePilot 创建的目录，请选择一个新目录。")
    root.mkdir(parents=True)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=")
    wav = io.BytesIO()
    with wave.open(wav, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as package:
        package.writestr("说明.txt", "这是一份 FilePilot 演示归档，全部内容由程序生成。")
        package.writestr("sample.bin", bytes(range(256)) * 4096)
    text = ("周末旅行计划\n周六：图书馆与公园。\n周日：整理照片，做一个小项目。\n" * 100).encode("utf-8")
    files = {
        "旅行计划.txt": text,
        "旧备份/旅行计划 - 副本.txt": text,
        "临时收集/旅行计划 (2).txt": text,
        "照片/封面.png": png,
        "临时收集/封面 - 副本.png": png,
        "素材归档.zip": archive.getvalue(),
        "旧备份/素材归档 - 副本.zip": archive.getvalue(),
        "声音/安静的一秒.wav": wav.getvalue(),
        "灵感.md": "# 下一次旅行\n\n记录遇到的颜色与声音。\n".encode("utf-8"),
        "阅读清单.csv": "书名,状态\n设计心理学,在读\n小王子,读完\n".encode("utf-8"),
        "代码/hello.py": b"print('Hello, FilePilot!')\n",
        "代码/settings.json": b'{"theme": "light", "offline": true}\n',
        "待整理.dat": b"An unknown extension stays visible in the Other category.\n",
        "收据.txt": "咖啡 18 元\n书籍 42 元\n".encode("utf-8"),
        "工作/会议纪要.md": "# 会议纪要\n先做一个可以安全撤销的版本。\n".encode("utf-8"),
    }
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    marker.write_text(json.dumps({"generator": "FilePilot", "files": list(files)}, ensure_ascii=False, indent=2), encoding="utf-8")
    return root
