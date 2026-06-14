import os, struct

cfg_path = "D:/new_tdx/T0002/blocknew/blocknew.cfg"

with open(cfg_path, "rb") as f:
    data = f.read()

print(f"cfg文件大小: {len(data)} 字节")

# 已知的板块列表(从cfg内容推断)
# 每个记录似乎是: 显示名(48字节) + 文件名(48字节) + 2字节尾
RECORD_SIZE = 98  # 48 + 48 + 2

records = []
for i in range(0, len(data), RECORD_SIZE):
    chunk = data[i:i+RECORD_SIZE]
    if len(chunk) < RECORD_SIZE:
        break
    name_part = chunk[:48]
    file_part = chunk[48:96]
    tail = chunk[96:98]

    display_name = name_part.decode('gbk', errors='ignore').rstrip('\x00').strip()
    file_name = file_part.decode('gbk', errors='ignore').rstrip('\x00').strip()

    records.append((display_name, file_name, tail))
    print(f"记录{len(records)}: 名称[{display_name}] -> 文件[{file_name}] 尾[{tail.hex()}]")

# 检查是否已有观察池记录
has_watch = any('观察' in r[0] for r in records)
print(f"\n是否已有观察池记录: {has_watch}")

# 需要添加的记录
new_display_name = "claude观察池"
new_file_name = "CLAUDE_观察池"

# 构造新记录: 48字节名称 + 48字节文件名 + 00 00
name_bytes = new_display_name.encode('gbk').ljust(48, b'\x00')[:48]
file_bytes = new_file_name.encode('ascii').ljust(48, b'\x00')[:48]
tail_bytes = b'\x00\x00'
new_record = name_bytes + file_bytes + tail_bytes

print(f"\n新记录: {new_display_name} -> {new_file_name}")
print(f"新记录长度: {len(new_record)} 字节")
print(f"新记录hex: {new_record.hex()}")

# 追加到文件
with open(cfg_path, "ab") as f:
    f.write(new_record)

print("\n已追加到blocknew.cfg！")

# 验证
with open(cfg_path, "rb") as f:
    data2 = f.read()

print(f"更新后cfg大小: {len(data2)} 字节")
print(f"新增了 {len(data2) - len(data)} 字节")

# 再读一下看有没有正确写入
for i in range(0, len(data2), RECORD_SIZE):
    chunk = data2[i:i+RECORD_SIZE]
    if len(chunk) < RECORD_SIZE:
        break
    name_part = chunk[:48]
    file_part = chunk[48:96]
    tail = chunk[96:98]
    display_name = name_part.decode('gbk', errors='ignore').rstrip('\x00').strip()
    file_name = file_part.decode('gbk', errors='ignore').rstrip('\x00').strip()
    if display_name and file_name:
        print(f"  [{display_name}] -> [{file_name}]")
