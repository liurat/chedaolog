#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import paramiko
import yaml
import datetime
import zipfile
from tqdm import tqdm
import logging
import re

class LogCollector:
    def __init__(self, config_file='config.yaml'):
        self.setup_logging()
        self.load_config(config_file)
        self.ssh = None
        self.sftp = None
        # 支持的文件后缀
        self.supported_extensions = ('.log', '.zip')

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('log_collector.log')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_config(self, config_file):
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
        """检查日志文件名是否在指定日期范围内"""
        # 首先尝试匹配 CenterDevCtrl_YYYY-MM-DD.xxx 格式
        pattern = r'.*_(\d{4}-\d{2}-\d{2})\.(log|zip)$'
        match = re.match(pattern, filename)
        
        if match:
            try:
                date_str = match.group(1)
                file_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                return start_date <= file_date <= end_date
            except ValueError:
                pass

        # 如果不匹配，尝试其他常见日期格式
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
        
        # 如果无法从文件名提取日期，尝试使用文件的修改时间
        try:
            mtime = self.sftp.stat(filename).st_mtime
            file_date = datetime.datetime.fromtimestamp(mtime).date()
            return start_date <= file_date <= end_date
        except:
            return False

    def is_supported_file(self, filename):
        """检查文件是否是支持的类型"""
        return filename.lower().endswith(self.supported_extensions)

    def collect_logs(self):
        try:
            # 创建本地保存目录
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            local_dir = os.path.join("collected_logs", timestamp)
            os.makedirs(local_dir, exist_ok=True)

            # 获取日期范围
            date_range = self.config.get('date_range', {})
            use_date_range = date_range.get('enabled', False)
            if use_date_range:
                start_date = datetime.datetime.strptime(
                    date_range['start_date'], '%Y-%m-%d').date()
                end_date = datetime.datetime.strptime(
                    date_range['end_date'], '%Y-%m-%d').date()
                self.logger.info(f"使用日期范围: {start_date} 到 {end_date}")

            # 收集每个指定的日志文件
            for log_path in self.config['log_paths']:
                try:
                    remote_path = log_path.strip()
                    
                    # 如果路径是目录，则列出目录中的所有文件
                    try:
                        files = self.sftp.listdir(remote_path)
                        is_dir = True
                        self.logger.info(f"在目录 {remote_path} 中找到 {len(files)} 个文件")
                    except:
                        files = [os.path.basename(remote_path)]
                        is_dir = False
                    
                    # 过滤出支持的文件类型
                    files = [f for f in files if self.is_supported_file(f)]
                    if not files:
                        self.logger.warning(f"在 {remote_path} 中没有找到支持的日志文件")
                        continue

                    self.logger.info(f"找到 {len(files)} 个支持的日志文件")

                    for filename in files:
                        full_remote_path = os.path.join(remote_path, filename) if is_dir else remote_path
                        
                        # 检查日期范围
                        if use_date_range:
                            if not self.is_log_in_date_range(filename, start_date, end_date):
                                self.logger.info(f"跳过日期范围外的文件: {filename}")
                                continue
                            else:
                                self.logger.info(f"找到日期范围内的文件: {filename}")
                        
                        local_path = os.path.join(local_dir, filename)
                        
                        # 获取远程文件大小
                        try:
                            stats = self.sftp.stat(full_remote_path)
                            total_size = stats.st_size
                            
                            with tqdm(total=total_size, unit='B', unit_scale=True, 
                                    desc=f"下载 {filename}") as pbar:
                                self.sftp.get(full_remote_path, local_path, 
                                            callback=lambda x, y: pbar.update(y - pbar.n))
                            
                            self.logger.info(f"成功下载文件: {filename}")
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

            # 压缩文件
            zip_path = f"{local_dir}.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(local_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, local_dir)
                        zipf.write(file_path, arcname)

            self.logger.info(f"日志文件已压缩保存到: {zip_path}")
            return zip_path

        except Exception as e:
            self.logger.error(f"收集日志过程中发生错误: {str(e)}")
            raise

    def close(self):
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        self.logger.info("SSH连接已关闭")

def main():
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