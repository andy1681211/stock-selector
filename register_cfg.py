with open("D:/new_tdx/T0002/blocknew/blocknew.cfg", "rb") as f:
    data = f.read()

RECORD_SIZE = 96  # 48(显示名) + 48(文件名)
num_records = len(data) // RECORD_SIZE
print(f"记录数: {num_records}, 文件总大小: {len(data)}")

for i in range(num_records):
    chunk = data[i*RECORD_SIZE:(i+1)*RECORD_SIZE]
    name_part = chunk[:48].rstrip(b'\x00')
    file_part = chunk[48:96].rstrip(b'\x00')
    display = name_part.decode('gbk', errors='ignore')
    fname = file_part.decode('ascii', errors='ignore')
    print(f"  [{display}] -> [{fname}]")

# 添加观察池记录
display_bytes = "观察池".encode('gbk').ljust(48, b'\x00')[:48]
file_bytes = "CLAUDE_观察池".encode('ascii').ljust(48, b'\x00')[:48]
new_record = display_bytes + file_bytes

with open("D:/new_tdx/T0002/blocknew/blocknew.cfg", "ab") as f:
    f.write(new_record)

print(f"\n已添加! 新文件大小: {len(data) + len(new_record)}")

# 验证
with open("D:/new_tdx/T0002/blocknew/blocknew.cfg", "rb") as f:
    data2 = f.read()

num2 = len(data2) // RECORD_SIZE
for i in range(num2):
    chunk = data2[i*RECORD_SIZE:(i+1)*RECORD_SIZE]
    name_part = chunk[:48].rstrip(b'\x00')
    file_part = chunk[48:96].rstrip(b'\x00')
    display = name_part.decode('gbk', errors='ignore')
    fname = file_part.decode('ascii', errors='ignore')
    print(f"  [{display}] -> [{fname}]")
