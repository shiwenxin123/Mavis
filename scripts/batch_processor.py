#!/usr/bin/env python3
"""Marvis 批量文件处理 - 图片压缩/水印、PDF合并拆分、编码转换等"""

import argparse
import json
import os
import sys
from datetime import datetime


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def batch_rename(root, pattern, dry_run=True, ext=None):
    """批量重命名文件"""
    results = []
    image_exts = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
    doc_exts = {'.pdf', '.docx', '.doc', '.txt', '.md'}
    
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            if not os.path.isfile(full):
                continue
            
            name, fext = os.path.splitext(f)
            stat = os.stat(full)
            mtime = datetime.fromtimestamp(stat.st_mtime)
            
            # 根据模式生成新名
            if pattern == "date-prefix":
                new_name = f"{mtime.strftime('%Y%m%d')}_{name}{fext}"
            elif pattern == "lowercase":
                new_name = f.lower()
            elif pattern == "sequential":
                results_count = len(results)
                new_name = f"{results_count + 1:04d}{fext}"
            elif pattern == "clean":
                import re
                clean = re.sub(r'[^\w\u4e00-\u9fff.\-]', '_', name)
                clean = re.sub(r'_+', '_', clean).strip('_')
                new_name = f"{clean}{fext}"
            else:
                continue
            
            new_path = os.path.join(dirpath, new_name)
            if os.path.abspath(full) == os.path.abspath(new_path):
                continue
            
            results.append({
                "original": f,
                "new_name": new_name,
                "path": os.path.abspath(full),
                "new_path": os.path.abspath(new_path),
            })
            
            if not dry_run:
                try:
                    os.rename(full, new_path)
                    results[-1]["status"] = "success"
                except OSError as e:
                    results[-1]["status"] = f"failed: {e}"
    
    return results


def compress_images(root, quality=85, max_size=None, ext=None, dry_run=True):
    """批量压缩图片"""
    try:
        from PIL import Image
    except ImportError:
        return {"error": "需要安装 Pillow: python -m pip install Pillow"}
    
    image_exts = {'.jpg', '.jpeg', '.png', '.webp'}
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
                
                # 调整大小
                if max_size:
                    w, h = img.size
                    if w > max_size or h > max_size:
                        ratio = min(max_size / w, max_size / h)
                        new_w, new_h = int(w * ratio), int(h * ratio)
                        img = img.resize((new_w, new_h), Image.LANCZOS)
                
                # 计算压缩后大小（模拟）
                if dry_run:
                    results.append({
                        "file": f,
                        "path": os.path.abspath(full),
                        "original_size": format_size(orig_size),
                        "quality": quality,
                        "resized": max_size is not None,
                    })
                else:
                    output = os.path.join(dirpath, f"compressed_{f}")
                    save_kwargs = {"quality": quality, "optimize": True}
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    img.save(output, **save_kwargs)
                    new_size = os.path.getsize(output)
                    results.append({
                        "file": f,
                        "original_size": format_size(orig_size),
                        "new_size": format_size(new_size),
                        "saved_pct": round((1 - new_size / orig_size) * 100, 1) if orig_size > 0 else 0,
                    })
            except Exception as e:
                results.append({"file": f, "error": str(e)})
    
    return results


def merge_pdfs(pdf_dir, output_path=None, dry_run=True):
    """合并目录下所有 PDF"""
    try:
        from pypdf import PdfMerger
    except ImportError:
        try:
            from PyPDF2 import PdfMerger
        except ImportError:
            return {"error": "需要安装 pypdf: python -m pip install pypdf"}
    
    pdf_files = []
    for f in sorted(os.listdir(pdf_dir)):
        if f.lower().endswith('.pdf'):
            pdf_files.append(os.path.join(pdf_dir, f))
    
    if not pdf_files:
        return {"error": "目录中没有 PDF 文件"}
    
    if not output_path:
        output_path = os.path.join(pdf_dir, "merged_output.pdf")
    
    if dry_run:
        return {
            "files": [os.path.basename(f) for f in pdf_files],
            "count": len(pdf_files),
            "output": output_path,
            "preview": True
        }
    
    merger = PdfMerger()
    for pdf in pdf_files:
        merger.append(pdf)
    merger.write(output_path)
    merger.close()
    
    return {"output": output_path, "count": len(pdf_files), "size": format_size(os.path.getsize(output_path))}


def detect_encoding(filepath):
    """检测文件编码"""
    try:
        import chardet
        with open(filepath, 'rb') as f:
            raw = f.read(10000)
            result = chardet.detect(raw)
        return result
    except ImportError:
        # 朴素检测
        for enc in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'big5', 'shift_jis', 'latin1']:
            try:
                with open(filepath, 'r', encoding=enc) as f:
                    f.read()
                return {"encoding": enc, "confidence": 0.7}
            except (UnicodeDecodeError, OSError):
                continue
        return {"encoding": "unknown", "confidence": 0}


