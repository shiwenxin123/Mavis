"""
Marvis 批量文件处理 — 重命名、图片压缩、PDF合并、编码转换、批量解压。

可导入使用：
    from marvis.core.batch_processor import batch_rename, compress_images, merge_pdfs
"""

import os
import re
import subprocess
import tempfile
import zipfile
from datetime import datetime
from typing import Optional

from marvis.utils.fs import format_size


def batch_rename(
    root: str,
    pattern: str = "date-prefix",
    dry_run: bool = True,
    ext: Optional[str] = None,
) -> list[dict]:
    """批量重命名文件。模式: date-prefix, lowercase, sequential, clean"""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            if not os.path.isfile(full):
                continue

            name, fext = os.path.splitext(f)
            try:
                st = os.stat(full)
                mtime = datetime.fromtimestamp(st.st_mtime)
            except OSError:
                continue

            if pattern == "date-prefix":
                new_name = f"{mtime.strftime('%Y%m%d')}_{name}{fext}"
            elif pattern == "lowercase":
                new_name = f.lower()
            elif pattern == "sequential":
                new_name = f"{len(results) + 1:04d}{fext}"
            elif pattern == "clean":
                clean = re.sub(r"[^\w\u4e00-\u9fff.\-]", "_", name)
                clean = re.sub(r"_+", "_", clean).strip("_")
                new_name = f"{clean}{fext}"
            else:
                continue

            new_path = os.path.join(dirpath, new_name)
            if os.path.abspath(full) == os.path.abspath(new_path):
                continue

            entry = {
                "original": f, "new_name": new_name,
                "path": os.path.abspath(full), "new_path": os.path.abspath(new_path),
            }

            if not dry_run:
                try:
                    os.rename(full, new_path)
                    entry["status"] = "success"
                except OSError as e:
                    entry["status"] = f"failed: {e}"
            results.append(entry)
    return results


def compress_images(
    root: str, quality: int = 85, max_size: Optional[int] = None,
    ext: Optional[str] = None, dry_run: bool = True,
) -> list[dict]:
    """批量压缩图片"""
    try:
        from PIL import Image
    except ImportError:
        return [{"error": "需要安装 Pillow: pip install Pillow"}]

    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    if ext:
        image_exts = {ext} & image_exts

    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if os.path.splitext(f)[1].lower() not in image_exts:
                continue
            full = os.path.join(dirpath, f)
            try:
                img = Image.open(full)
                orig_size = os.path.getsize(full)
                orig_w, orig_h = img.size

                if max_size and (orig_w > max_size or orig_h > max_size):
                    ratio = min(max_size / orig_w, max_size / orig_h)
                    img = img.resize((int(orig_w * ratio), int(orig_h * ratio)), Image.LANCZOS)

                entry = {
                    "path": os.path.abspath(full), "name": f,
                    "orig_size": format_size(orig_size), "orig_dims": f"{orig_w}x{orig_h}",
                }

                if not dry_run:
                    img.save(full, quality=quality, optimize=True)
                    new_size = os.path.getsize(full)
                    entry["new_size"] = format_size(new_size)
                    entry["saved_pct"] = round((1 - new_size / orig_size) * 100, 1)
                results.append(entry)
            except (PermissionError, OSError):
                continue
    return results


def merge_pdfs(root: str, output_path: str) -> dict:
    """合并目录下所有 PDF"""
    try:
        import pdfplumber
    except ImportError:
        return {"error": "需要安装 pdfplumber: pip install pdfplumber"}

    pdf_files = sorted([
        os.path.join(dirpath, f)
        for dirpath, _, filenames in os.walk(root)
        for f in filenames if f.lower().endswith(".pdf")
    ])
    if len(pdf_files) < 2:
        return {"error": f"需要至少2个PDF文件，当前找到 {len(pdf_files)} 个"}

    try:
        import pikepdf
        merged = pikepdf.new()
        for pdf_file in pdf_files:
            merged.pages.extend(pikepdf.open(pdf_file).pages)
        merged.save(output_path)
    except ImportError:
        # 回退：使用 pdfplumber 读取 + pikepdf 不可用时的说明
        return {"error": "需要安装 pikepdf: pip install pikepdf。或者使用在线工具合并。"}

    return {"output": os.path.abspath(output_path), "merged_count": len(pdf_files), "files": pdf_files}


def convert_encoding(root: str, target_encoding: str = "utf-8", dry_run: bool = True) -> list[dict]:
    """批量编码转换"""
    try:
        import chardet
    except ImportError:
        return [{"error": "需要安装 chardet: pip install chardet"}]

    text_exts = {".txt", ".csv", ".md", ".html", ".css", ".js", ".py", ".xml", ".json", ".yaml"}
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if os.path.splitext(f)[1].lower() not in text_exts:
                continue
            full = os.path.join(dirpath, f)
            try:
                with open(full, "rb") as fh:
                    raw = fh.read()
                detected = chardet.detect(raw)
                encoding = detected.get("encoding", "unknown")
                entry = {
                    "path": os.path.abspath(full), "name": f,
                    "detected_encoding": encoding, "confidence": detected.get("confidence", 0),
                }
                if not dry_run and encoding and encoding.lower() != target_encoding.lower():
                    text = raw.decode(encoding, errors="replace")
                    with open(full, "w", encoding=target_encoding, errors="replace") as fh:
                        fh.write(text)
                    entry["converted"] = True
                results.append(entry)
            except (PermissionError, OSError, UnicodeDecodeError):
                continue
    return results


def batch_extract(root: str, output_dir: Optional[str] = None) -> list[dict]:
    """批量解压 ZIP"""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if not f.lower().endswith(".zip"):
                continue
            full = os.path.join(dirpath, f)
            dest = output_dir or os.path.join(dirpath, f"_{os.path.splitext(f)[0]}")
            try:
                os.makedirs(dest, exist_ok=True)
                with zipfile.ZipFile(full, "r") as zf:
                    zf.extractall(dest)
                results.append({"archive": os.path.abspath(full), "output": dest, "status": "success"})
            except (zipfile.BadZipFile, PermissionError, OSError) as e:
                results.append({"archive": os.path.abspath(full), "status": f"failed: {e}"})
    return results
