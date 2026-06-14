with open("D:/new_tdx/T0002/blocknew/blocknew.cfg", "rb") as f:
    data = f.read()

print(f"文件大小: {len(data)} 字节")
print()
for i in range(0, len(data), 16):
    hex_str = " ".join(f"{b:02x}" for b in data[i:i+16])
    ascii_str = ""
    for b in data[i:i+16]:
        if 32 <= b <= 126:
            ascii_str += chr(b)
        elif b == 0:
            ascii_str += " "
        else:
            ascii_str += "."
    print(f"{i:04x}: {hex_str:<48} '{ascii_str}'")
