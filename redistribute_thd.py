import json
from pathlib import Path
import openai
from openai import OpenAI
import os
import re
from tqdm import tqdm
import threading
import queue
import time
import math
from typing import List, Tuple, Dict, Optional
import glob

# ========== 配置 ==========
INPUT_FILE = Path("translation_strings.json")
OUTPUT_DIR = Path("json_temp")
THREAD_COUNT = 8  # 线程数
BATCH_SIZE = 50   # 每批处理量
SAVE_EVERY = 10    # 每处理多少批次保存一次
MAX_RETRIES = 3    # 最大重试次数

# ========== 初始化Client ==========
client = OpenAI(api_key="sk-6a7f61f0ee874b7dadd0be7a1683b99a", base_url="https://api.deepseek.com")

# ========== 正则表达式 ==========
PATTERN = re.compile(
    r"^(?P<prefix>-*[↓↑]?[　\s-]*)"
    r"(?P<text>.*?)"
    r"(?P<suffix>[　\s↑↓-]*)$"
)

def split_json(input_file: Path, parts: int) -> List[List[dict]]:
    """将原始JSON文件拆分为多个部分"""
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    part_size = math.ceil(len(data) / parts)
    return [data[i*part_size : (i+1)*part_size] for i in range(parts)]

SEPARATOR = "|||"

# def safe_combine_texts(texts: List[str]) -> str:
#     """安全合并文本列表"""
#     for text in texts:
#         if SEPARATOR in text:
#             text = text.replace(SEPARATOR, "∣")
#     return SEPARATOR.join(texts)

def safe_combine_texts(texts: List[str]) -> str:
    return "\n".join([f"{i+1}. {t}" for i, t in enumerate(texts)])

# def safe_split_result(result: str, expected_count: int) -> List[str]:
#     """安全拆分翻译结果"""
#     parts = [p.strip() for p in result.split(SEPARATOR) if p.strip()]
    
#     if len(parts) != expected_count:
#         parts = [p for p in parts 
#                 if not p.startswith("=") and not p.startswith("「") 
#                 and len(p) > 1]
#     return parts

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


def validate_and_fix_batch(translated_batch: List[str], original_batch: List[str]) -> List[str]:
    """验证并修复翻译结果长度"""
    if len(translated_batch) > len(original_batch):
        return translated_batch[:len(original_batch)]
    elif len(translated_batch) < len(original_batch):
        return translated_batch + original_batch[len(translated_batch):]
    return translated_batch