def batch_convert_encoding(root, from_enc='auto', to_enc='utf-8', ext=None, dry_run=True):
    """批量转换文件编码"""
    text_exts = {'.txt', '.md', '.csv', '.json', '.xml', '.yaml', '.yml', '.ini', '.cfg', '.log'}
    if ext:
        text_exts = {ext} & text_exts
    
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {'.git', 'node_modules', '__pycache__'}]
        for f in filenames:
            if os.path.splitext(f)[1].lower() not in text_exts:
                continue
            full = os.path.join(dirpath, f)
            try:
                enc_info = detect_encoding(full)
                detected = enc_info.get('encoding', 'unknown')
                
                if from_enc == 'auto':
                    src_enc = detected
                else:
                    src_enc = from_enc
                
                if src_enc.lower() == to_enc.lower():
                    continue
                
                results.append({
                    "file": os.path.relpath(full, root),
                    "detected": detected,
                    "convert": f"{src_enc} → {to_enc}",
                    "path": os.path.abspath(full),
                })
                
                if not dry_run:
                    with open(full, 'r', encoding=src_enc, errors='ignore') as fh:
                        content = fh.read()
                    with open(full, 'w', encoding=to_enc) as fh:
                        fh.write(content)
                    results[-1]["status"] = "done"
            except Exception as e:
                results.append({"file": f, "error": str(e)})
    
    return results


def extract_archives(root, dry_run=True):
    """批量解压压缩包"""
    archive_exts = {'.zip'}
    results = []
    
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            ext = os.path.splitext(f)[1].lower()
            if ext not in archive_exts:
                continue
            full = os.path.join(dirpath, f)
            extract_dir = os.path.join(dirpath, os.path.splitext(f)[0])
            
            results.append({
                "archive": f,
                "path": os.path.abspath(full),
                "extract_to": os.path.abspath(extract_dir),
            })
            
            if not dry_run:
                try:
                    import zipfile
                    with zipfile.ZipFile(full, 'r') as zf:
                        zf.extractall(extract_dir)
                    results[-1]["status"] = "done"
                    results[-1]["file_count"] = len(zf.namelist())
                except Exception as e:
                    results[-1]["status"] = f"failed: {e}"
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Marvis 批量文件处理")
    parser.add_argument("root", help="处理根目录")
    parser.add_argument("--action", choices=[
        "rename", "compress-images", "merge-pdf", "convert-encoding", "extract"
    ], required=True, help="操作类型")
    parser.add_argument("--pattern", choices=["date-prefix", "lowercase", "sequential", "clean"], 
                        default="date-prefix", help="重命名模式")
    parser.add_argument("--quality", type=int, default=85, help="图片压缩质量 (1-100)")
    parser.add_argument("--max-size", type=int, help="图片最大边长 (像素)")
    parser.add_argument("--from-enc", default="auto", help="源编码")
    parser.add_argument("--to-enc", default="utf-8", help="目标编码")
    parser.add_argument("--ext", "-e", help="文件扩展名过滤")
    parser.add_argument("--output", "-o", help="输出路径")
    parser.add_argument("--execute", action="store_true", help="实际执行（默认预览模式）")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    dry_run = not args.execute

    if not os.path.isdir(args.root):
        print(f"错误: 目录不存在 - {args.root}", file=sys.stderr)
        sys.exit(1)

    if args.action == "rename":
        results = batch_rename(args.root, args.pattern, dry_run, args.ext)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            mode = "预览" if dry_run else "执行"
            print(f"批量重命名 ({mode}): {len(results)} 个文件\n")
            for r in results[:20]:
                print(f"  {r['original']} → {r['new_name']}")
            if len(results) > 20:
                print(f"  ... 还有 {len(results) - 20} 个文件")
            if dry_run:
                print(f"\n⚠️ 预览模式，未实际执行。加 --execute 参数执行。")

    elif args.action == "compress-images":
        results = compress_images(args.root, args.quality, args.max_size, args.ext, dry_run)
        if isinstance(results, dict) and "error" in results:
            print(f"错误: {results['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            mode = "预览" if dry_run else "执行"
            print(f"图片压缩 ({mode}): {len(results)} 张图片, quality={args.quality}\n")
            for r in results[:15]:
                if "error" in r:
                    print(f"  ❌ {r['file']}: {r['error']}")
                else:
                    print(f"  📷 {r['file']} ({r['original_size']})")
            if dry_run:
                print(f"\n⚠️ 预览模式，未实际执行。加 --execute 参数执行。")

    elif args.action == "merge-pdf":
        results = merge_pdfs(args.root, args.output, dry_run)
        if isinstance(results, dict) and "error" in results:
            print(f"错误: {results['error']}", file=sys.stderr)
            sys.exit(1)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            mode = "预览" if dry_run else "执行"
            print(f"PDF 合并 ({mode}): {results['count']} 个文件")
            for f in results.get('files', []):
                print(f"  📄 {f}")
            print(f"  输出: {results.get('output', 'N/A')}")

    elif args.action == "convert-encoding":
        results = batch_convert_encoding(args.root, args.from_enc, args.to_enc, args.ext, dry_run)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            mode = "预览" if dry_run else "执行"
            print(f"编码转换 ({mode}): {len(results)} 个文件\n")
            for r in results[:20]:
                if "error" in r:
                    print(f"  ❌ {r['file']}: {r['error']}")
                else:
                    print(f"  {r['file']}: {r['convert']}")
            if dry_run:
                print(f"\n⚠️ 预览模式，未实际执行。加 --execute 参数执行。")

    elif args.action == "extract":
        results = extract_archives(args.root, dry_run)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            mode = "预览" if dry_run else "执行"
            print(f"批量解压 ({mode}): {len(results)} 个压缩包\n")
            for r in results[:20]:
                status = r.get("status", "pending")
                icon = "✅" if status == "done" else "📦"
                print(f"  {icon} {r['archive']} → {os.path.basename(r['extract_to'])}")
            if dry_run:
                print(f"\n⚠️ 预览模式，未实际执行。加 --execute 参数执行。")


if __name__ == "__main__":
    main()