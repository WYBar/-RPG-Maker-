import json
from pathlib import Path
import openai
from openai import OpenAI
import os
import re
from tqdm import tqdm
import time
import math
from typing import List, Tuple, Dict, Optional
import glob

# ========== 配置 ==========
INPUT_FILE = Path("translation_strings_debug.json")
OUTPUT_DIR = Path("json_temp_debug")
BATCH_SIZE = 20   # 每批处理量
SAVE_EVERY = 3    # 每处理多少批次保存一次
MAX_RETRIES = 3    # 最大重试次数

# ========== 初始化Client ==========
client = OpenAI(api_key="<API KEY>", base_url="https://api.deepseek.com")

# ========== 正则表达式 ==========
PATTERN = re.compile(
    r"^(?P<prefix>-*[↓↑]?[　\s-]*)"
    r"(?P<text>.*?)"
    r"(?P<suffix>[　\s↑↓-]*)$"
)

def load_json(input_file: Path) -> List[dict]:
    """加载原始JSON文件"""
    with open(input_file, 'r', encoding='utf-8') as f:
        return json.load(f)

SEPARATOR = "|||"

def safe_combine_texts(texts: List[str]) -> str:
    return "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])

def safe_split_result(result: str, expected_count: int) -> List[str]:
    """
    根据编号（如 1. xxx\n2. yyy）来提取翻译结果，避免因换行错误分割。
    """
    # 匹配以数字编号开头的段落（可能跨多行）
    pattern = re.compile(r"^\d+\.\s", re.MULTILINE)
    positions = [m.start() for m in pattern.finditer(result)]

    translated = []

    for i in range(len(positions)):
        start = positions[i]
        end = positions[i + 1] if i + 1 < len(positions) else len(result)
        block = result[start:end].strip()

        # 去掉前缀编号 “1.”、“2.”等
        match = re.match(r"^\d+\.\s*(.*)", block, re.DOTALL)
        if match:
            translated.append(match.group(1).strip())
        else:
            translated.append(block.strip())

    # 校验数量并自动修复（补空或截断）
    return validate_and_fix_batch(translated, [''] * expected_count)

def extract_text_parts(texts: List[str]) -> Tuple[List[str], List[tuple]]:
    """提取需要翻译的文本部分"""
    extracted = []
    structures = []
    
    for text in texts:
        match = PATTERN.match(str(text))
        if match:
            prefix = match.group("prefix") or ""
            text_part = match.group("text") or ""
            suffix = match.group("suffix") or ""
            
            if text_part.strip() and not re.fullmatch(r"[\s　↑↓-]+", text_part):
                extracted.append(text_part)
                structures.append((prefix, suffix))
            else:
                extracted.append(text)
                structures.append(None)
        else:
            extracted.append(text)
            structures.append(None)
    
    return extracted, structures

def reconstruct_translated_texts(translated: List[str], structures: List[tuple]) -> List[str]:
    """重建翻译后的字符串"""
    reconstructed = []
    for text, structure in zip(translated, structures):
        if structure and isinstance(text, str):
            prefix, suffix = structure
            reconstructed.append(f"{prefix}{text}{suffix}")
        else:
            reconstructed.append(text)
    return reconstructed

def load_existing_result(save_count: int) -> Optional[List[str]]:
    """检查并加载已存在的翻译结果"""
    output_file = OUTPUT_DIR / f"0_{save_count}_translated.json"
    if not output_file.exists():
        return None
    
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        return existing_data
    except:
        return None

def validate_and_fix_batch(translated_batch: List[str], original_batch: List[str]) -> List[str]:
    """验证并修复翻译结果长度"""
    if len(translated_batch) > len(original_batch):
        return translated_batch[:len(original_batch)]
    elif len(translated_batch) < len(original_batch):
        return translated_batch + original_batch[len(translated_batch):]
    return translated_batch

