import os
import json
import shutil
import re
from pathlib import Path
from tqdm import tqdm

# ========== 配置 ==========
SOURCE_DIR = Path("www/data_bak")
OUTPUT_DIR = Path("www/data")
TRANSLATION_FILE = Path("translation_strings_cn.json")  # 翻译后的结果（必须和原提取顺序一致）
JP_REGEX = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]+')

# ========== 读取翻译结果 ==========
def load_translations() -> list:
    if not TRANSLATION_FILE.exists():
        raise FileNotFoundError(f"未找到翻译文件: {TRANSLATION_FILE}")
    with open(TRANSLATION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ========== 写回函数 ==========
def write_back_translations(obj, translations, idx_ptr, key_path=None) -> object:
    """递归地将翻译结果写回原结构，key_path 是用于追踪键路径的列表"""
    if key_path is None:
        key_path = []

    if isinstance(obj, dict):
        return {k: write_back_translations(v, translations, idx_ptr, key_path + [k]) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [write_back_translations(item, translations, idx_ptr, key_path) for item in obj]
    elif isinstance(obj, str):
        if JP_REGEX.search(obj):  # 是待翻译的字符串
            # 如果当前键路径中包含 "image"，则跳过该字符串
            if "image" in key_path:
                idx_ptr[0] += 1
                print(f"跳过替换 image 字段: {obj}")
                return obj
            
            if idx_ptr[0] >= len(translations):
                raise IndexError("翻译结果数量不足，无法匹配所有原始字符串。")
            
            translated = translations[idx_ptr[0]]
            idx_ptr[0] += 1
            return translated
        else:
            return obj
    else:
        return obj

# ========== 替换特定文件 ==========
def restore_original_files():
    """用源目录的CommonEvents.json和Tilesets.json替换输出目录的文件"""
    files_to_restore = ["CommonEvents.json", "Tilesets.json"]
    
    for file_name in files_to_restore:
        source_file = SOURCE_DIR / file_name
        target_file = OUTPUT_DIR / file_name
        
        if not source_file.exists():
            print(f"警告: 源文件 {source_file} 不存在，跳过替换")
            continue
            
        try:
            shutil.copy2(source_file, target_file)
            print(f"已恢复原始文件: {file_name}")
        except Exception as e:
            print(f"恢复文件 {file_name} 时出错: {e}")

# ========== 主处理流程 ==========
def restore_translations():
    translations = load_translations()
    idx_ptr = [0]  # 用列表包装以支持引用传递

    OUTPUT_DIR.mkdir(exist_ok=True)

    json_files = list(SOURCE_DIR.glob("*.json"))
    for file_path in tqdm(json_files, desc="写回中"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            
            updated_content = write_back_translations(content, translations, idx_ptr)

            output_file = OUTPUT_DIR / file_path.name
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(updated_content, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"[错误] 写入文件 {file_path}: {e}")

    print(f"\n已完成写回，共使用翻译条数: {idx_ptr[0]}")
    if idx_ptr[0] < len(translations):
        print(f"警告: 翻译结果还有剩余 {len(translations) - idx_ptr[0]} 条未使用")
    
    # 恢复特定原始文件
    restore_original_files()

# ========== 启动 ==========
def main():
    restore_translations()

if __name__ == "__main__":
    main()