#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
日志收集器模块
功能：通过SSH连接远程服务器，收集指定目录下的日志文件
支持：
1. Windows和Linux系统
2. 多种日期格式的日志文件名
3. 多种文件获取方式（SFTP/SCP）
4. 自动压缩打包
"""

import os
import paramiko  # SSH连接库
import yaml     # 配置文件解析
import datetime # 日期时间处理
import zipfile  # 文件压缩
from tqdm import tqdm  # 进度条显示
import logging  # 日志记录
import re       # 正则表达式
import shutil   # 文件操作

class LogCollector:
    """
    日志收集器类
    负责连接远程服务器、查找和下载日志文件、打包压缩等核心功能
    """
    def __init__(self, config_file='config.yaml', progress_callback=None):
        """
        初始化日志收集器
        Args:
            config_file: 配置文件路径，默认为'config.yaml'
            progress_callback: 进度回调函数，用于通知界面下载进度
        """
        self.setup_logging()  # 设置日志记录
        self.load_config(config_file)  # 加载配置文件
        self.ssh = None   # SSH连接对象
        self.sftp = None  # SFTP连接对象
        # 支持的日志文件后缀
        self.supported_extensions = ('.log', '.zip')
        # 缓存远程系统类型（Windows/Linux）
        self._is_windows = None
        # 进度回调函数
        self.progress_callback = progress_callback

    def setup_logging(self):
        """
        设置日志记录器
        配置日志格式、输出位置等
        """
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),  # 输出到控制台
                logging.FileHandler('log_collector.log')  # 输出到文件
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self, config_file):
        """
        加载配置文件
        Args:
            config_file: 配置文件路径
        Raises:
            Exception: 配置文件加载失败时抛出异常
        """
        if config_file is None:
            self.config = {}
            return
            
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"配置文件加载失败: {str(e)}")
            raise

    def connect(self):
        """
        建立SSH连接
        连接到远程服务器并创建SFTP会话
        Raises:
            Exception: 连接失败时抛出异常
        """
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(
                hostname=self.config['ssh']['host'],
                port=self.config['ssh'].get('port', 22),
                username=self.config['ssh']['username'],
                password=self.config['ssh']['password']
            )
            self.sftp = self.ssh.open_sftp()
            self.logger.info(f"成功连接到服务器 {self.config['ssh']['host']}")
        except Exception as e:
            self.logger.error(f"SSH连接失败: {str(e)}")
            raise

    def is_log_in_date_range(self, filename, start_date, end_date):
        """
        检查日志文件名是否在指定日期范围内
        支持多种日期格式：
        1. CenterDevCtrl_YYYY-MM-DD.xxx
        2. YYYY-MM-DD
        3. YYYYMMDD
        4. YYYY_MM_DD
        如果文件名中没有日期，则使用文件修改时间

        Args:
            filename: 文件名
            start_date: 开始日期
            end_date: 结束日期
        Returns:
            bool: 是否在日期范围内
        """
        # 首先尝试匹配标准格式：CenterDevCtrl_YYYY-MM-DD.xxx
        pattern = r'.*_(\d{4}-\d{2}-\d{2})\.(log|zip)$'
        match = re.match(pattern, filename)
        
        if match:
            try:
                date_str = match.group(1)
                file_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                return start_date <= file_date <= end_date
            except ValueError:
                pass

        # 尝试其他常见日期格式
        date_patterns = [
            r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
            r'(\d{8})',              # YYYYMMDD
            r'(\d{4}_\d{2}_\d{2})'  # YYYY_MM_DD
        ]
        
        for pattern in date_patterns:
            match = re.search(pattern, filename)
            if match:
                date_str = match.group(1)
                try:
                    if len(date_str) == 8:  # YYYYMMDD
                        file_date = datetime.datetime.strptime(date_str, '%Y%m%d').date()
                    elif '_' in date_str:  # YYYY_MM_DD
                        file_date = datetime.datetime.strptime(date_str, '%Y_%m_%d').date()
                    else:  # YYYY-MM-DD
                        file_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                    
                    return start_date <= file_date <= end_date
                except ValueError:
                    continue
        
        # 如果文件名中没有日期，使用文件的修改时间
        try:
            mtime = self.sftp.stat(filename).st_mtime
            file_date = datetime.datetime.fromtimestamp(mtime).date()
            return start_date <= file_date <= end_date
        except:
            return False

    def is_supported_file(self, filename):
        """
        检查文件是否是支持的类型（.log或.zip）
        Args:
            filename: 文件名
        Returns:
            bool: 是否是支持的文件类型
        """
        return filename.lower().endswith(self.supported_extensions)

    def collect_logs(self):
        """
        收集日志文件的主要方法
        流程：
        1. 创建本地保存目录
        2. 获取日期范围（如果启用）
        3. 检测远程系统类型
        4. 遍历所有指定路径
        5. 列出并过滤文件
        6. 下载符合条件的文件
        7. 压缩打包

        Returns:
            str: 压缩文件路径，如果没有找到文件则返回None
        Raises:
            Exception: 收集过程中的错误
        """
        try:
            # 获取日期范围
            date_range = self.config.get('date_range', {})
            use_date_range = date_range.get('enabled', False)
            if use_date_range:
                start_date = datetime.datetime.strptime(
                    date_range['start_date'], '%Y-%m-%d').date()
                end_date = datetime.datetime.strptime(
                    date_range['end_date'], '%Y-%m-%d').date()
                self.logger.info(f"使用日期范围: {start_date} 到 {end_date}")
                # 如果开始日期和结束日期相同，使用该日期；否则使用结束日期
                log_date = start_date if start_date == end_date else end_date
            else:
                # 如果没有指定日期范围，使用当前日期
                log_date = datetime.date.today()
            
            # 生成标准命名格式
            date_str = log_date.strftime("%Y-%m-%d")
            standard_zip_name = f"wcLog_{date_str}.zip"
            
            # 创建本地保存目录
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            local_dir = os.path.join("collected_logs", timestamp)
            os.makedirs(local_dir, exist_ok=True)

            # 检查远程系统类型
            is_windows = self.is_remote_windows()
            self.logger.info(f"远程系统类型: {'Windows' if is_windows else 'Linux/Unix'}")

            # 收集每个指定的日志文件
            for log_path in self.config['log_paths']:
                try:
                    remote_path = log_path.strip()
                    self.logger.info(f"处理路径: {remote_path}")
                    
                    # 尝试列出目录内容
                    try:
                        # 首先尝试使用SFTP列出目录
                        try:
                            files = self.sftp.listdir(remote_path)
                            is_dir = True
                            self.logger.info(f"在目录 {remote_path} 中找到 {len(files)} 个文件")
                        except Exception as e:
                            # SFTP列目录失败，尝试使用命令行方式
                            self.logger.warning(f"无法使用SFTP列出目录 {remote_path}: {str(e)}")
                            
                            # 根据系统类型选择命令
                            if is_windows:
                                cmd = f'dir /b "{remote_path}"'  # Windows的dir命令
                            else:
                                cmd = f'ls -1 {remote_path}'     # Linux的ls命令
                                
                            stdin, stdout, stderr = self.ssh.exec_command(cmd)
                            cmd_output = stdout.read().decode('utf-8', errors='ignore')
                            err_output = stderr.read().decode('utf-8', errors='ignore')
                            
                            if err_output and not cmd_output:
                                # 命令执行出错，可能是路径问题
                                self.logger.warning(f"命令行列出目录失败 {remote_path}: {err_output}")
                                files = [os.path.basename(remote_path)]
                                is_dir = False
                            else:
                                # 成功获取文件列表
                                files = [f.strip() for f in cmd_output.splitlines() if f.strip()]
                                is_dir = True
                    except Exception as e:
                        # 所有列目录方法都失败，假设是单个文件
                        self.logger.warning(f"假设 {remote_path} 是单个文件: {str(e)}")
                        files = [os.path.basename(remote_path)]
                        is_dir = False
                    
                    # 过滤出支持的文件类型
                    files = [f for f in files if self.is_supported_file(f)]
                    if not files:
                        self.logger.warning(f"在 {remote_path} 中没有找到支持的日志文件")
                        continue

                    self.logger.info(f"找到 {len(files)} 个支持的日志文件")

                    # 处理每个文件
                    for filename in files:
                        # 构建完整的远程路径
                        if is_dir:
                            # 根据系统类型使用正确的路径分隔符
                            if is_windows:
                                full_remote_path = remote_path.rstrip('\\') + '\\' + filename
                            else:
                                full_remote_path = os.path.join(remote_path, filename)
                        else:
                            full_remote_path = remote_path
                        
                        # 检查日期范围
                        if use_date_range:
                            if not self.is_log_in_date_range(filename, start_date, end_date):
                                self.logger.info(f"跳过日期范围外的文件: {filename}")
                                continue
                            else:
                                self.logger.info(f"找到日期范围内的文件: {filename}")
                        
                        local_path = os.path.join(local_dir, filename)
                        
                        # 下载文件
                        try:
                            self.logger.info(f"尝试下载文件: {full_remote_path}")
                            
                            # 首先尝试使用SFTP下载
                            try:
                                stats = self.sftp.stat(full_remote_path)
                                total_size = stats.st_size
                                
                                # 使用进度条显示下载进度
                                with tqdm(total=total_size, unit='B', unit_scale=True, 
                                        desc=f"下载 {filename}") as pbar:
                                    
                                    # 添加自定义的更新函数以同时通知进度条和回调函数
                                    def update_progress(transferred, total):
                                        # 更新tqdm进度条
                                        pbar.update(transferred - pbar.n)
                                        # 如果有回调函数，通知界面更新进度
                                        if self.progress_callback:
                                            self.progress_callback(filename, transferred, total)
                                    
                                    self.sftp.get(full_remote_path, local_path, callback=update_progress)
                                
                                self.logger.info(f"成功下载文件: {filename}")
                            except Exception as e:
                                # SFTP下载失败，尝试使用SCP方式
                                self.logger.error(f"使用SFTP下载 {filename} 失败: {str(e)}")
                                self.logger.info(f"尝试使用SCP方式下载 {filename}")
                                
                                try:
                                    import paramiko
                                    from scp import SCPClient
                                    
                                    # 创建SCP客户端并下载
                                    with SCPClient(self.ssh.get_transport()) as scp:
                                        # SCP不支持进度回调，所以先通知界面开始下载
                                        if self.progress_callback:
                                            self.progress_callback(filename, 0, 100)
                                        
                                        scp.get(full_remote_path, local_path)
                                        
                                        # 下载完成后通知界面进度100%
                                        if self.progress_callback:
                                            self.progress_callback(filename, 100, 100)
                                    
                                    self.logger.info(f"使用SCP成功下载文件: {filename}")
                                except Exception as scp_e:
                                    self.logger.error(f"SCP下载 {filename} 失败: {str(scp_e)}")
                                    continue
                        except Exception as e:
                            self.logger.error(f"下载文件 {filename} 失败: {str(e)}")
                            continue

                except Exception as e:
                    self.logger.error(f"处理路径 {log_path} 失败: {str(e)}")

            # 检查是否有文件被下载
            downloaded_files = os.listdir(local_dir)
            if not downloaded_files:
                self.logger.warning("没有找到符合条件的日志文件")
                return None

            # 检查是否只下载了一个zip文件
            if len(downloaded_files) == 1 and downloaded_files[0].lower().endswith('.zip'):
                self.logger.info(f"只下载了一个zip文件，不再进行压缩")
                single_zip_path = os.path.join(local_dir, downloaded_files[0])
                final_zip_path = os.path.join(os.path.dirname(local_dir), standard_zip_name)
                shutil.copy2(single_zip_path, final_zip_path)
                # 删除临时目录及其内容
                shutil.rmtree(local_dir)
                return final_zip_path

            # 压缩下载的文件
            zip_path = os.path.join(os.path.dirname(local_dir), standard_zip_name)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(local_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, local_dir)
                        zipf.write(file_path, arcname)

            # 压缩完成后删除原始文件
            shutil.rmtree(local_dir)
            self.logger.info(f"压缩完成后删除了原始日志文件")

            self.logger.info(f"日志文件已压缩保存到: {zip_path}")
            return zip_path

        except Exception as e:
            self.logger.error(f"收集日志过程中发生错误: {str(e)}")
            raise

    def close(self):
        """
        关闭SSH和SFTP连接
        """
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        self.logger.info("SSH连接已关闭")

    def is_remote_windows(self):
        """
        检测远程系统是否为Windows
        通过尝试执行系统特有的命令来判断
        
        Returns:
            bool: True表示Windows系统，False表示类Unix系统
        """
        # 如果已经检测过，直接返回缓存的结果
        if self._is_windows is not None:
            return self._is_windows
            
        try:
            # 尝试执行Windows特有的ver命令
            stdin, stdout, stderr = self.ssh.exec_command('ver')
            output = stdout.read().decode('utf-8', errors='ignore')
            
            # 检查输出中是否包含"Windows"字样
            self._is_windows = 'Windows' in output
            return self._is_windows
        except:
            # ver命令失败，尝试执行Unix的uname命令
            try:
                stdin, stdout, stderr = self.ssh.exec_command('uname')
                output = stdout.read().decode('utf-8', errors='ignore')
                
                # 如果能执行uname命令，说明是类Unix系统
                self._is_windows = False
                return False
            except:
                # 两种检测都失败，默认假设为Linux
                self._is_windows = False
                return False

def main():
    """
    主函数，用于命令行方式运行
    """
    collector = LogCollector()
    try:
        collector.connect()
        zip_path = collector.collect_logs()
        if zip_path:
            print(f"\n日志收集完成！压缩文件保存在: {zip_path}")
        else:
            print("\n没有找到符合条件的日志文件")
    except Exception as e:
        print(f"\n程序执行出错: {str(e)}")
    finally:
        collector.close()

if __name__ == "__main__":
    main() 