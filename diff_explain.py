import os
import glob
import datetime
import re
import json
import shutil
from openai import OpenAI
from feishu_hook import send_feishu_message

# OpenAI客户端初始化
client = OpenAI(
  base_url="https://openrouter.ai/api/v1",
  api_key="*******************",
)

def get_recent_diff_reports(hours=1):
    """
    获取指定小时数内的diff报告
    :param hours: 小时数，默认为1小时
    :return: 找到的diff报告文件列表
    """
    # 计算时间阈值
    now = datetime.datetime.now()
    time_threshold = now - datetime.timedelta(hours=hours)
    
    # 查找所有设备目录
    device_dirs = glob.glob(os.path.join('backups', '*'))
    device_dirs = [d for d in device_dirs if os.path.isdir(d) and not d.endswith('reports')]
    
    recent_reports = []
    
    for device_dir in device_dirs:
        device_name = os.path.basename(device_dir)
        diff_dir = os.path.join(device_dir, 'diff')
        
        if not os.path.exists(diff_dir):
            continue
        
        # 获取所有时间戳目录
        timestamp_dirs = glob.glob(os.path.join(diff_dir, '*'))
        timestamp_dirs = [d for d in timestamp_dirs if os.path.isdir(d)]
        
        for ts_dir in timestamp_dirs:
            # 从目录名提取时间戳
            ts_name = os.path.basename(ts_dir)
            if not re.match(r'^\d{12}$', ts_name):  # 确保格式为年月日时分
                continue
            
            try:
                # 解析时间戳
                dir_time = datetime.datetime.strptime(ts_name, '%Y%m%d%H%M')
                
                # 检查是否在时间阈值内
                if dir_time >= time_threshold:
                    # 获取目录中的所有diff文件
                    diff_files = glob.glob(os.path.join(ts_dir, '*_diff.txt'))
                    for diff_file in diff_files:
                        recent_reports.append({
                            'device_name': device_name,
                            'file_path': diff_file,
                            'timestamp': dir_time
                        })
            except ValueError:
                # 如果时间戳格式不正确，跳过
                continue
    
    return recent_reports

