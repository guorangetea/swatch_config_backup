import paramiko
import time
import socket
import os
import datetime
import csv
import re
import filecmp
import glob

def get_config(hostname, username, password, port, command, timeout=120, device_type=None, device_name=None):
    """为每个命令创建新的SSH连接并执行命令，改进分页处理"""
    device_info = f"{device_name}({hostname})" if device_name else hostname
    print(f"设备 {device_info} - 执行命令: {command}")
    
    # 创建新的SSH客户端
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        # 连接到设备
        ssh_client.connect(
            hostname, 
            port=port,
            username=username, 
            password=password,
            timeout=30,
            allow_agent=False,
            look_for_keys=False
        )
        
        # 创建一个新的通道
        channel = ssh_client.invoke_shell()
        # 设置终端大小，避免分页问题
        channel.settimeout(timeout)
        
        # 清空缓冲区
        if channel.recv_ready():
            channel.recv(1024)
        
        # 根据设备类型发送禁用分页命令
        if device_type == 'huawei':
            print(f"设备 {device_info} - 发送华为设备禁用分页命令: screen-length 0 temporary")
            channel.send('screen-length 0 temporary\n')
        elif device_type == 'h3c':
            print(f"设备 {device_info} - 发送华三设备禁用分页命令: screen-length disable")
            channel.send('screen-length disable\n')
        else:
            # 尝试通用命令
            print(f"设备 {device_info} - 设备类型未知，尝试通用禁用分页命令")
            channel.send('screen-length 0 temporary\n')
            time.sleep(1)
            channel.send('screen-length disable\n')
        
        time.sleep(2)
        if channel.recv_ready():
            channel.recv(4096)
        
        # 发送命令
        channel.send(command + '\n')
        time.sleep(2)  # 给设备一些响应时间
        
        # 接收输出
        output = ""
        max_wait_cycles = 5  # 增加最大等待周期
        wait_cycles = 0
        last_output_length = 0  # 记录上次输出长度
        same_length_count = 0   # 记录输出长度不变的次数
        
        while True:
            if channel.recv_ready():
                chunk = channel.recv(4096).decode('utf-8', errors='ignore')
                output += chunk
                print(f"设备 {device_info} - 接收到 {len(chunk)} 字节数据")
                wait_cycles = 0  # 重置等待周期
                
                # 检查是否有分页提示，如果有则发送空格继续
                if ' ---- More ----' in chunk or '--More--' in chunk or '  ---- More ----' in chunk:
                    print(f"设备 {device_info} - 检测到分页提示，发送空格继续...")
                    channel.send(' ')
                    time.sleep(1.5)  # 增加等待时间，确保设备有足够时间处理
                
                # 如果接收到命令提示符，表示命令执行完毕
                if ('#' in chunk or '>' in chunk) and len(chunk.strip()) > 1 and command not in chunk:
                    # 确保这不是命令回显
                    if not any(cmd_part in chunk for cmd_part in command.split()):
                        break
                
                # 检查输出长度是否变化
                if len(output) == last_output_length:
                    same_length_count += 1
                else:
                    same_length_count = 0
                    last_output_length = len(output)
                
                # 如果连续多次输出长度不变，可能是卡在了某个状态
                if same_length_count >= 5:
                    print(f"设备 {device_info} - 检测到输出长度不变，尝试发送回车...")
                    channel.send('\n')
                    time.sleep(1)
                    same_length_count = 0
            else:
                # 如果没有更多数据，等待一下再检查
                time.sleep(1)
                wait_cycles += 1
                
                # 如果等待超过最大周期，检查是否已经有完整输出
                if wait_cycles >= max_wait_cycles:
                    # 检查是否有命令提示符，如果有则可能已经完成
                    if '#' in output or '>' in output:
                        print(f"设备 {device_info} - 达到最大等待周期，检测到命令提示符，结束接收")
                        break
                    else:
                        # 尝试发送回车，看是否能触发更多输出
                        print(f"设备 {device_info} - 达到最大等待周期，发送回车...")
                        channel.send('\n')
                        time.sleep(1)
                        wait_cycles = 0  # 重置等待周期
        
        # 清理输出中的分页标记和控制字符
        output = output.replace(' ---- More ----', '').replace('--More--', '').replace('  ---- More ----', '')
        # 清理华三设备特有的控制字符
        output = re.sub(r'\[\d+D\s*\[\d+D', '', output)
        
        # 关闭通道和连接
        channel.close()
        ssh_client.close()
        return output
        
    except Exception as e:
        print(f"设备 {device_info} - 命令执行错误: {str(e)}")
        ssh_client.close()
        raise

