"""
Marvis AI 图库与文档库 — 个人知识库管理。

图库：按人像/主题/时间/地点维度管理图片。
文档库：文档索引 + 自动标签 + 检索。

可导入使用：
    from marvis.core.knowledge_base import build_image_gallery, build_doc_library, search_gallery
"""

import os
from datetime import datetime
from typing import Optional


def _get_exif_data(image_path: str) -> dict:
    """提取图片 EXIF 信息"""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS

        img = Image.open(image_path)
        exif_data = img._getexif() if hasattr(img, "_getexif") else None

        if not exif_data:
            return {"has_exif": False, "size": list(img.size), "format": img.format}

        result = {"has_exif": True, "size": list(img.size), "format": img.format}
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag in ("DateTime", "DateTimeOriginal"):
                result["date_taken"] = str(value)
            elif tag == "Model":
                result["camera"] = str(value)
            elif tag == "LensModel":
                result["lens"] = str(value)
            elif tag == "FocalLength":
                result["focal_length"] = str(value)
            elif tag == "ISOSpeedRatings":
                result["iso"] = str(value)
            elif tag == "GPSInfo":
                gps = {}
                for gps_tag_id in value:
                    gps_tag = GPSTAGS.get(gps_tag_id, gps_tag_id)
                    gps[gps_tag] = str(value[gps_tag_id])
                if "GPSLatitude" in gps and "GPSLongitude" in gps:
                    result["gps"] = {"latitude": gps.get("GPSLatitude"),
                                     "longitude": gps.get("GPSLongitude")}
        return result
    except ImportError:
        return {"has_exif": False, "error": "Pillow 未安装"}
    except Exception as e:
        return {"has_exif": False, "error": str(e)}


def _classify_image(filepath: str, exif: dict) -> list[str]:
    """根据文件名和 EXIF 分类图片"""
    name = os.path.basename(filepath).lower()
    categories = []

    chat_keywords = ["img_", "mmexport", "wx_", "wechat", "screenshot", "截图", "screen"]
    doc_keywords = ["scan", "扫描", "id_", "证件", "passport", "visa"]
    photo_keywords = ["dsc_", "dscf", "photo", "dcim"]

    if any(k in name for k in chat_keywords):
        categories.append("聊天记录/截图")
    elif any(k in name for k in doc_keywords):
        categories.append("证件/扫描件")
    elif any(k in name for k in photo_keywords) or exif.get("has_exif"):
        categories.append("照片")
    else:
        categories.append("其他图片")

    if exif.get("date_taken"):
        try:
            dt_str = exif["date_taken"]
            dt = datetime.strptime(dt_str[:10], "%Y:%m:%d")
            categories.append(f"年月:{dt.year}/{dt.month:02d}")
        except (ValueError, IndexError):
            pass

    if exif.get("gps"):
        categories.append("有GPS定位")

    if exif.get("camera"):
        categories.append(f"相机:{exif['camera']}")

    return categories


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic"}
DOC_EXTS = {".pdf", ".doc", ".docx", ".txt", ".md", ".ppt", ".pptx", ".xls", ".xlsx", ".csv"}
SKIP_DIRS = {".git", "node_modules", "$RECYCLE.BIN", "System Volume Information"}


def build_image_gallery(root: str, max_images: int = 500) -> list[dict]:
    """扫描目录构建 AI 图库索引"""
    gallery = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        if any(skip in dirpath for skip in SKIP_DIRS):
            continue
        for f in filenames:
            if os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                full = os.path.join(dirpath, f)
                try:
                    st = os.stat(full)
                    exif = _get_exif_data(full)
                    categories = _classify_image(full, exif)
                    entry = {
                        "path": os.path.abspath(full),
                        "name": f,
                        "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "categories": categories,
                        "exif": exif,
                    }
                    gallery.append(entry)
                    count += 1
                    if count >= max_images:
                        return gallery
                except (PermissionError, OSError):
                    continue
    return gallery


def build_doc_library(root: str, max_files: int = 500) -> list[dict]:
    """扫描目录构建文档库索引"""
    library = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        if any(skip in dirpath for skip in SKIP_DIRS.union({"__pycache__"})):
            continue
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in DOC_EXTS:
                full = os.path.join(dirpath, f)
                try:
                    st = os.stat(full)
                    entry = {
                        "path": os.path.abspath(full),
                        "name": f,
                        "ext": ext,
                        "size": st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        "type": _classify_doc(ext),
                        "tags": _auto_tag(f, ext),
                    }
                    library.append(entry)
                    count += 1
                    if count >= max_files:
                        return library
                except (PermissionError, OSError):
                    continue
    return library


