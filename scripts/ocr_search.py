#!/usr/bin/env python3
"""Marvis OCR 图片搜索 - 提取图片中的文字"""

import argparse
import json
import os
import sys
from pathlib import Path


def check_tesseract():
    """检查 Tesseract 是否安装"""
    import shutil
    return shutil.which('tesseract') is not None


def ocr_image(image_path, lang='chi_sim+eng'):
    """对单个图片进行 OCR"""
    if not check_tesseract():
        return None, "Tesseract 未安装。安装方式: winget install UB-Mannheim.TesseractOCR"

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


def scan_and_ocr(root, ext=None, lang='chi_sim+eng', max_files=50):
    """扫描目录下所有图片并执行 OCR"""
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    if ext:
        image_exts = {ext} & image_exts
    
    results = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if any(skip in dirpath for skip in {'.git', 'node_modules', '__pycache__', '.BIN'}):
            continue
        for f in filenames:
            if os.path.splitext(f)[1].lower() in image_exts:
                full = os.path.join(dirpath, f)
                text, error = ocr_image(full, lang)
                results.append({
                    'path': os.path.abspath(full),
                    'name': f,
                    'text': text or '',
                    'error': error,
                })
                count += 1
                if count >= max_files:
                    return results
    return results


def search_by_text(results, keyword):
    """在 OCR 结果中搜索关键词"""
    matches = []
    for r in results:
        if keyword.lower() in r['text'].lower():
            matches.append(r)
    return matches


def main():
    parser = argparse.ArgumentParser(description='Marvis OCR 图片搜索')
    parser.add_argument('root', help='图片目录')
    parser.add_argument('--action', choices=['scan', 'search', 'single'], default='scan', help='操作类型')
    parser.add_argument('--image', help='单张图片路径 (single 模式)')
    parser.add_argument('--keyword', '-k', help='搜索关键词 (search 模式)')
    parser.add_argument('--ext', '-e', help='图片扩展名过滤')
    parser.add_argument('--lang', default='chi_sim+eng', help='OCR 语言 (默认中英文)')
    parser.add_argument('--max-files', type=int, default=50, help='最大处理文件数')
    parser.add_argument('--json', action='store_true', help='JSON 格式输出')

    args = parser.parse_args()

    if args.action == 'single':
        if not args.image:
            print("错误: single 模式需要 --image 参数", file=sys.stderr)
            sys.exit(1)
        text, error = ocr_image(args.image, args.lang)
        if error:
            print(f"错误: {error}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps({'path': args.image, 'text': text}, ensure_ascii=False, indent=2))
        else:
            print(text)

    elif args.action == 'scan':
        results = scan_and_ocr(args.root, args.ext, args.lang, args.max_files)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for r in results:
                if r['text']:
                    preview = r['text'][:200]
                    print(f"[{r['name']}]")
                    print(f"  {preview}...")
                    print()

    elif args.action == 'search':
        if not args.keyword:
            print("错误: search 模式需要 --keyword 参数", file=sys.stderr)
            sys.exit(1)
        results = scan_and_ocr(args.root, args.ext, args.lang, args.max_files)
        matches = search_by_text(results, args.keyword)
        if args.json:
            print(json.dumps(matches, ensure_ascii=False, indent=2))
        else:
            if not matches:
                print("未找到包含关键词的图片。")
            else:
                print(f"找到 {len(matches)} 张包含 '{args.keyword}' 的图片:\n")
                for m in matches:
                    print(f"  {m['path']}")
                    # 找到包含关键词的行
                    for line in m['text'].split('\n'):
                        if args.keyword.lower() in line.lower():
                            print(f"    匹配: {line.strip()[:200]}")
                    print()


if __name__ == '__main__':
    main()