def compare_configs(running_config, startup_config):
    # 比较运行配置和已保存配置
    # 清理配置文本，移除提示符和分页标记
    def clean_config(config):
        lines = []
        for line in config.splitlines():
            # 移除分页标记和提示符
            line = line.replace(' ---- More ----', '').replace('--More--', '')
            # 移除控制字符
            line = re.sub(r'\[\d+D\s*\[\d+D', '', line)
            # 移除命令提示符和命令本身
            if not (line.strip().startswith('<') or line.strip().endswith('#') or line.strip().endswith('>')):
                # 移除命令行
                if not ('display' in line and 'configuration' in line):
                    # 忽略以 Info: 开头的行
                    if not line.strip().startswith('Info:'):
                        if line.strip():  # 只添加非空行
                            lines.append(line.strip())
        return lines
    
    running_lines = clean_config(running_config)
    startup_lines = clean_config(startup_config)
    
    running_set = set(running_lines)
    startup_set = set(startup_lines)
    
    added_lines = running_set - startup_set
    removed_lines = startup_set - running_set
    
    return added_lines, removed_lines

def save_config_to_file(hostname, config_type, config_content, device_name=None):
    """将配置保存到文件"""
    # 创建备份目录
    backup_dir = "backups"
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    
    # 使用设备名称作为第一级目录
    device_name = device_name or hostname
    device_dir = os.path.join(backup_dir, device_name)
    if not os.path.exists(device_dir):
        os.makedirs(device_dir)
    
    # 使用配置类型作为第二级目录
    config_type_dir = os.path.join(device_dir, config_type)
    if not os.path.exists(config_type_dir):
        os.makedirs(config_type_dir)
    
    # 使用年月日时分作为第三级目录
    timestamp_dir = datetime.datetime.now().strftime("%Y%m%d%H%M")
    final_dir = os.path.join(config_type_dir, timestamp_dir)
    
    # 检查是否有之前的备份
    previous_backup = get_latest_backup(config_type_dir)
    
    # 如果有之前的备份，创建临时文件比较内容
    if previous_backup:
        temp_file = os.path.join(device_dir, f"temp_{config_type}.txt")
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        # 获取上一次备份的文件路径
        prev_backup_file = os.path.join(previous_backup, f"{hostname}_{config_type}.txt")
        
        # 比较文件内容
        if os.path.exists(prev_backup_file) and files_are_identical(temp_file, prev_backup_file):
            # 如果内容相同，删除临时文件并返回上一次的备份文件路径
            os.remove(temp_file)
            device_info = f"{device_name}({hostname})" if device_name != hostname else hostname
            print(f"设备 {device_info} - {config_type}配置与上次备份相同，跳过备份")
            return prev_backup_file
        
        # 删除临时文件
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    # 如果没有之前的备份或内容不同，创建新的备份
    if not os.path.exists(final_dir):
        os.makedirs(final_dir)
    
    # 生成文件名
    filename = f"{hostname}_{config_type}.txt"
    filepath = os.path.join(final_dir, filename)
    
    # 保存配置到文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(config_content)
    
    device_info = f"{device_name}({hostname})" if device_name != hostname else hostname
    print(f"设备 {device_info} - {config_type}配置已保存到 {filepath}")
    return filepath

def get_latest_backup(config_dir):
    """获取最新的备份目录"""
    if not os.path.exists(config_dir):
        return None
    
    # 获取所有备份目录（格式为年月日时分）
    backup_dirs = [d for d in os.listdir(config_dir) if os.path.isdir(os.path.join(config_dir, d))]
    
    # 按照时间戳排序
    backup_dirs.sort(reverse=True)
    
    if backup_dirs:
        return os.path.join(config_dir, backup_dirs[0])
    
    return None

def files_are_identical(file1, file2):
    """比较两个文件内容是否相同"""
    # 使用filecmp模块比较文件
    return filecmp.cmp(file1, file2, shallow=False)

