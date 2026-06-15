"""
Marvis OCR 图片文字识别与搜索。

可导入使用：
    from marvis.core.ocr import ocr_image, scan_and_ocr, search_by_text, check_tesseract
"""

import os
import shutil
from typing import Optional, Tuple


def check_tesseract() -> bool:
    """检查 Tesseract 是否已安装"""
    return shutil.which("tesseract") is not None


def ocr_image(
    image_path: str, lang: str = "chi_sim+eng"
) -> Tuple[Optional[str], Optional[str]]:
    """对单张图片进行 OCR，返回 (文字, 错误信息)"""
    if not check_tesseract():
        return None, "Tesseract 未安装。安装: winget install UB-Mannheim.TesseractOCR"

    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip(), None
    except ImportError as e:
        return None, f"缺少依赖: {e}。安装: pip install pytesseract Pillow"
    except Exception as e:
        return None, f"OCR 失败: {e}"


def scan_and_ocr(
    root: str,
    ext: Optional[str] = None,
    lang: str = "chi_sim+eng",
    max_files: int = 50,
) -> list[dict]:
    """扫描目录下所有图片并执行 OCR，返回结果列表"""
    image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
    if ext:
        image_exts = {ext} & image_exts

    skip_dirs = {".git", "node_modules", "__pycache__", ".BIN", "System Volume Information"}

    results = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in image_exts:
                full = os.path.join(dirpath, f)
                text, error = ocr_image(full, lang)
                results.append({
                    "path": os.path.abspath(full),
                    "name": f,
                    "text": text or "",
                    "error": error,
                })
                count += 1
                if count >= max_files:
                    return results
    return results


def search_by_text(results: list[dict], keyword: str) -> list[dict]:
    """在 OCR 结果中按关键词搜索"""
    matches = []
    kw = keyword.lower()
    for r in results:
        if kw in r["text"].lower():
            # 查找匹配行
            match_lines = [
                line.strip() for line in r["text"].split("\n")
                if kw in line.lower()
            ]
            matches.append({**r, "match_lines": match_lines})
    return matches


def ocr_batch(
    paths: list[str], lang: str = "chi_sim+eng"
) -> list[dict]:
    """批量 OCR 指定图片列表"""
    results = []
    for path in paths:
        text, error = ocr_image(path, lang)
        results.append({
            "path": os.path.abspath(path),
            "name": os.path.basename(path),
            "text": text or "",
            "error": error,
        })
    return results
