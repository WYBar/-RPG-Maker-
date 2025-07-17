# RPG Maker游戏基于大模型的自助翻译脚本

## 原理

RPG Maker游戏的主要文本内容以json形式存储于www/data文件夹下，通过提取该文件夹下json的日语内容，汇总并格式化为一个json文件，之后调用Deepseek等大模型API对其进行翻译、写回，从而实现RPG Maker游戏的翻译。

## 环境

主要依赖openai的SDK，无特殊依赖。

## 脚本

### 翻译

将python文件置于与www文件夹平行的位置，并依次执行以下文件：

1. **transfile2json.py**：从www/data中提取日语内容，按序格式化并保存为一个translation_strings.json文件；
2. **translate_v4.py**：调用deepseek API(https://platform.deepseek.com/usage)，逐行对translation_strings.json进行翻译，结果保存到translation_strings_cn.json；
3. **write_back_cn_trans.py**：将translation_strings_cn.json写回到www/data中的目标位置。

### 其余

1. **transfile2json_onlysta.py**：测算大致token数量和API开销，但经过实际测试，该脚本测量的开销是真实开销的约2倍，如果考虑deepseek半价时段，则是实际开销约4倍；
2. **translate_v4_debug.py**：单线程测试脚本；
3. **redistribute_thd.py**：在translate_v4.py执行后期使用，用于解决不同线程处理速度差距较大的问题，重新分配各个线程的负载。

## 更新

**2025.7.17**：调用上述脚本能够实现翻译功能，但是在游戏运行中调试发现www/data中有四类文本不需要翻译：

1. CommonEvents.json；
2. Tilesets.json；
3. 父键列表中存在"image"的日语，代表www/img中的日语图片文件名，改为中文后无法调用相应图片文件；
4. TO DO：www/audio中的日语音频文件名，与3类似，但目前样本较少，没有修改和测试。