def process_device(device):
    """处理单个设备的配置备份和比较"""
    hostname = device['hostname']
    username = device['username']
    password = device['password']
    port = device.get('port', 22)
    device_type = device.get('device_type', 'unknown')
    device_name = device.get('device_name', '')
    
    device_info = f"{device_name}({hostname})" if device_name else hostname
    
    try:
        print(f"\n开始处理设备: {device_info} (类型: {device_type})")
        
        # 获取运行配置
        print(f"设备 {device_info} - 获取运行配置...")
        running_config = get_config(hostname, username, password, port, 'display current-configuration', 
                                   device_type=device_type, device_name=device_name)
        print(f"设备 {device_info} - 获取到运行配置，长度: {len(running_config)} 字节")
        
        # 保存运行配置到文件
        running_config_file = save_config_to_file(hostname, "running", running_config, device_name)
        
        # 获取启动配置
        print(f"设备 {device_info} - 获取启动配置...")
        try:
            # 无论是华为还是华三设备，都使用相同的命令
            startup_config = get_config(hostname, username, password, port, 'display saved-configuration', 
                                       device_type=device_type, device_name=device_name)
            print(f"设备 {device_info} - 获取到启动配置，长度: {len(startup_config)} 字节")
            
            # 检查启动配置是否与最近一次相同
            startup_changed = True  # 默认假设有变化
            prev_startup_added = set()  # 存储当前startup相比上次新增的行
            prev_startup_removed = set()  # 存储当前startup相比上次删除的行
            startup_diff_lines = []  # 存储启动配置差异的行，初始化为空列表
            
            # 获取最近一次的启动配置目录
            device_name = device_name or hostname
            startup_dir = os.path.join("backups", device_name, "startup")
            if os.path.exists(startup_dir):
                latest_startup_dir = get_latest_backup(startup_dir)
                
                if latest_startup_dir:
                    # 获取最近一次启动配置文件路径
                    latest_startup_file = os.path.join(latest_startup_dir, f"{hostname}_startup.txt")
                    
                    # 比较文件内容
                    if os.path.exists(latest_startup_file):
                        # 读取上一次的启动配置
                        with open(latest_startup_file, 'r', encoding='utf-8') as f:
                            prev_startup_config = f.read()
                        
                        # 创建临时文件保存当前启动配置
                        temp_file = os.path.join(startup_dir, f"temp_{hostname}_startup.txt")
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            f.write(startup_config)
                        
                        if files_are_identical(temp_file, latest_startup_file):
                            startup_changed = False
                            print(f"设备 {device_info} - 启动配置与上次相同，使用上次的配置文件")
                            startup_config_file = latest_startup_file
                        else:
                            # 如果启动配置有变化，计算差异
                            print(f"设备 {device_info} - 启动配置与上次不同，计算差异")
                            
                            # 比较当前startup和上次备份的startup
                            prev_startup_added, prev_startup_removed = compare_configs(startup_config, prev_startup_config)
                        
                            if prev_startup_added:
                                startup_diff_lines.append("当前启动配置相比上次备份新增的行:")
                                for line in prev_startup_added:
                                    startup_diff_lines.append(f"+ {line}")
                            else:
                                startup_diff_lines.append("当前启动配置相比上次备份没有新增的行。")
                            
                            startup_diff_lines.append("")  # 空行分隔
                            
                            if prev_startup_removed:
                                startup_diff_lines.append("当前启动配置相比上次备份删除的行:")
                                for line in prev_startup_removed:
                                    startup_diff_lines.append(f"- {line}")
                            else:
                                startup_diff_lines.append("当前启动配置相比上次备份没有删除的行。")
                    
                    # 删除临时文件
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
            
            # 如果启动配置有变化，保存到文件
            if startup_changed:
                startup_config_file = save_config_to_file(hostname, "startup", startup_config, device_name)
            
            # 比较配置
            added_lines, removed_lines = compare_configs(running_config, startup_config)
            
            # 检查是否有差异
            has_diff = bool(added_lines or removed_lines)
            diff_file = None
            
            # 如果有差异且启动配置有变化，保存差异到文件
            if has_diff and startup_changed:
                # 使用设备名称作为第一级目录
                diff_dir = os.path.join("backups", device_name, "diff")
                if not os.path.exists(diff_dir):
                    os.makedirs(diff_dir)
                
                # 使用年月日时分作为第二级目录
                timestamp_dir = datetime.datetime.now().strftime("%Y%m%d%H%M")
                final_diff_dir = os.path.join(diff_dir, timestamp_dir)
                if not os.path.exists(final_diff_dir):
                    os.makedirs(final_diff_dir)
                
                diff_file = os.path.join(final_diff_dir, f"{hostname}_diff.txt")
                
                with open(diff_file, 'w', encoding='utf-8') as f:
                    f.write(f"设备: {device_info}\n")
                    f.write(f"比较时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    f.write("运行配置中新增的行:\n")
                    if added_lines:
                        for line in added_lines:
                            f.write(f"+ {line}\n")
                    else:
                        f.write("没有新增的行。\n")
                    
                    f.write("\n运行配置中删除的行:\n")
                    if removed_lines:
                        for line in removed_lines:
                            f.write(f"- {line}\n")
                    else:
                        f.write("没有删除的行。\n")
                    
                    # 添加启动配置变化信息
                    if startup_changed and (prev_startup_added or prev_startup_removed):
                        f.write("\n启动配置变化:\n")
                        if prev_startup_added:
                            f.write("启动配置中新增的行:\n")
                            for line in prev_startup_added:
                                f.write(f"+ {line}\n")
                        else:
                            f.write("启动配置中没有新增的行。\n")
                        
                        f.write("\n")
                        
                        if prev_startup_removed:
                            f.write("启动配置中删除的行:\n")
                            for line in prev_startup_removed:
                                f.write(f"- {line}\n")
                        else:
                            f.write("启动配置中没有删除的行。\n")
                
                print(f"设备 {device_info} - 配置差异已保存到 {diff_file}")
            elif startup_changed:  # 只有启动配置有变化
                # 使用设备名称作为第一级目录
                diff_dir = os.path.join("backups", device_name, "diff")
                if not os.path.exists(diff_dir):
                    os.makedirs(diff_dir)
                
                # 使用年月日时分作为第二级目录
                timestamp_dir = datetime.datetime.now().strftime("%Y%m%d%H%M")
                final_diff_dir = os.path.join(diff_dir, timestamp_dir)
                if not os.path.exists(final_diff_dir):
                    os.makedirs(final_diff_dir)
                
                diff_file = os.path.join(final_diff_dir, f"{hostname}_diff.txt")
                
                with open(diff_file, 'w', encoding='utf-8') as f:
                    f.write(f"设备: {device_info}\n")
                    f.write(f"比较时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                    
                    f.write("运行配置与启动配置无差异。\n\n")
                    
                    # 添加启动配置变化信息
                    f.write("启动配置变化:\n")
                    if prev_startup_added:
                        f.write("启动配置中新增的行:\n")
                        for line in prev_startup_added:
                            f.write(f"+ {line}\n")
                    else:
                        f.write("启动配置中没有新增的行。\n")
                    
                    f.write("\n")
                    
                    if prev_startup_removed:
                        f.write("启动配置中删除的行:\n")
                        for line in prev_startup_removed:
                            f.write(f"- {line}\n")
                    else:
                        f.write("启动配置中没有删除的行。\n")
                
                print(f"设备 {device_info} - 启动配置有变化，差异已保存到 {diff_file}")
            elif has_diff:
                print(f"设备 {device_info} - 有配置差异，但启动配置未变化，跳过生成diff报告")
            else:
                print(f"设备 {device_info} - 没有配置差异，跳过生成diff报告")
            
            # 输出差异
            print(f"\n设备 {device_info} - 配置差异:")
            if added_lines:
                print(f"设备 {device_info} - 运行配置中新增的行:")
                for line in added_lines:
                    print(f"+ {line}")
            else:
                print(f"设备 {device_info} - 没有新增的行。")
            
            if removed_lines:
                print(f"设备 {device_info} - 运行配置中删除的行:")
                for line in removed_lines:
                    print(f"- {line}")
            else:
                print(f"设备 {device_info} - 没有删除的行。")
            
            return {
                'hostname': hostname,
                'device_name': device_name,
                'status': 'success',
                'running_config_file': running_config_file,
                'startup_config_file': startup_config_file,
                'diff_file': diff_file,
                'has_diff': has_diff,
                'startup_changed': startup_changed  # 添加标记表示启动配置是否变化
            }
            
        except Exception as e:
            print(f"设备 {device_info} - 获取启动配置失败: {str(e)}")
            return {
                'hostname': hostname,
                'device_name': device_name,
                'status': 'partial',
                'running_config_file': running_config_file,
                'error': str(e)
            }
            
    except Exception as e:
        print(f"设备 {device_info} - 处理失败: {str(e)}")
        return {
            'hostname': hostname,
            'device_name': device_name,
            'status': 'failed',
            'error': str(e)
        }

def main():
    # 检查是否存在设备CSV文件
    csv_file = 'devices.csv'
    if os.path.exists(csv_file):
        print(f"从CSV文件加载设备信息: {csv_file}")
        devices = load_devices_from_csv(csv_file)
    else:
        # 如果CSV文件不存在，创建一个模板文件但包含真实密码
        create_devices_template(csv_file)
        print(f"已创建设备CSV模板文件: {csv_file}")
        print(f"已创建设备CSV模板文件: {csv_file}")
        print("请编辑此文件添加设备信息后再运行程序")
        return
    
    if not devices:
        print("没有找到设备信息，请检查设备列表或CSV文件")
        return
    
    print(f"找到 {len(devices)} 个设备")
    
    # 处理每个设备
    results = []
    has_any_diff = False
    has_any_startup_change = False  # 添加标记表示是否有任何设备的启动配置变化
    
    for device in devices:
        result = process_device(device)
        results.append(result)
        if result.get('status') == 'success':
            if result.get('has_diff', False):
                has_any_diff = True
            if result.get('startup_changed', False):
                has_any_startup_change = True
    
    # 只有当有差异且有启动配置变化时才生成汇总报告
    if has_any_diff and has_any_startup_change:
        # 生成汇总报告
        print("\n配置备份和比较汇总报告:")
        for result in results:
            hostname = result['hostname']
            device_name = result.get('device_name', '')
            status = result['status']
            
            device_info = f"{device_name}({hostname})" if device_name else hostname
            
            if status == 'success':
                diff_status = "有差异" if result['has_diff'] else "无差异"
                startup_status = "有变化" if result.get('startup_changed', False) else "无变化"
                print(f"设备 {device_info}: 成功 (配置差异: {diff_status}, 启动配置: {startup_status})")
            elif status == 'partial':
                print(f"设备 {device_info}: 部分成功 (只获取了运行配置)")
            else:
                print(f"设备 {device_info}: 失败 - {result.get('error', '未知错误')}")
        
        # 使用年月日作为文件名
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        report_dir = os.path.join("backups", "reports")
        if not os.path.exists(report_dir):
            os.makedirs(report_dir)
        
        # 报告文件名使用年月日
        report_file = os.path.join(report_dir, f"{date_str}.txt")
        
        # 获取当前时间作为本次报告的时间戳
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # 准备报告内容
        report_content = f"===== {current_time} 配置备份和比较汇总报告 =====\n\n"
        
        for result in results:
            hostname = result['hostname']
            device_name = result.get('device_name', '')
            status = result['status']
            
            device_info = f"{device_name}({hostname})" if device_name else hostname
            
            report_content += f"设备: {device_info}\n"
            report_content += f"状态: {status}\n"
            
            if status == 'success':
                report_content += f"运行配置文件: {result['running_config_file']}\n"
                report_content += f"启动配置文件: {result['startup_config_file']}\n"
                if result['diff_file']:
                    report_content += f"差异文件: {result['diff_file']}\n"
                report_content += f"配置差异: {'有' if result['has_diff'] else '无'}\n"
                report_content += f"启动配置变化: {'有' if result.get('startup_changed', False) else '无'}\n"
            elif status == 'partial':
                report_content += f"运行配置文件: {result['running_config_file']}\n"
                report_content += f"错误: {result.get('error', '未知错误')}\n"
            else:
                report_content += f"错误: {result.get('error', '未知错误')}\n"
            
            report_content += "\n"
        
        report_content += "=" * 50 + "\n\n"
        
        # 检查文件是否存在，如果存在则追加内容，否则创建新文件
        if os.path.exists(report_file):
            with open(report_file, 'a', encoding='utf-8') as f:
                f.write(report_content)
            print(f"\n汇总报告已追加到 {report_file}")
        else:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
            print(f"\n汇总报告已保存到 {report_file}")
    else:
        if not has_any_diff:
            print("\n所有设备配置无差异，跳过生成汇总报告")
        elif not has_any_startup_change:
            print("\n所有设备启动配置未变化，跳过生成汇总报告")
        else:
            print("\n跳过生成汇总报告")

def create_devices_template(csv_file):
    """创建设备CSV模板文件，不包含真实密码"""
    with open(csv_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['hostname', 'username', 'password', 'port', 'device_type', 'device_name'])
    print(f"已创建设备CSV模板文件，请编辑 {csv_file} 添加设备信息和密码")

def load_devices_from_csv(csv_file):
    """从CSV文件加载设备信息"""
    devices = []
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 确保必要的字段存在
                if 'hostname' in row and 'username' in row and 'password' in row:
                    # 转换端口为整数
                    if 'port' in row and row['port']:
                        row['port'] = int(row['port'])
                    else:
                        row['port'] = 22  # 默认SSH端口
                    
                    devices.append(row)
    except Exception as e:
        print(f"加载设备信息失败: {str(e)}")
    
    return devices

if __name__ == '__main__':
    main()
