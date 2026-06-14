"""
微信群消息监听器
通过 WeChatFerry 连接微信PC客户端，自动将群消息输出到文件
文件路径: D:\股票分析\wechat_messages.txt
"""

import wcferry
import threading
import json
import os
from datetime import datetime

class WeChatListener:
    def __init__(self):
        self.wcf = wcferry.Wcf()
        self.msg_file = "D:/股票分析/wechat_messages.txt"

    def on_msg(self, msg):
        """收到消息的回调"""
        try:
            # 只处理群消息
            if msg.type == 1:  # 文字消息
                # 群消息的roomid不是空
                if msg.roomid:
                    sender = msg.sender
                    # 获取发送者昵称
                    member_info = self.wcf.get_chatroom_members(msg.roomid)

                    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{msg.roomid}] {msg.sender}: {msg.content}"

                    with open(self.msg_file, "a", encoding="utf-8") as f:
                        f.write(line + "\n")

                    # 也打印出来看看
                    print(line)
        except Exception as e:
            print(f"处理消息出错: {e}")

    def run(self):
        print("=" * 50)
        print("微信消息监听器启动")
        print(f"消息会保存到: {self.msg_file}")
        print("=" * 50)

        # 检查是否登录
        if not self.wcf.is_login():
            print("微信未登录，请先登录微信")
            return

        print(f"登录用户: {self.wcf.get_user_info()}")

        # 获取群列表
        rooms = self.wcf.get_rooms()
        print(f"\n当前群聊 ({len(rooms)}个):")
        for r in rooms:
            print(f"  {r}")

        # 注册消息回调
        self.wcf.enable_receiving(self.on_msg)

        print("\n开始监听消息... (按Ctrl+C停止)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\n停止监听")
        finally:
            self.wcf.cleanup()

if __name__ == "__main__":
    listener = WeChatListener()

    # 先测试连接
    try:
        print("正在连接微信...")
        print(f"WeChatFerry版本: {wcferry.__version__}")
        print(f"微信版本: {listener.wcf.get_version()}")

        listener.run()
    except Exception as e:
        print(f"启动失败: {e}")
        print("\n请确保:")
        print("1. 微信PC端已打开并登录")
        print("2. 微信版本为3.9.x")
