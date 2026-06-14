with open("D:/new_tdx/T0002/blocknew/blocknew.cfg", "rb") as f:
    data = f.read()

print(f"文件总大小: {len(data)}")
print(f"最后100字节hex:")
print(" ".join(f"{b:02x}" for b in data[-100:]))
print()
print(f"最后100字节文本:")
for b in data[-100:]:
    if 32 <= b <= 126:
        print(chr(b), end="")
    else:
        print(".", end="")
print()

# 查找"SPQR6.5"位置
idx = data.find(b"SPQR6.5")
print(f"\nSPQR6.5位置: {idx}")
start = max(0, idx-50)
end = min(len(data), idx+60)
print(f"SPQR6.5周围({start}-{end}):")
print(" ".join(f"{b:02x}" for b in data[start:end]))
print()
for b in data[start:end]:
    if 32 <= b <= 126:
        print(chr(b), end="")
    else:
        print(".", end="")
print()

# 检查每个记录是否是 48+48+2 结构
# 从SPQR6.5往前48字节看是否是中文名
name_start = idx - 48
print(f"\nSPQR6.5往前48字节: {data[name_start:idx]}")
print(f"解码: {data[name_start:idx].decode('gbk', errors='ignore')}")