def read_diff_content(file_path):
    """
    读取diff文件内容
    :param file_path: diff文件路径
    :return: diff文件内容
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"读取文件失败: {str(e)}"

def extract_config_changes(diff_content):
    """
    从diff内容中提取配置变化
    :param diff_content: diff文件内容
    :return: 提取的配置变化
    """
    # 提取运行配置变化
    running_changes = ""
    startup_changes = ""
    
    # 分割内容
    sections = diff_content.split("\n\n")
    
    # 提取运行配置变化
    running_section_start = False
    for i, section in enumerate(sections):
        if "运行配置中新增的行:" in section or "运行配置中删除的行:" in section:
            running_section_start = True
            running_changes += section + "\n\n"
        elif running_section_start and "启动配置变化:" in section:
            running_section_start = False
    
    # 提取启动配置变化
    startup_section_start = False
    for i, section in enumerate(sections):
        if "启动配置变化:" in section or "启动配置中新增的行:" in section or "启动配置中删除的行:" in section:
            startup_section_start = True
            startup_changes += section + "\n\n"
    
    return {
        "running_changes": running_changes.strip(),
        "startup_changes": startup_changes.strip()
    }

def get_ai_explanation(config_changes):
    """
    使用OpenAI解释配置变化
    :param config_changes: 配置变化内容
    :return: AI解释
    """
    # 构建提示
    prompt = "仅仅解释以下网络设备配置变化的含义,不需要其他：\n\n"
    
    if config_changes["running_changes"]:
        prompt += "运行配置变化:\n" + config_changes["running_changes"] + "\n\n"
    
    if config_changes["startup_changes"]:
        prompt += "启动配置变化:\n" + config_changes["startup_changes"]
    
    try:
        # 调用OpenAI API
        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "",
                "X-Title": "",
            },
            extra_body={},
            model="qwen/qwen3-32b:free",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        # 返回解释
        return completion.choices[0].message.content
    except Exception as e:
        return f"获取AI解释失败: {str(e)}"

def save_to_diff_ai(device_name, timestamp, diff_content, ai_explanation):
    """
    保存原始diff报告和AI解释到diff_ai文件夹
    :param device_name: 设备名称
    :param timestamp: 时间戳
    :param diff_content: diff内容
    :param ai_explanation: AI解释
    :return: 保存的文件路径
    """
    # 创建diff_ai目录
    diff_ai_dir = os.path.join("backups", "diff_ai")
    if not os.path.exists(diff_ai_dir):
        os.makedirs(diff_ai_dir)
    
    # 创建设备目录
    device_dir = os.path.join(diff_ai_dir, device_name)
    if not os.path.exists(device_dir):
        os.makedirs(device_dir)
    
    # 创建时间戳目录
    timestamp_str = timestamp.strftime('%Y%m%d%H%M')
    timestamp_dir = os.path.join(device_dir, timestamp_str)
    if not os.path.exists(timestamp_dir):
        os.makedirs(timestamp_dir)
    
    # 保存原始diff内容
    diff_file = os.path.join(timestamp_dir, f"{device_name}_diff.txt")
    with open(diff_file, 'w', encoding='utf-8') as f:
        f.write(diff_content)
    
    # 保存AI解释
    explanation_file = os.path.join(timestamp_dir, f"{device_name}_explanation.txt")
    with open(explanation_file, 'w', encoding='utf-8') as f:
        f.write(ai_explanation)
    
    # 保存合并内容
    combined_file = os.path.join(timestamp_dir, f"{device_name}_combined.txt")
    with open(combined_file, 'w', encoding='utf-8') as f:
        f.write("原始配置变化:\n")
        f.write("=" * 50 + "\n\n")
        f.write(diff_content)
        f.write("\n\n")
        f.write("AI解释:\n")
        f.write("=" * 50 + "\n\n")
        f.write(ai_explanation)
    
    return combined_file

def main():
    # 飞书webhook URL
    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/*******************"
    
    # 获取最近一小时的diff报告
    recent_reports = get_recent_diff_reports(hours=1)
    
    if not recent_reports:
        print("未找到最近一小时内的配置变更报告")
        return
    
    print(f"找到 {len(recent_reports)} 个最近一小时内的配置变更报告")
    
    # 处理每个报告
    for report in recent_reports:
        device_name = report['device_name']
        file_path = report['file_path']
        timestamp = report['timestamp']
        
        print(f"处理设备 {device_name} 的配置变更报告...")
        
        # 读取diff内容
        diff_content = read_diff_content(file_path)
        
        # 提取配置变化
        config_changes = extract_config_changes(diff_content)
        
        # 如果没有配置变化，跳过
        if not config_changes["running_changes"] and not config_changes["startup_changes"]:
            print(f"设备 {device_name} 没有有效的配置变化，跳过")
            continue
        
        # 获取AI解释
        ai_explanation = get_ai_explanation(config_changes)
        
        # 保存到diff_ai文件夹
        combined_file = save_to_diff_ai(device_name, timestamp, diff_content, ai_explanation)
        
        # 构建消息
        message = f"设备 {device_name} 配置变化解释\n"
        message += f"时间: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        message += "原始配置变化:\n"
        message += "=" * 30 + "\n"
        message += diff_content
        message += "\n\n"
        message += "AI解释:\n"
        message += "=" * 30 + "\n"
        message += ai_explanation
        
        # 发送消息
        try:
            response = send_feishu_message(webhook_url, message)
            if response.status_code == 200:
                print(f"已成功发送 {device_name} 的配置变更通知和解释")
            else:
                print(f"发送 {device_name} 的配置变更通知和解释失败: {response.status_code} {response.text}")
        except Exception as e:
            print(f"发送 {device_name} 的配置变更通知和解释时出错: {str(e)}")

if __name__ == "__main__":
    main()