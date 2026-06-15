#!/usr/bin/env python3
"""Marvis AI 图库与文档库 - 个人知识库管理"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

DB_DIR = os.path.join(os.path.expanduser("~"), ".marvis", "knowledge")


def ensure_db_dir():
    os.makedirs(DB_DIR, exist_ok=True)


def get_exif_data(image_path):
    """提取图片 EXIF 信息"""
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
        
        img = Image.open(image_path)
        exif_data = img._getexif() if hasattr(img, '_getexif') else None
        
        if not exif_data:
            return {"has_exif": False, "size": img.size, "format": img.format}
        
        result = {"has_exif": True, "size": img.size, "format": img.format}
        
        for tag_id, value in exif_data.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "DateTime" or tag == "DateTimeOriginal":
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
                    gps[gps_tag] = value[gps_tag_id]
                if "GPSLatitude" in gps and "GPSLongitude" in gps:
                    lat = convert_gps(gps["GPSLatitude"], gps.get("GPSLatitudeRef", "N"))
                    lon = convert_gps(gps["GPSLongitude"], gps.get("GPSLongitudeRef", "E"))
                    result["gps"] = {"latitude": lat, "longitude": lon}
        
        return result
    except ImportError:
        return {"has_exif": False, "error": "Pillow 未安装"}
    except Exception as e:
        return {"has_exif": False, "error": str(e)}


def convert_gps(coord, ref):
    """GPS 坐标转换"""
    d, m, s = coord
    decimal = float(d) + float(m) / 60 + float(s) / 3600
    if ref in ("S", "W"):
        decimal = -decimal
    return round(decimal, 6)


def classify_image(filepath, exif):
    """根据文件名和 EXIF 分类图片"""
    name = os.path.basename(filepath).lower()
    ext = os.path.splitext(name)[1]
    categories = []
    
    # 按内容主题分类
    chat_keywords = ['img_', 'mmexport', 'wx_', 'wechat', 'screenshot', '截图', 'screen']
    doc_keywords = ['scan', '扫描', 'id_', '证件', 'passport', 'visa']
    photo_keywords = ['dsc_', 'img_', 'dscf', 'photo', 'dcim']
    
    if any(k in name for k in chat_keywords):
        categories.append("聊天记录/截图")
    elif any(k in name for k in doc_keywords):
        categories.append("证件/扫描件")
    elif any(k in name for k in photo_keywords) or exif.get("has_exif"):
        categories.append("照片")
    else:
        categories.append("其他图片")
    
    # 按时间分类
    if exif.get("date_taken"):
        try:
            dt_str = exif["date_taken"]
            dt = datetime.strptime(dt_str[:10], "%Y:%m:%d")
            categories.append(f"年月:{dt.year}/{dt.month:02d}")
        except (ValueError, IndexError):
            pass
    
    # 按地点分类
    if exif.get("gps"):
        categories.append("有GPS定位")
    
    # 按相机分类
    if exif.get("camera"):
        categories.append(f"相机:{exif['camera']}")
    
    return categories


def build_image_gallery(root, max_images=500):
    """扫描目录构建 AI 图库索引"""
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic'}
    gallery = []
    count = 0
    
    for dirpath, dirnames, filenames in os.walk(root):
        if any(skip in dirpath for skip in {'.git', 'node_modules', '$RECYCLE.BIN', 'System Volume Information'}):
            continue
        for f in filenames:
            if os.path.splitext(f)[1].lower() in image_exts:
                full = os.path.join(dirpath, f)
                try:
                    stat = os.stat(full)
                    exif = get_exif_data(full)
                    categories = classify_image(full, exif)
                    
                    entry = {
                        "path": os.path.abspath(full),
                        "name": f,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
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


def build_doc_library(root, max_files=500):
    """扫描目录构建文档库索引"""
    doc_exts = {'.pdf', '.doc', '.docx', '.txt', '.md', '.ppt', '.pptx', '.xls', '.xlsx', '.csv'}
    library = []
    count = 0
    
    for dirpath, dirnames, filenames in os.walk(root):
        if any(skip in dirpath for skip in {'.git', 'node_modules', '__pycache__', '$RECYCLE.BIN'}):
            continue
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext in doc_exts:
                full = os.path.join(dirpath, f)
                try:
                    stat = os.stat(full)
                    entry = {
                        "path": os.path.abspath(full),
                        "name": f,
                        "ext": ext,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "type": classify_doc(ext),
                        "tags": auto_tag(f, ext),
                    }
                    library.append(entry)
                    count += 1
                    if count >= max_files:
                        return library
                except (PermissionError, OSError):
                    continue
    return library


def classify_doc(ext):
    """分类文档类型"""
    doc_types = {
        '.pdf': 'PDF文档', '.doc': 'Word文档', '.docx': 'Word文档',
        '.txt': '纯文本', '.md': 'Markdown', '.ppt': 'PPT演示',
        '.pptx': 'PPT演示', '.xls': 'Excel表格', '.xlsx': 'Excel表格', '.csv': 'CSV数据'
    }
    return doc_types.get(ext, '其他文档')


def auto_tag(filename, ext):
    """自动为文档打标签"""
    tags = []
    name = filename.lower()
    
    # 类型标签
    if ext in ('.pdf', '.doc', '.docx'):
        tags.append('文档')
    elif ext in ('.xls', '.xlsx', '.csv'):
        tags.append('数据')
    elif ext in ('.ppt', '.pptx'):
        tags.append('演示')
    elif ext == '.md':
        tags.append('笔记')
    
    # 内容标签（基于文件名关键词）
    tag_map = {
        '合同': ['合同', '法律'], '报告': ['报告'], '方案': ['方案'],
        '简历': ['求职', '简历'], '证书': ['证书'], '论文': ['学术', '论文'],
        '文献': ['学术', '文献'], '发票': ['财务', '发票'], '账单': ['财务'],
        '会议': ['会议'], '培训': ['学习'], '规划': ['规划'],
        '招标': ['招标'], '投标': ['招标'],
    }
    for keyword, tag_list in tag_map.items():
        if keyword in name:
            tags.extend(tag_list)
    
    return list(set(tags))


def search_gallery(gallery, keyword=None, category=None, date_from=None, date_to=None, has_gps=None):
    """搜索图库"""
    results = gallery
    if keyword:
        kw = keyword.lower()
        results = [g for g in results if kw in g['name'].lower() or 
                   any(kw in c.lower() for c in g['categories'])]
    if category:
        cat = category.lower()
        results = [g for g in results if any(cat in c.lower() for c in g['categories'])]
    if date_from:
        results = [g for g in results if g['modified'] >= date_from]
    if date_to:
        results = [g for g in results if g['modified'] <= date_to]
    if has_gps is not None:
        results = [g for g in results if g.get('exif', {}).get('gps') is not None == has_gps]
    return results


def search_library(library, keyword=None, doc_type=None, tag=None, ext=None, date_from=None, date_to=None):
    """搜索文档库"""
    results = library
    if keyword:
        kw = keyword.lower()
        results = [d for d in results if kw in d['name'].lower()]
    if doc_type:
        results = [d for d in results if d['type'] == doc_type]
    if tag:
        t = tag.lower()
        results = [d for d in results if any(t in tg.lower() for tg in d['tags'])]
    if ext:
        results = [d for d in results if d['ext'] == ext.lower()]
    if date_from:
        results = [d for d in results if d['modified'] >= date_from]
    if date_to:
        results = [d for d in results if d['modified'] <= date_to]
    return results


def gallery_stats(gallery):
    """图库统计"""
    stats = {"total": len(gallery), "by_category": {}, "by_month": {}, "with_gps": 0}
    for g in gallery:
        for cat in g['categories']:
            stats['by_category'][cat] = stats['by_category'].get(cat, 0) + 1
        month = g['modified'][:7]
        stats['by_month'][month] = stats['by_month'].get(month, 0) + 1
        if g.get('exif', {}).get('gps'):
            stats['with_gps'] += 1
    return stats


def library_stats(library):
    """文档库统计"""
    stats = {"total": len(library), "by_type": {}, "by_tag": {}, "by_month": {}}
    for d in library:
        stats['by_type'][d['type']] = stats['by_type'].get(d['type'], 0) + 1
        for t in d['tags']:
            stats['by_tag'][t] = stats['by_tag'].get(t, 0) + 1
        month = d['modified'][:7]
        stats['by_month'][month] = stats['by_month'].get(month, 0) + 1
    return stats


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def main():
    parser = argparse.ArgumentParser(description="Marvis AI 图库与文档库")
    parser.add_argument("root", help="扫描根目录")
    parser.add_argument("--mode", choices=["image-gallery", "doc-library"], required=True, help="库类型")
    parser.add_argument("--action", choices=["build", "search", "stats"], default="build", help="操作类型")
    parser.add_argument("--keyword", "-k", help="搜索关键词")
    parser.add_argument("--category", help="图片分类过滤")
    parser.add_argument("--tag", help="文档标签过滤")
    parser.add_argument("--type", help="文档类型过滤")
    parser.add_argument("--ext", "-e", help="扩展名过滤")
    parser.add_argument("--date-from", help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="截止日期 (YYYY-MM-DD)")
    parser.add_argument("--max", type=int, default=500, help="最大文件数")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print(f"错误: 目录不存在 - {args.root}", file=sys.stderr)
        sys.exit(1)

    if args.mode == "image-gallery":
        gallery = build_image_gallery(args.root, args.max)
        
        if args.action == "stats":
            stats = gallery_stats(gallery)
            if args.json:
                print(json.dumps(stats, ensure_ascii=False, indent=2))
            else:
                print(f"图库统计: {stats['total']} 张图片")
                print(f"  有 GPS 定位: {stats['with_gps']} 张\n")
                print("按分类:")
                for cat, cnt in sorted(stats['by_category'].items(), key=lambda x: -x[1])[:10]:
                    print(f"  {cat}: {cnt}")
                print("\n按月份:")
                for month, cnt in sorted(stats['by_month'].items(), reverse=True)[:12]:
                    print(f"  {month}: {cnt}")
        
        elif args.action == "search":
            results = search_gallery(gallery, args.keyword, args.category, 
                                    args.date_from, args.date_to)
            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
            else:
                if not results:
                    print("未找到匹配图片。")
                else:
                    print(f"找到 {len(results)} 张图片:\n")
                    for r in results[:20]:
                        cats = ', '.join(r['categories'])
                        print(f"  {r['path']}")
                        print(f"    分类: {cats} | 修改: {r['modified']}")
        
        else:  # build
            if args.json:
                print(json.dumps(gallery, ensure_ascii=False, indent=2, default=str))
            else:
                print(f"扫描完成: {len(gallery)} 张图片\n")
                for g in gallery[:15]:
                    cats = ', '.join(g['categories'])
                    print(f"  {g['name']}")
                    print(f"    路径: {g['path']}")
                    print(f"    分类: {cats}")
                    if g['exif'].get('camera'):
                        print(f"    相机: {g['exif']['camera']}")
                    if g['exif'].get('gps'):
                        print(f"    GPS: {g['exif']['gps']}")
                    print()
                if len(gallery) > 15:
                    print(f"  ... 还有 {len(gallery) - 15} 张图片")

    elif args.mode == "doc-library":
        library = build_doc_library(args.root, args.max)
        
        if args.action == "stats":
            stats = library_stats(library)
            if args.json:
                print(json.dumps(stats, ensure_ascii=False, indent=2))
            else:
                print(f"文档库统计: {stats['total']} 个文件\n")
                print("按类型:")
                for t, cnt in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
                    print(f"  {t}: {cnt}")
                print("\n按标签:")
                for t, cnt in sorted(stats['by_tag'].items(), key=lambda x: -x[1])[:10]:
                    print(f"  {t}: {cnt}")
        
        elif args.action == "search":
            results = search_library(library, args.keyword, args.type, 
                                    args.tag, args.ext, args.date_from, args.date_to)
            if args.json:
                print(json.dumps(results, ensure_ascii=False, indent=2))
            else:
                if not results:
                    print("未找到匹配文档。")
                else:
                    print(f"找到 {len(results)} 个文档:\n")
                    for r in results[:20]:
                        tags = ', '.join(r['tags']) if r['tags'] else '无标签'
                        print(f"  {r['path']}")
                        print(f"    类型: {r['type']} | 标签: {tags} | 修改: {r['modified']}")
        
        else:  # build
            if args.json:
                print(json.dumps(library, ensure_ascii=False, indent=2))
            else:
                print(f"扫描完成: {len(library)} 个文档\n")
                for d in library[:15]:
                    tags = ', '.join(d['tags']) if d['tags'] else '无标签'
                    print(f"  {d['name']}")
                    print(f"    路径: {d['path']}")
                    print(f"    类型: {d['type']} | 标签: {tags}")
                    print()
                if len(library) > 15:
                    print(f"  ... 还有 {len(library) - 15} 个文档")


if __name__ == "__main__":
    main()