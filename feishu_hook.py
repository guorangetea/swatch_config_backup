import requests
import json

def send_feishu_message(webhook_url, message):
    """
    发送消息到飞书机器人
    
    参数:
        webhook_url (str): 飞书机器人的webhook URL
        message (str): 要发送的消息内容
        
    返回:
        Response: 请求响应对象
    """
    headers = {
        'Content-Type': 'application/json'
    }
    
    # 构建飞书消息格式
    payload = {
        "msg_type": "text",
        "content": {
            "text": message
        }
    }
    
    # 发送请求
    response = requests.post(webhook_url, headers=headers, data=json.dumps(payload))
    return response

if __name__ == "__main__":
    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/*******************"
    message_text = "Hello, Feishu!"
    response = send_feishu_message(webhook_url, message_text)
    if response.status_code == 200:
        print("消息发送成功！")