def save_partial_result(thread_id: int, save_count: int, translated_data: List[str], original_data: List[str]):
    """保存每SAVE_EVERY批次的结果和原文"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    # 保存翻译结果
    translated_file = OUTPUT_DIR / f"{thread_id}_{save_count}_translated.json"
    with open(translated_file, 'w', encoding='utf-8') as f:
        json.dump(translated_data, f, ensure_ascii=False, indent=2)
    
    # 保存原文对照
    original_file = OUTPUT_DIR / f"{thread_id}_{save_count}_original.json"
    with open(original_file, 'w', encoding='utf-8') as f:
        json.dump(original_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n\033[1;33m[线程 {thread_id}] 已保存第 {save_count} 次结果 → {translated_file}\033[0m")
    print(f"\033[1;33m[线程 {thread_id}] 已保存第 {save_count} 次原文 → {original_file}\033[0m")

def find_missing_batches() -> List[Tuple[int, int]]:
    """找出所有未完成的 thread_id 和 save_count 组合"""
    missing = []
    
    # 扫描所有可能的组合
    for thread_id in range(THREAD_COUNT):
        # 获取该线程所有已保存的文件
        existing_files = glob.glob(str(OUTPUT_DIR / f"{thread_id}_*_translated.json"))
        existing_save_counts = {int(Path(f).stem.split('_')[1]) for f in existing_files}
        
        # 找出该线程理论上应该有的所有 save_count
        part = split_json(INPUT_FILE, THREAD_COUNT)[thread_id]
        total_batches = (len(part) + BATCH_SIZE - 1) // BATCH_SIZE
        all_save_counts = set(range(1, (total_batches + SAVE_EVERY - 1) // SAVE_EVERY + 1))
        
        # 计算缺失的 save_count
        missing_save_counts = all_save_counts - existing_save_counts
        for save_count in sorted(missing_save_counts):
            missing.append((thread_id, save_count))
    
    return missing

def redistribute_missing_batches(missing: List[Tuple[int, int]]):
    """将缺失的批次重新分配给线程处理"""
    if not missing:
        print("\033[1;32m所有批次已完成，无需重新分配\033[0m")
        return
    
    print(f"\n\033[1;33m发现 {len(missing)} 个未完成批次，重新分配到 {THREAD_COUNT} 个线程...\033[0m")
    
    # 将缺失批次均匀分配到线程
    batches_per_thread = [[] for _ in range(THREAD_COUNT)]
    for i, batch in enumerate(missing):
        batches_per_thread[i % THREAD_COUNT].append(batch)
    
    # 准备线程任务队列
    task_queue = queue.Queue()
    for thread_id, batches in enumerate(batches_per_thread):
        if batches:
            task_queue.put((thread_id, batches))
    
    def process_redistributed_batches(thread_id: int, batches: List[Tuple[int, int]]):
        """处理重新分配的任务"""
        print(f"\033[1;36m[线程 {thread_id}] 分配到 {len(batches)} 个待处理批次\033[0m；分别为: {batches}")
        
        for original_thread_id, save_count in batches:
            # 加载原始数据分片
            parts = split_json(INPUT_FILE, THREAD_COUNT)
            original_texts = parts[original_thread_id]
            
            # 计算该save_count对应的批次范围
            start_batch = (save_count - 1) * SAVE_EVERY
            end_batch = min(start_batch + SAVE_EVERY, (len(original_texts) + BATCH_SIZE - 1) // BATCH_SIZE)
            
            # 提取需要处理的具体文本
            start_index = start_batch * BATCH_SIZE
            end_index = min(end_batch * BATCH_SIZE, len(original_texts))
            texts_to_process = original_texts[start_index:end_index]
            
            # 调用原有的处理逻辑
            extracted, structures = extract_text_parts(texts_to_process)
            translated = []
            original = []
            
            # 分小批次处理（避免一次性处理过多）
            for i in range(0, len(extracted), BATCH_SIZE):
                batch = extracted[i:i+BATCH_SIZE]
                original_batch = texts_to_process[i:i+BATCH_SIZE]
                
                combined = safe_combine_texts(batch)
                
                for attempt in range(MAX_RETRIES):
                    try:
                        completion = client.chat.completions.create(
                            model="deepseek-chat",
                            messages=[
                                {"role": "system", "content": 
                                "你是一个专业的日文翻译助手。请逐条翻译日文为中文，保留行号和顺序。"},
                                {"role": "user", "content": f"翻译以下日文为中文：\n{combined}"}
                            ],
                        )
                        result = completion.choices[0].message.content
                        translated_batch = safe_split_result(result, len(batch))
                        translated_batch = validate_and_fix_batch(translated_batch, batch)
                        break
                    except Exception as e:
                        print(f"\033[1;31m[线程 {thread_id}] 重试 {attempt+1}/{MAX_RETRIES}: {e}\033[0m")
                        time.sleep(3)
                else:
                    translated_batch = batch  # 所有重试失败后使用原文
                
                # 重建完整格式
                partial_structures = structures[i:i+len(translated_batch)]
                final_translated = reconstruct_translated_texts(translated_batch, partial_structures)
                
                translated.extend(final_translated)
                original.extend(original_batch)
            
            # 保存结果（使用原始thread_id和save_count）
            save_partial_result(original_thread_id, save_count, translated, original)
    
    # 启动线程处理
    threads = []
    while not task_queue.empty():
        thread_id, batches = task_queue.get()
        t = threading.Thread(
            target=process_redistributed_batches,
            args=(thread_id, batches),
            daemon=True
        )
        t.start()
        threads.append(t)
        time.sleep(0.1)  # 避免进度条错位
    
    # 等待所有线程完成
    for t in threads:
        t.join()

def merge_results_from_files() -> List[str]:
    """从临时文件合并最终结果（仅使用翻译文件）"""
    # 获取所有翻译临时文件
    file_pattern = str(OUTPUT_DIR / "*_translated.json")
    files = glob.glob(file_pattern)
    
    # 按线程ID和保存序号排序
    def sort_key(filename):
        base = Path(filename).stem
        parts = base.split('_')
        thread_id = int(parts[0])
        save_count = int(parts[1])
        return (thread_id, save_count)
    
    files.sort(key=sort_key)
    
    # 合并所有文件
    final_result = []
    for file in files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                final_result.extend(data)
        except Exception as e:
            print(f"\033[1;31m加载文件失败 {file}: {e}\033[0m")
    
    return final_result

def resume_translation():
    """恢复未完成的翻译任务"""
    print("\n\033[1;35m=== 检查未完成批次 ===\033[0m")
    missing = find_missing_batches()
    
    if missing:
        print("\033[1;33m发现未完成批次:\033[0m")
        for thread_id, save_count in missing:
            print(f"  - 线程 {thread_id} 的 save_count {save_count}")
        
        redistribute_missing_batches(missing)
        
        # 合并最终结果
        print("\n\033[1;36m合并最终结果...\033[0m")
        final_result = merge_results_from_files()
        with open("translation_strings_cn.json", 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        print("\033[1;32m所有缺失批次处理完成!\033[0m")
    else:
        print("\033[1;32m没有发现未完成的批次\033[0m")

if __name__ == "__main__":
    resume_translation()  # 添加这行