def _classify_doc(ext: str) -> str:
    """分类文档类型"""
    doc_types = {
        ".pdf": "PDF文档", ".doc": "Word文档", ".docx": "Word文档",
        ".txt": "纯文本", ".md": "Markdown", ".ppt": "PPT演示",
        ".pptx": "PPT演示", ".xls": "Excel表格", ".xlsx": "Excel表格",
        ".csv": "CSV数据",
    }
    return doc_types.get(ext, "其他文档")


def _auto_tag(filename: str, ext: str) -> list[str]:
    """自动为文档打标签"""
    tags = []
    name = filename.lower()

    if ext in (".pdf", ".doc", ".docx"):
        tags.append("文档")
    elif ext in (".xls", ".xlsx", ".csv"):
        tags.append("数据")
    elif ext in (".ppt", ".pptx"):
        tags.append("演示")
    elif ext == ".md":
        tags.append("笔记")

    tag_map = {
        "合同": ["合同", "法律"], "报告": ["报告"], "方案": ["方案"],
        "简历": ["求职", "简历"], "证书": ["证书"], "论文": ["学术", "论文"],
        "文献": ["学术", "文献"], "发票": ["财务", "发票"], "账单": ["财务"],
        "会议": ["会议"], "培训": ["学习"], "规划": ["规划"],
        "招标": ["招标"], "投标": ["招标"],
    }
    for keyword, tag_list in tag_map.items():
        if keyword in name:
            tags.extend(tag_list)

    return list(set(tags))


def search_gallery(
    gallery: list[dict],
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    has_gps: Optional[bool] = None,
) -> list[dict]:
    """搜索图库"""
    results = gallery
    if keyword:
        kw = keyword.lower()
        results = [
            g for g in results
            if kw in g["name"].lower()
            or any(kw in c.lower() for c in g["categories"])
        ]
    if category:
        cat = category.lower()
        results = [
            g for g in results
            if any(cat in c.lower() for c in g["categories"])
        ]
    if date_from:
        results = [g for g in results if g["modified"] >= date_from]
    if date_to:
        results = [g for g in results if g["modified"] <= date_to]
    if has_gps is not None:
        results = [
            g for g in results
            if (g.get("exif", {}).get("gps") is not None) == has_gps
        ]
    return results


def search_library(
    library: list[dict],
    keyword: Optional[str] = None,
    doc_type: Optional[str] = None,
    tag: Optional[str] = None,
    ext: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """搜索文档库"""
    results = library
    if keyword:
        kw = keyword.lower()
        results = [d for d in results if kw in d["name"].lower()]
    if doc_type:
        results = [d for d in results if d["type"] == doc_type]
    if tag:
        t = tag.lower()
        results = [d for d in results if any(t in tg.lower() for tg in d["tags"])]
    if ext:
        results = [d for d in results if d["ext"] == ext.lower()]
    if date_from:
        results = [d for d in results if d["modified"] >= date_from]
    if date_to:
        results = [d for d in results if d["modified"] <= date_to]
    return results


def gallery_stats(gallery: list[dict]) -> dict:
    """图库统计"""
    stats = {"total": len(gallery), "by_category": {}, "by_month": {}, "with_gps": 0}
    for g in gallery:
        for cat in g["categories"]:
            stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
        month = g["modified"][:7]
        stats["by_month"][month] = stats["by_month"].get(month, 0) + 1
        if g.get("exif", {}).get("gps"):
            stats["with_gps"] += 1
    return stats


def library_stats(library: list[dict]) -> dict:
    """文档库统计"""
    stats = {"total": len(library), "by_type": {}, "by_tag": {}, "by_month": {}}
    for d in library:
        stats["by_type"][d["type"]] = stats["by_type"].get(d["type"], 0) + 1
        for t in d["tags"]:
            stats["by_tag"][t] = stats["by_tag"].get(t, 0) + 1
        month = d["modified"][:7]
        stats["by_month"][month] = stats["by_month"].get(month, 0) + 1
    return stats
