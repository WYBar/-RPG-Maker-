import os
import json
import shutil
import re
import random
from pathlib import Path
from tqdm import tqdm

# ========== 配置 ==========
SOURCE_DIR = Path("www/data")
BACKUP_DIR = Path("www/data_bak")
OUTPUT_FILE = Path("translation_strings.json")  # 保存需要翻译的字符串
SAMPLE_SIZE = 5  # 随机采样的数量
JP_REGEX = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff]+')  # 检测日文字符

# ========== 统计变量 ==========
translation_count = 0
total_tokens = 0
strings_to_translate = []  # 存储所有需要翻译的字符串

# ========== 备份函数 ==========
def backup_data_dir():
    if BACKUP_DIR.exists():
        print("备份目录已存在，跳过备份。")
    else:
        shutil.copytree(SOURCE_DIR, BACKUP_DIR)
        print(f"已备份 {SOURCE_DIR} 到 {BACKUP_DIR}")

        # 删除指定文件
        files_to_delete = ["CommonEvents.json", "Tilesets.json"]
        for file in files_to_delete:
            file_path = SOURCE_DIR / file
            try:
                if file_path.exists():
                    file_path.unlink()
                    print(f"已删除文件: {file_path}")
                else:
                    print(f"文件不存在，无需删除: {file_path}")
            except Exception as e:
                print(f"删除文件 {file_path} 时出错: {e}")

# ========== 模拟翻译函数 ==========
def gpt_translate(text: str) -> str:
    global translation_count, input_tokens, output_tokens, total_tokens, strings_to_translate
    
    # 记录需要翻译的字符串
    strings_to_translate.append(text)
    
    # 模拟翻译请求
    translation_count += 1
    
    # 估算token数量 (日文和中文通常1字符≈1token)
    input_token = len(text)
    output_token = len(text) * 1.2  # 假设中文输出比日文长20%
    input_tokens += input_token
    output_tokens += output_token
    total_tokens += int(input_token + output_token)
    
    # 返回原始文本而不实际翻译
    return text

# ========== 遍历 JSON 并统计 ==========
def translate_japanese_in_obj(obj):
    if isinstance(obj, dict):
        return {k: translate_japanese_in_obj(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [translate_japanese_in_obj(item) for item in obj]
    elif isinstance(obj, str):
        if JP_REGEX.search(obj):
            return gpt_translate(obj)
        return obj
    else:
        return obj

# ========== 保存翻译字符串 ==========
def save_translation_strings():
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(strings_to_translate, f, ensure_ascii=False, indent=2)
    print(f"\n已保存 {len(strings_to_translate)} 条需要翻译的字符串到 {OUTPUT_FILE}")

# ========== 显示随机样本 ==========
def show_samples():
    if len(strings_to_translate) == 0:
        print("没有找到需要翻译的字符串")
        return
        
    sample_size = min(SAMPLE_SIZE, len(strings_to_translate))
    samples = random.sample(strings_to_translate, sample_size)
    
    print(f"\n随机采样 {sample_size} 条需要翻译的字符串:")
    for i, sample in enumerate(samples, 1):
        print(f"\n【样本 {i}】")
        print(sample)

# ========== 主处理流程 ==========
def process_all_json_files():
    global translation_count, input_tokens, output_tokens, total_tokens, strings_to_translate

    # 正确地使用 global 声明并重置
    translation_count = 0
    total_tokens = 0
    input_tokens = 0
    output_tokens = 0
    strings_to_translate = []
    
    json_files = list(SOURCE_DIR.glob("*.json"))
    for file_path in tqdm(json_files, desc="统计中"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            # 只处理不保存
            translate_japanese_in_obj(content)
        except Exception as e:
            print(f"[错误] 处理文件 {file_path}: {e}")
    
    # 保存和显示结果
    save_translation_strings()
    show_samples()
    
    print(f"\n统计结果:")
    print(f"需要翻译的字符串数量: {translation_count}")
    print(f"预估总token消耗: {total_tokens}")
    print(f"输入token数量: {input_tokens}, 输出token数量: {output_tokens}")
    print(f"按v3价格估算费用: ${input_tokens / 1000 * 0.002 + output_tokens / 1000 * 0.008:.2f} (输入+输出)")

# ========== 启动 ==========
def main():
    print("开始备份...")
    backup_data_dir()
    print("开始统计需要翻译的内容...")
    process_all_json_files()

if __name__ == "__main__":
    main()