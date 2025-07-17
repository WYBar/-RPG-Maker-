import json
from pathlib import Path
import re
from tqdm import tqdm
import time
import math

# ========== 配置 ==========
INPUT_FILE = Path("translation_strings.json")
OUTPUT_FILE = Path("translation_stats.json")  # 改为统计结果文件
MODEL_NAME = "gpt-4"
BATCH_SIZE = 100
PRINT_SAMPLES = True  # 是否打印样本
SAMPLE_SIZE = 5  # 打印的样本数量

# ========== 价格参数 ==========
INPUT_PRICE =0.002  # 输入价格 元/千tokens
OUTPUT_PRICE = 0.008  # 输出价格 元/千tokens
TOKENS_PER_SECOND = 1000  # 假设处理速度 (tokens/秒)

# ========== 增强版正则表达式 ==========
PATTERN = re.compile(
    r"^(?P<prefix>-*[↓↑]?[　\s-]*)"  # 更灵活的前缀（允许箭头在前）
    r"(?P<text>.*?)"  # 懒惰匹配所有字符作为文本部分
    r"(?P<suffix>[　\s↑↓-]*)$"  # 后缀
)

class TranslationStats:
    def __init__(self):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost = 0.0
        self.total_time = 0.0
        self.translated_strings = []
        
    def add_batch(self, input_tokens, output_tokens, process_time):
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += (input_tokens / 1000 * INPUT_PRICE) + (output_tokens / 1000 * OUTPUT_PRICE)
        self.total_time += process_time
        
    def get_summary(self):
        return {
            "total_strings": len(self.translated_strings),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost": self.total_cost,
            "estimated_time": self.total_time,
            "cost_detail": f"输入: ¥{self.total_input_tokens / 1000 * INPUT_PRICE:.2f} + 输出: ¥{self.total_output_tokens / 1000 * OUTPUT_PRICE:.2f}",
            "price_rates": f"输入: {INPUT_PRICE}元/千tokens, 输出: {OUTPUT_PRICE}元/千tokens"
        }

def estimate_tokens(text):
    """估算字符串的token数量（日文和中文通常1字符≈1token）"""
    return max(len(text), 1)  # 至少1个token

def extract_text_parts(texts: list) -> tuple[list, list]:
    """改进的文本提取函数"""
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

def simulate_translate(batch: list, stats: TranslationStats):
    """模拟翻译过程并统计"""
    combined = "\n=\n".join(str(text) for text in batch)
    
    # 估算输入输出token
    input_tokens = estimate_tokens(combined)
    output_tokens = int(input_tokens * 1.2)  # 假设输出比输入多20%
    
    # 模拟处理时间 (基于token数量)
    process_time = (input_tokens + output_tokens) / TOKENS_PER_SECOND
    
    # 更新统计
    stats.add_batch(input_tokens, output_tokens, process_time)
    
    # 模拟翻译结果 (原样返回但标记为已翻译)
    return batch

def batch_process(texts: list, stats: TranslationStats) -> list:
    """批量处理函数"""
    extracted_texts, structures = extract_text_parts(texts)
    
    translated = []
    for i in tqdm(range(0, len(extracted_texts), BATCH_SIZE), desc="模拟进度"):
        batch = extracted_texts[i:i+BATCH_SIZE]
        translated_batch = simulate_translate(batch, stats)
        translated.extend(translated_batch)
    
    # 确保数量一致
    translated = translated[:len(extracted_texts)]
    
    # 重建结构
    final_result = []
    for text, structure in zip(translated, structures):
        if structure and isinstance(text, str):
            prefix, suffix = structure
            final_result.append(f"{prefix}{text}{suffix}")
        else:
            final_result.append(text)
    
    stats.translated_strings = final_result
    return final_result

def print_samples(stats: TranslationStats):
    """打印样本"""
    if not PRINT_SAMPLES or len(stats.translated_strings) == 0:
        return
        
    print("\n随机样本:")
    samples = stats.translated_strings[:SAMPLE_SIZE]
    for i, sample in enumerate(samples, 1):
        print(f"[样本 {i}] {sample}")

def main():
    # 验证输入文件
    if not INPUT_FILE.exists():
        print(f"错误: 输入文件不存在 {INPUT_FILE}")
        return
    
    # 读取日文字符串
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            japanese_strings = json.load(f)
    except Exception as e:
        print(f"读取输入文件失败: {e}")
        return
    
    print(f"开始模拟翻译 {len(japanese_strings)} 条字符串...")
    start_time = time.time()
    
    stats = TranslationStats()
    batch_process(japanese_strings, stats)
    
    total_real_time = time.time() - start_time
    stats.total_time = max(stats.total_time, total_real_time)  # 取计算时间和实际时间的较大值
    
    # 保存统计结果
    result = stats.get_summary()
    try:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n统计结果已保存到: {OUTPUT_FILE}")
    except Exception as e:
        print(f"保存统计结果失败: {e}")
    
    # 打印统计
    print("\n===== 统计摘要 =====")
    print(f"总字符串数: {result['total_strings']}")
    print(f"总输入token: {result['total_input_tokens']}")
    print(f"总输出token: {result['total_output_tokens']}")
    print(f"预估费用: ¥{result['estimated_cost']:.2f} ({result['cost_detail']})")
    print(f"预估时间: {result['estimated_time']:.2f}秒")
    print(f"价格费率: {result['price_rates']}")
    
    print_samples(stats)

if __name__ == "__main__":
    main()