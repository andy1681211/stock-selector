# 方案：把观察池的15只股票合并到"claude选股"(CLAUDEXG.blk)板块
# 这样用户按Ctrl+Z选"claude选股"就能看到观察池的票了

# 读取观察池
watch_codes = set()
with open("D:/new_tdx/T0002/blocknew/CLAUDE_观察池.blk", "r") as f:
    for line in f:
        code = line.strip()
        if code:
            watch_codes.add(code)

print(f"观察池: {len(watch_codes)} 只")

# 读取claude选股(已存在的板块)
existing = set()
with open("D:/new_tdx/T0002/blocknew/CLAUDEXG.blk", "r") as f:
    for line in f:
        code = line.strip()
        if code:
            existing.add(code)

print(f"claude选股原有: {len(existing)} 只")

# 合并（去重）
merged = existing | watch_codes

# 写回CLAUDEXG.blk
with open("D:/new_tdx/T0002/blocknew/CLAUDEXG.blk", "wb") as f:
    for code in sorted(merged):
        f.write(code.encode("ascii") + b"\r\n")

print(f"合并后: {len(merged)} 只")
print(f"新增: {len(merged) - len(existing)} 只")
print(f"已在通达信中按 Ctrl+Z 选 \"claude选股\" 即可查看")