def save_partial_result(save_count: int, translated_data: List[str], original_data: List[str]):
    """保存每SAVE_EVERY批次的结果和原文"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # 保存翻译结果
    translated_file = OUTPUT_DIR / f"0_{save_count}_translated.json"
    with open(translated_file, 'w', encoding='utf-8') as f:
        json.dump(translated_data, f, ensure_ascii=False, indent=2)
    
    # 保存原文对照
    original_file = OUTPUT_DIR / f"0_{save_count}_original.json"
    with open(original_file, 'w', encoding='utf-8') as f:
        json.dump(original_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n\033[1;33m已保存第 {save_count} 次结果 → {translated_file}\033[0m")
    print(f"\033[1;33m已保存第 {save_count} 次原文 → {original_file}\033[0m")

def batch_translate(texts: List[str]):
    """单线程处理函数"""
    extracted_texts, structures = extract_text_parts(texts)
    batch_count = 0
    save_count = 0
    accumulated_translated = []
    accumulated_original = []
    
    # 计算总批次数
    total_batches = (len(extracted_texts) + BATCH_SIZE - 1) // BATCH_SIZE
    
    # 创建批次处理状态表
    batch_status = [False] * total_batches
    
    with tqdm(total=len(extracted_texts), desc="翻译进度") as pbar:
        
        # 第一步：扫描所有可能的缓存
        for save_idx in range(1, (total_batches + SAVE_EVERY - 1) // SAVE_EVERY + 1):
            existing_result = load_existing_result(save_idx)
            if existing_result is not None:
                # 计算这个save_count包含的批次数
                start_batch = (save_idx - 1) * SAVE_EVERY
                end_batch = min(start_batch + SAVE_EVERY, total_batches)
                
                # 标记这些批次为已处理
                for batch_idx in range(start_batch, end_batch):
                    batch_status[batch_idx] = True
                
                # 计算跳过的数据量
                start_index = start_batch * BATCH_SIZE
                end_index = min(end_batch * BATCH_SIZE, len(extracted_texts))
                skip_count = end_index - start_index
                
                # 更新进度条
                pbar.update(skip_count)
        
        # 第二步：处理实际批次
        for batch_idx in range(total_batches):
            # 如果批次已处理（通过缓存），则跳过
            if batch_status[batch_idx]:
                continue
                
            # 计算当前批次在数据中的位置
            start_index = batch_idx * BATCH_SIZE
            end_index = min(start_index + BATCH_SIZE, len(extracted_texts))
            
            batch = extracted_texts[start_index:end_index]
            original_batch = texts[start_index:end_index]
            
            # 计算当前save_count
            save_count = batch_idx // SAVE_EVERY + 1
            
            # 处理当前批次
            combined = safe_combine_texts(batch)
            print(combined)
            
            success = False
            translated_batch = []
            for attempt in range(MAX_RETRIES):
                try:
                    completion = client.chat.completions.create(
                        model="deepseek-chat",
                        messages=[
                            {"role": "system", "content": 
                            #  "你是一个专业的日文翻译助手。只翻译日文部分，严格保持符号、格式和分隔符|||不变，不要修改或解释分隔符；不要添加额外内容，如果遇到无法翻译的内容，原样返回"
                            "你是一个专业的日文翻译助手。请逐条翻译日文为中文，保留行号和顺序。"
                        "原文为编号形式（如 1. xxx），你只需将每行的文本部分翻译为中文，编号保持不变。"
                        "如果某行无法翻译，请原样保留。"
                            },
                            {"role": "user", "content": f"翻译以下日文为中文：\n{combined}"}
                        ],
                    )
                    

                    result = completion.choices[0].message.content
                    print(result)
                    translated_batch = safe_split_result(result, len(batch))
                    
                    # 验证并修复翻译结果
                    translated_batch = validate_and_fix_batch(translated_batch, batch)
                    
                    success = True
                    break
                    
                except Exception as e:
                    pbar.write(f"出错: {str(e)}")
                    time.sleep(3)
            
            if not success:
                translated_batch = batch  # 失败时保留原文
            
            # 重建完整格式
            partial_structures = structures[start_index:start_index+len(translated_batch)]
            final_translated = reconstruct_translated_texts(translated_batch, partial_structures)
            
            # 添加到累积列表
            accumulated_translated.extend(final_translated)
            accumulated_original.extend(original_batch)
            
            # 更新进度
            pbar.update(len(batch))
            batch_count += 1
            
            # 检查是否需要保存
            if (batch_idx + 1) % SAVE_EVERY == 0 or (batch_idx + 1) == total_batches:
                # 保存累积的结果和原文
                save_partial_result(save_count, accumulated_translated, accumulated_original)
                
                # 重置累积列表
                accumulated_translated = []
                accumulated_original = []

def merge_results_from_files() -> List[str]:
    """从临时文件合并最终结果"""
    # 获取所有翻译临时文件
    file_pattern = str(OUTPUT_DIR / "*_translated.json")
    files = glob.glob(file_pattern)
    
    # 按保存序号排序
    def sort_key(filename):
        base = Path(filename).stem
        parts = base.split('_')
        save_count = int(parts[1])
        return save_count
    
    files.sort(key=sort_key)
    
    # 合并所有文件
    final_result = []
    for file in files:
        print(file)
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                final_result.extend(data)
        except Exception as e:
            print(f"\033[1;31m加载文件失败 {file}: {e}\033[0m")
    
    return final_result

def main():
    # 验证输入文件
    if not INPUT_FILE.exists():
        print(f"错误: 输入文件不存在 {INPUT_FILE}")
        return
    
    # 读取数据
    try:
        texts = load_json(INPUT_FILE)
        total_items = len(texts)
    except Exception as e:
        print(f"读取输入文件失败: {e}")
        return
    
    print(f"\n\033[1;36m开始翻译 {total_items} 条字符串...\033[0m")
    print(f"\033[1;33m配置: 每批 {BATCH_SIZE} 条, 每 {SAVE_EVERY} 批保存一次\033[0m")
    start_time = time.time()
    
    # 执行翻译
    batch_translate(texts)
    
    # 从文件合并结果
    print("\n\033[1;36m合并临时文件...\033[0m")
    final_result = merge_results_from_files()
    
    # 保存最终结果
    try:
        with open("translation_strings_cn_debug.json", 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"\033[1;31m保存最终结果失败: {e}\033[0m")
    
    print(f"\n\033[1;32m翻译完成! 总耗时: {time.time()-start_time:.2f}秒\033[0m")
    print(f"\033[1;33m临时文件保存在: {OUTPUT_DIR}\033[0m")
    print(f"\033[1;33m最终结果保存在: translation_strings_cn_debug.json\033[0m")

if __name__ == "__main__":
    main()