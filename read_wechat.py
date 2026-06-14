"""
微信消息监听器 - 通过UI Automation读取微信4.x聊天消息
不需要旧版微信，支持当前版本的微信
依赖: pip install uiautomation
"""
import uiautomation as auto
import time
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

MSG_FILE = "D:/股票分析/wechat_messages.txt"

def find_wechat():
    """查找微信主窗口"""
    # 微信4.x进程名是 Weixin.exe
    # 微信3.x进程名是 WeChat.exe
    for name in ["Weixin", "WeChat"]:
        windows = auto.GetRootControl().GetChildren()
        for w in windows:
            if name.lower() in w.Name.lower() or "微信" in w.Name:
                return w
    return None

def read_chat_messages(chat_window, max_read=20):
    """读取聊天窗口中的消息"""
    msgs = []
    try:
        # 查找消息列表控件
        msg_list = chat_window.ListControl()
        if msg_list:
            items = msg_list.GetChildren()
            for item in items[-max_read:]:
                txt = item.Name.strip()
                if txt:
                    msgs.append(txt)
    except:
        pass
    return msgs

def get_chat_list(wechat_window):
    """获取会话列表"""
    chats = []
    try:
        # 查找左侧会话列表
        all_controls = wechat_window.GetChildren()
        for c in all_controls:
            if "会话" in c.Name or "聊天" in c.Name:
                chats.append(c)
    except:
        pass
    return chats

def main():
    print("=" * 50)
    print("微信消息监听器启动")
    print(f"消息保存到: {MSG_FILE}")
    print("=" * 50)

    # 查找微信窗口
    win = find_wechat()
    if not win:
        print("❌ 未找到微信窗口")
        print("请先打开微信并保持运行")
        return

    print(f"✅ 找到微信窗口: {win.Name}")
    print(f"   位置: ({win.BoundingRectangle.left}, {win.BoundingRectangle.top})")
    print(f"   大小: {win.BoundingRectangle.width()}x{win.BoundingRectangle.height()}")

    # 激活窗口
    win.SetActive()
    time.sleep(1)

    # 尝试读取当前聊天消息
    print("\n尝试读取当前聊天消息...")
    msgs = read_chat_messages(win, 10)
    if msgs:
        print(f"\n读取到 {len(msgs)} 条消息:")
        for m in msgs[-5:]:
            print(f"  {m}")
    else:
        print("未读取到消息，尝试查找会话列表...")
        chats = get_chat_list(win)
        print(f"找到 {len(chats)} 个会话控件")

    # 保存
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(MSG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n=== {timestamp} ===\n")
        for m in msgs:
            f.write(m + "\n")

    print(f"\n消息已保存到 {MSG_FILE}")
    print("\n提示: 把微信聊天窗口打开到你想监听的群聊")
    print("然后运行这个脚本就能读取消息了")

if __name__ == "__main__":
    main()
