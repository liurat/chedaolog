#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import yaml
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QLabel, QLineEdit, QPushButton,
                           QTextEdit, QFileDialog, QProgressBar, QMessageBox,
                           QSpinBox, QListWidget, QCalendarWidget, QGroupBox,
                           QCheckBox, QDateEdit, QDialog, QComboBox, QTableWidget,
                           QTableWidgetItem, QHeaderView, QDialogButtonBox, QTabWidget,
                           QSizePolicy, QListWidgetItem, QSplitter)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from log_collector import LogCollector

class LogCollectorWorker(QThread):
    progress = pyqtSignal(str, int, int)  # 文件名，当前进度，总大小
    finished = pyqtSignal(str)  # 完成信号
    error = pyqtSignal(str)     # 错误信号
    file_list = pyqtSignal(list)  # 文件列表信号
    
    def __init__(self, config, mode='collect'):
        super().__init__()
        self.config = config
        self.mode = mode
        
    def run(self):
        try:
            collector = LogCollector(config_file=None, progress_callback=self.update_progress)
            collector.config = self.config
            collector.connect()
            
            try:
                if self.mode == 'collect':
                    zip_path = collector.collect_logs()
                    self.finished.emit(zip_path)
                elif self.mode == 'list':
                    # 获取文件列表
                    for path in self.config['log_paths']:
                        try:
                            # 根据系统类型选择命令
                            if collector.is_remote_windows():
                                # Windows系统使用dir命令
                                cmd = f'dir /O-D "{path}"'
                                stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                                try:
                                    files = stdout.read().decode('gbk').splitlines()
                                except UnicodeDecodeError:
                                    # 如果读取失败，重新执行命令
                                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                                    files = stdout.read().decode('utf-8', errors='ignore').splitlines()
                                
                                # 跳过Windows dir命令的头部信息
                                start_idx = 0
                                for i, line in enumerate(files):
                                    if "Directory of" in line:
                                        start_idx = i + 2
                                        break
                                
                                files = files[start_idx:]
                                
                                # 解析文件信息
                                file_info_list = []
                                for line in files:
                                    if not line.strip() or "<DIR>" in line:
                                        continue
                                    
                                    parts = line.strip().split()
                                    if len(parts) >= 4:
                                        # Windows dir命令格式: 日期 时间 大小 文件名
                                        try:
                                            date_str = parts[0]
                                            time_str = parts[1]
                                            # 文件名可能包含空格，所以要合并后面的所有部分
                                            filename = ' '.join(parts[3:])
                                            file_info_list.append({
                                                'name': filename,
                                                'date': f"{date_str} {time_str}",
                                                'path': path
                                            })
                                        except:
                                            continue
                            else:
                                # Linux系统使用ls命令
                                cmd = f'ls -lt {path} | head -n 11'  # 11是因为第一行是total
                                stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                                try:
                                    files = stdout.read().decode('utf-8').splitlines()
                                except UnicodeDecodeError:
                                    files = stdout.read().decode('gbk', errors='ignore').splitlines()
                                
                                # 移除第一行的total
                                if files and files[0].startswith('total'):
                                    files = files[1:]
                                
                                # 解析文件信息
                                file_info_list = []
                                for line in files:
                                    parts = line.split()
                                    if len(parts) >= 9:  # 确保行包含足够的部分
                                        # 提取文件名（可能包含空格的最后一部分）
                                        filename = ' '.join(parts[8:])
                                        # 提取日期时间
                                        date_str = ' '.join(parts[5:8])
                                        file_info_list.append({
                                            'name': filename,
                                            'date': date_str,
                                            'path': path
                                        })
                            
                            self.file_list.emit(file_info_list)
                        except Exception as e:
                            self.error.emit(f"列出目录 {path} 失败: {str(e)}")
            finally:
                collector.close()
        except Exception as e:
            self.error.emit(str(e))

    def update_progress(self, filename, current, total):
        """
        更新进度条
        Args:
            filename: 当前正在下载的文件名
            current: 当前已下载的字节数
            total: 文件总字节数
        """
        # 发送进度信号
        self.progress.emit(filename, current, total)

class PathInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加远程目录路径")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        # 添加说明标签
        info_label = QLabel("请输入远程主机上的日志目录完整路径\n例如：/var/log/车道系统/")
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)
        
        # 添加输入框
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("输入远程目录路径")
        layout.addWidget(self.path_input)
        
        # 添加按钮
        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        cancel_button = QPushButton("取消")
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
    
    def get_path(self):
        return self.path_input.text().strip()

class HostInputDialog(QDialog):
    def __init__(self, parent=None, host_data=None):
        super().__init__(parent)
        self.setWindowTitle("添加/编辑主机信息")
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout(self)
        
        # 主机名称
        name_layout = QHBoxLayout()
        name_label = QLabel("主机名称:")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如: 生产服务器")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # SSH连接信息
        ssh_group = QGroupBox("SSH连接设置")
        ssh_layout = QVBoxLayout(ssh_group)
        
        # 主机地址
        host_layout = QHBoxLayout()
        host_label = QLabel("主机地址:")
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("例如: 192.168.1.100")
        port_label = QLabel("端口:")
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(22)
        host_layout.addWidget(host_label)
        host_layout.addWidget(self.host_input)
        host_layout.addWidget(port_label)
        host_layout.addWidget(self.port_input)
        ssh_layout.addLayout(host_layout)
        
        # 用户名密码
        credentials_layout = QHBoxLayout()
        username_label = QLabel("用户名:")
        self.username_input = QLineEdit()
        password_label = QLabel("密码:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        credentials_layout.addWidget(username_label)
        credentials_layout.addWidget(self.username_input)
        credentials_layout.addWidget(password_label)
        credentials_layout.addWidget(self.password_input)
        ssh_layout.addLayout(credentials_layout)
        
        layout.addWidget(ssh_group)
        
        # 日志路径列表
        path_group = QGroupBox("日志文件路径")
        path_layout = QVBoxLayout(path_group)
        
        # 添加路径说明
        path_info = QLabel("请输入日志文件所在的目录，程序会自动查找并下载符合日期条件的日志文件\n支持的文件类型：.log 和 .zip")
        path_info.setStyleSheet("color: gray;")
        path_layout.addWidget(path_info)
        
        # 创建路径列表和按钮的完整容器
        path_list_container = QWidget()
        path_list_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        path_list_layout = QVBoxLayout(path_list_container)
        path_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加路径列表
        self.path_list = QListWidget()
        self.path_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        path_list_layout.addWidget(self.path_list, 1)  # 1是拉伸因子，让列表获得尽可能多的空间
        
        # 路径操作按钮容器，使用水平布局
        path_buttons_container = QWidget()
        path_buttons_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        path_buttons = QHBoxLayout(path_buttons_container)
        path_buttons.setContentsMargins(0, 0, 0, 0)
        
        # 添加按钮
        add_path_btn = QPushButton("添加目录")
        remove_path_btn = QPushButton("删除选中")
        path_buttons.addWidget(add_path_btn)
        path_buttons.addWidget(remove_path_btn)
        path_buttons.addStretch(1)  # 添加空白区域推开按钮
        
        # 添加按钮区域到列表容器
        path_list_layout.addWidget(path_buttons_container)
        
        # 将完整容器添加到路径组布局
        path_layout.addWidget(path_list_container)
        
        # 连接按钮事件
        add_path_btn.clicked.connect(self.add_path)
        remove_path_btn.clicked.connect(self.remove_path)
        
        layout.addWidget(path_group)
        
        # 添加确定取消按钮
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 如果有主机数据，填充表单
        if host_data:
            self.name_input.setText(host_data.get("name", ""))
            self.host_input.setText(host_data.get("ssh", {}).get("host", ""))
            self.port_input.setValue(host_data.get("ssh", {}).get("port", 22))
            self.username_input.setText(host_data.get("ssh", {}).get("username", ""))
            self.password_input.setText(host_data.get("ssh", {}).get("password", ""))
            
            for path in host_data.get("log_paths", []):
                self.path_list.addItem(path)
    
    def add_path(self):
        dialog = PathInputDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            path = dialog.get_path()
            if path:
                self.path_list.addItem(path)
    
    def remove_path(self):
        current_item = self.path_list.currentItem()
        if current_item:
            self.path_list.takeItem(self.path_list.row(current_item))
    
    def get_host_data(self):
        return {
            "name": self.name_input.text(),
            "ssh": {
                "host": self.host_input.text(),
                "port": self.port_input.value(),
                "username": self.username_input.text(),
                "password": self.password_input.text()
            },
            "log_paths": [self.path_list.item(i).text() 
                         for i in range(self.path_list.count())]
        }

class HostManagerDialog(QDialog):
    def __init__(self, parent=None, hosts_data=None):
        super().__init__(parent)
        self.setWindowTitle("主机管理")
        self.setMinimumSize(700, 400)
        
        self.hosts_data = hosts_data or []
        
        layout = QVBoxLayout(self)
        
        # 主机列表表格
        self.hosts_table = QTableWidget()
        self.hosts_table.setColumnCount(4)
        self.hosts_table.setHorizontalHeaderLabels(["主机名称", "主机地址", "用户名", "日志路径数"])
        self.hosts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        layout.addWidget(self.hosts_table)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        add_host_btn = QPushButton("添加主机")
        edit_host_btn = QPushButton("编辑主机")
        delete_host_btn = QPushButton("删除主机")
        button_layout.addWidget(add_host_btn)
        button_layout.addWidget(edit_host_btn)
        button_layout.addWidget(delete_host_btn)
        
        # 确定取消按钮
        close_btn = QPushButton("关闭")
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # 连接信号
        add_host_btn.clicked.connect(self.add_host)
        edit_host_btn.clicked.connect(self.edit_host)
        delete_host_btn.clicked.connect(self.delete_host)
        close_btn.clicked.connect(self.accept)
        
        # 加载主机数据
        self.load_hosts()
    
    def load_hosts(self):
        self.hosts_table.setRowCount(len(self.hosts_data))
        
        for row, host in enumerate(self.hosts_data):
            self.hosts_table.setItem(row, 0, QTableWidgetItem(host.get("name", "")))
            self.hosts_table.setItem(row, 1, QTableWidgetItem(host.get("ssh", {}).get("host", "")))
            self.hosts_table.setItem(row, 2, QTableWidgetItem(host.get("ssh", {}).get("username", "")))
            self.hosts_table.setItem(row, 3, QTableWidgetItem(str(len(host.get("log_paths", [])))))
    
    def add_host(self):
        dialog = HostInputDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            host_data = dialog.get_host_data()
            self.hosts_data.append(host_data)
            self.load_hosts()
    
    def edit_host(self):
        current_row = self.hosts_table.currentRow()
        if current_row >= 0 and current_row < len(self.hosts_data):
            dialog = HostInputDialog(self, self.hosts_data[current_row])
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.hosts_data[current_row] = dialog.get_host_data()
                self.load_hosts()
    
    def delete_host(self):
        current_row = self.hosts_table.currentRow()
        if current_row >= 0 and current_row < len(self.hosts_data):
            host_name = self.hosts_data[current_row].get("name", "")
            reply = QMessageBox.question(self, "确认删除", 
                                       f"确定要删除主机 '{host_name}' 吗？",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                del self.hosts_data[current_row]
                self.load_hosts()
    
    def get_hosts_data(self):
        return self.hosts_data

class LogAnalysisWorker(QThread):
    log_list = pyqtSignal(list)  # 日志列表信号
    search_result = pyqtSignal(str, list)  # 搜索结果信号，关键字和结果行列表
    complete_log = pyqtSignal(str)  # 完整日志信号
    error = pyqtSignal(str)  # 错误信号
    log_message_signal = pyqtSignal(str)  # 添加日志消息信号
    
    def __init__(self, config, mode='list', log_path=None, keyword=None):
        super().__init__()
        self.config = config
        self.mode = mode
        self.log_path = log_path
        self.keyword = keyword
    
    def log_message(self, message):
        """发送普通日志消息"""
        self.log_message_signal.emit(message)
        
    def run(self):
        try:
            collector = LogCollector(config_file=None)
            collector.config = self.config
            collector.connect()
            
            try:
                if self.mode == 'list':
                    # 获取日志文件列表
                    self.get_log_files(collector)
                elif self.mode == 'search':
                    # 在日志中搜索关键字
                    self.search_keyword(collector)
                elif self.mode == 'get_log':
                    # 获取完整日志
                    self.get_full_log(collector)
            finally:
                collector.close()
        except Exception as e:
            self.error.emit(str(e))
    
    def get_log_files(self, collector):
        """获取日志文件列表"""
        all_logs = []
        
        for path in self.config['log_paths']:
            try:
                # 根据系统类型选择命令
                if collector.is_remote_windows():
                    # Windows系统使用dir命令
                    cmd = f'dir /O-D "{path}"'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        files = stdout.read().decode('gbk').splitlines()
                    except UnicodeDecodeError:
                        # 如果读取失败，重新执行命令
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        files = stdout.read().decode('utf-8', errors='ignore').splitlines()
                    
                    # 跳过Windows dir命令的头部信息
                    start_idx = 0
                    for i, line in enumerate(files):
                        if "Directory of" in line:
                            start_idx = i + 2
                            break
                    
                    files = files[start_idx:]
                    
                    # 解析文件信息
                    file_info_list = []
                    for line in files:
                        if not line.strip() or "<DIR>" in line:
                            continue
                        
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            # Windows dir命令格式: 日期 时间 大小 文件名
                            try:
                                date_str = parts[0]
                                time_str = parts[1]
                                # 文件名可能包含空格，所以要合并后面的所有部分
                                filename = ' '.join(parts[3:])
                                file_info_list.append({
                                    'name': filename,
                                    'date': f"{date_str} {time_str}",
                                    'path': path
                                })
                            except:
                                continue
                else:
                    # Linux系统使用ls命令
                    cmd = f'ls -1 {path}'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        files = stdout.read().decode('utf-8').splitlines()
                    except UnicodeDecodeError:
                        files = stdout.read().decode('gbk', errors='ignore').splitlines()
                
                # 过滤出支持的文件类型
                supported_files = []
                for file in files:
                    file = file.strip()
                    if collector.is_supported_file(file):
                        # 检查日期范围
                        if 'date_range' in self.config and self.config['date_range'].get('enabled', False):
                            start_date = datetime.strptime(
                                self.config['date_range']['start_date'], '%Y-%m-%d').date()
                            end_date = datetime.strptime(
                                self.config['date_range']['end_date'], '%Y-%m-%d').date()
                            
                            if collector.is_log_in_date_range(file, start_date, end_date):
                                full_path = f"{path.rstrip('/')}/{file}"
                                supported_files.append({
                                    'name': file,
                                    'path': full_path
                                })
                        else:
                            full_path = f"{path.rstrip('/')}/{file}"
                            supported_files.append({
                                'name': file,
                                'path': full_path
                            })
                
                all_logs.extend(supported_files)
            except Exception as e:
                self.error.emit(f"获取目录 {path} 中的日志列表失败: {str(e)}")
        
        # 发送日志列表信号
        self.log_list.emit(all_logs)
    
    def search_keyword(self, collector):
        """在日志文件中搜索关键字"""
        try:
            if not self.log_path or not self.keyword:
                self.error.emit("未指定日志文件或关键字")
                return
            
            self.log_message(f"准备搜索关键字: '{self.keyword}'")
            
            # 使用缓存管理
            file_name = os.path.basename(self.log_path)
            cache_file = self._get_cached_file(self.log_path, collector)
            
            # 在本地文件中搜索
            found_lines = []
            line_numbers = []
            
            try:
                # 尝试多种编码打开文件
                file_content = self._read_file_with_encoding(cache_file)
                
                # 搜索关键字
                for i, line in enumerate(file_content, 1):
                    if self.keyword in line:
                        found_lines.append(line.strip())
                        line_numbers.append(i)
                
                # 检查结果
                if found_lines:
                    self.log_message(f"找到 {len(found_lines)} 个匹配项")
                    self.search_result.emit(self.keyword, found_lines)
                    return
                else:
                    self.log_message("搜索未找到匹配结果")
                    self.search_result.emit(self.keyword, [])
                    return
            except Exception as e:
                self.error.emit(f"本地搜索方法失败: {str(e)}")
                # 如果本地搜索失败，继续尝试远程搜索方法
            
            # 以下是原来的远程搜索方法（作为备用）
            # 使用grep命令搜索关键字
            if collector.is_remote_windows():
                # Windows系统使用findstr命令
                cmd = f'findstr /n "{self.keyword}" "{self.log_path}"'
                if not self.keyword.isascii():  # 如果是非ASCII字符(如中文)
                    # 对于Windows系统中文搜索，使用type配合findstr
                    cmd = f'type "{self.log_path}" | findstr /n "{self.keyword}"'
            else:
                # Linux系统使用grep命令，添加字符集支持
                if not self.keyword.isascii():  # 如果是非ASCII字符(如中文)
                    # 尝试多种字符集编码
                    encoding_options = ["--binary-files=text", "--text"]
                    # 添加LC_ALL=zh_CN.UTF-8环境变量以支持中文
                    cmd = f'export LC_ALL=zh_CN.UTF-8 || export LC_ALL=C.UTF-8; grep -n {" ".join(encoding_options)} "{self.keyword}" {self.log_path}'
                else:
                    cmd = f'grep -n "{self.keyword}" {self.log_path}'
            
            self.log_message(f"执行搜索命令: {cmd}")
            
            stdin, stdout, stderr = collector.ssh.exec_command(cmd)
            stdout_data = stdout.read()
            stderr_data = stderr.read()
            
            if stderr_data:
                self.error.emit(f"搜索错误: {stderr_data.decode('utf-8', errors='ignore')}")
                
                # 如果第一次尝试失败且是中文关键字，再尝试一次其他方法
                if not self.keyword.isascii() and not collector.is_remote_windows():
                    self.log_message("尝试使用备用方法搜索中文关键字...")
                    # 使用grep -P (Perl正则模式)搜索
                    cmd2 = f'export LC_ALL=C.UTF-8; grep -P -n "{self.keyword}" {self.log_path} || grep -a -n "{self.keyword}" {self.log_path}'
                    self.log_message(f"执行备用搜索命令: {cmd2}")
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd2)
                    stdout_data = stdout.read()
            
            # 尝试多种编码格式
            try:
                results = stdout_data.decode('gbk').splitlines()
            except UnicodeDecodeError:
                try:
                    results = stdout_data.decode('utf-8').splitlines()
                except UnicodeDecodeError:
                    results = stdout_data.decode('utf-8', errors='ignore').splitlines()
            
            # 解析结果，提取行号
            parsed_results = []
            for line in results:
                try:
                    # 格式为"行号:内容"
                    parts = line.split(':', 1)
                    if len(parts) >= 2:
                        line_num = int(parts[0])
                        content = parts[1]
                        parsed_results.append({
                            'line': line_num,
                            'content': content
                        })
                except Exception as e:
                    self.error.emit(f"解析搜索结果失败: {str(e)}, 行内容: {line}")
            
            # 如果找到了匹配项，获取最早和最晚的行号
            if parsed_results:
                min_line = min(r['line'] for r in parsed_results)
                max_line = max(r['line'] for r in parsed_results)
                
                # 获取这个范围内的所有行
                if collector.is_remote_windows():
                    # Windows使用更简单的命令，避免PowerShell复杂性
                    line_range = max_line - min_line + 1
                    cmd = f'more +{min_line-1} "{self.log_path}" | findstr /n "^" | findstr /b "[1-{line_range}]:"'
                else:
                    # Linux使用sed命令
                    cmd = f'sed -n "{min_line},{max_line}p" {self.log_path}'
                
                stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                stdout_data = stdout.read()
                stderr_data = stderr.read()
                
                if stderr_data:
                    self.error.emit(f"获取内容错误: {stderr_data.decode('utf-8', errors='ignore')}")
                
                # 尝试多种编码格式
                try:
                    complete_results = stdout_data.decode('gbk').splitlines()
                except UnicodeDecodeError:
                    try:
                        complete_results = stdout_data.decode('utf-8').splitlines()
                    except UnicodeDecodeError:
                        complete_results = stdout_data.decode('utf-8', errors='ignore').splitlines()
                
                # 去除行号前缀
                processed_results = []
                for line in complete_results:
                    parts = line.split(':', 1)
                    if len(parts) >= 2:
                        processed_results.append(parts[1])
                    else:
                        processed_results.append(line)
                
                # 发送搜索结果信号
                self.search_result.emit(self.keyword, processed_results)
            else:
                # 如果使用第一种方法没找到，尝试使用strings命令过滤二进制文件然后grep
                if not self.keyword.isascii() and not collector.is_remote_windows():
                    self.log_message("尝试使用strings命令搜索二进制文件...")
                    cmd3 = f'strings "{self.log_path}" | grep -n "{self.keyword}"'
                    self.log_message(f"执行strings搜索命令: {cmd3}")
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd3)
                    stdout_data = stdout.read()
                    
                    if stdout_data:
                        try:
                            results = stdout_data.decode('utf-8', errors='ignore').splitlines()
                            if results:
                                self.search_result.emit(self.keyword, results)
                                return
                        except:
                            pass
                
                self.search_result.emit(self.keyword, [])
                self.log_message(f"未找到包含关键字 '{self.keyword}' 的内容")
        except Exception as e:
            self.error.emit(f"搜索关键字失败: {str(e)}")
    
    def get_full_log(self, collector):
        """获取完整日志内容"""
        try:
            if not self.log_path:
                self.error.emit("未指定日志文件")
                return
            
            # 检查文件大小
            if collector.is_remote_windows():
                cmd = f'powershell -Command "(Get-Item \'{self.log_path}\').length"'
            else:
                cmd = f'stat -c %s {self.log_path}'
            
            stdin, stdout, stderr = collector.ssh.exec_command(cmd)
            size_str = stdout.read().decode('utf-8', errors='ignore').strip()
            
            try:
                size = int(size_str)
                if size > 10 * 1024 * 1024:  # 大于10MB
                    self.error.emit(f"文件太大 ({size/1024/1024:.1f}MB)，请使用关键字搜索缩小范围")
                    return
            except:
                pass  # 忽略转换错误，继续尝试获取文件
            
            # 使用缓存管理
            cache_file = self._get_cached_file(self.log_path, collector)
            
            # 读取文件内容
            try:
                log_content = self._read_file_content(cache_file)
                
                # 发送完整日志信号
                self.complete_log.emit(log_content)
                return
            except Exception as e:
                self.error.emit(f"本地文件读取失败: {str(e)}")
                # 如果本地下载失败，继续尝试远程读取方法
            
            # 以下是原来的远程获取方法（作为备用）
            # 获取文件内容
            if collector.is_remote_windows():
                # 对于Windows系统，确保使用正确的命令和编码
                cmd = f'type "{self.log_path}"'
            else:
                cmd = f'cat {self.log_path}'
            
            stdin, stdout, stderr = collector.ssh.exec_command(cmd)
            stdout_data = stdout.read()
            stderr_data = stderr.read()
            
            if stderr_data:
                self.error.emit(f"获取日志内容错误: {stderr_data.decode('utf-8', errors='ignore')}")
            
            # 优先尝试GBK编码（中文Windows系统常用）
            try:
                log_content = stdout_data.decode('gbk')
            except UnicodeDecodeError:
                try:
                    # 如果GBK失败，尝试UTF-8
                    log_content = stdout_data.decode('utf-8')
                except UnicodeDecodeError:
                    # 最后使用带错误忽略的UTF-8
                    log_content = stdout_data.decode('utf-8', errors='ignore')
                    self.error.emit("警告：日志内容编码不匹配，可能有乱码")
            
            # 发送完整日志信号
            self.complete_log.emit(log_content)
        except Exception as e:
            self.error.emit(f"获取日志内容失败: {str(e)}")
    
    def _get_cached_file(self, remote_path, collector):
        """获取缓存的文件，如果缓存不存在则下载"""
        # 确保缓存目录存在
        import tempfile
        import hashlib
        
        # 创建缓存目录
        cache_dir = os.path.join(tempfile.gettempdir(), "log_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 计算缓存文件名（使用远程路径的哈希作为文件名）
        file_hash = hashlib.md5(remote_path.encode()).hexdigest()
        file_name = os.path.basename(remote_path)
        cache_file = os.path.join(cache_dir, f"{file_hash}_{file_name}")
        
        # 如果缓存不存在，则下载
        if not os.path.exists(cache_file):
            self.log_message(f"缓存不存在，下载文件: {remote_path}")
            collector.sftp.get(remote_path, cache_file)
            self.log_message(f"文件已下载到缓存: {cache_file}")
        else:
            self.log_message(f"使用缓存文件: {cache_file}")
        
        return cache_file
    
    def _read_file_with_encoding(self, file_path):
        """尝试多种编码读取文件为行列表"""
        # 尝试多种编码打开文件
        encodings = ['gbk', 'utf-8', 'gb18030', 'latin1']
        file_content = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    file_content = f.readlines()
                self.log_message(f"成功使用编码 {encoding} 打开文件")
                break
            except UnicodeDecodeError:
                continue
        
        if not file_content:
            # 如果所有编码都失败，使用二进制模式读取并手动处理
            with open(file_path, 'rb') as f:
                binary_content = f.read()
                try:
                    file_content = binary_content.decode('gbk', errors='ignore').splitlines(True)
                except:
                    file_content = binary_content.decode('utf-8', errors='ignore').splitlines(True)
            self.log_message("使用二进制模式读取文件并手动解码")
        
        return file_content
    
    def _read_file_content(self, file_path):
        """尝试多种编码读取文件为字符串"""
        # 尝试多种编码打开文件
        encodings = ['gbk', 'utf-8', 'gb18030', 'latin1']
        file_content = None
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    file_content = f.read()
                self.log_message(f"成功使用编码 {encoding} 打开文件")
                break
            except UnicodeDecodeError:
                continue
        
        if not file_content:
            # 如果所有编码都失败，使用二进制模式读取并手动处理
            with open(file_path, 'rb') as f:
                binary_content = f.read()
                try:
                    file_content = binary_content.decode('gbk', errors='ignore')
                except:
                    file_content = binary_content.decode('utf-8', errors='ignore')
            self.log_message("使用二进制模式读取文件并手动解码")
        
        return file_content

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("车道系统日志收集分析工具")
        self.setMinimumSize(800, 600)
        
        # 主机配置数据
        self.hosts_data = []
        
        # 创建主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        
        # 主机选择区域
        host_select_group = QGroupBox("主机选择")
        host_select_layout = QHBoxLayout(host_select_group)
        
        host_label = QLabel("选择主机:")
        self.host_combo = QComboBox()
        self.host_combo.setMinimumWidth(200)
        manage_hosts_btn = QPushButton("管理主机")
        
        host_select_layout.addWidget(host_label)
        host_select_layout.addWidget(self.host_combo)
        host_select_layout.addWidget(manage_hosts_btn)
        host_select_layout.addStretch(1)
        
        # 连接主机选择变化信号
        self.host_combo.currentIndexChanged.connect(self.on_host_changed)
        manage_hosts_btn.clicked.connect(self.manage_hosts)
        
        # SSH连接设置
        ssh_group = QGroupBox("SSH连接设置")
        ssh_layout = QVBoxLayout(ssh_group)
        
        # 主机设置
        host_layout = QHBoxLayout()
        host_label = QLabel("主机地址:")
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("例如: 192.168.1.100")
        port_label = QLabel("端口:")
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(22)
        host_layout.addWidget(host_label)
        host_layout.addWidget(self.host_input)
        host_layout.addWidget(port_label)
        host_layout.addWidget(self.port_input)
        
        # 用户名密码设置
        credentials_layout = QHBoxLayout()
        username_label = QLabel("用户名:")
        self.username_input = QLineEdit()
        password_label = QLabel("密码:")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        credentials_layout.addWidget(username_label)
        credentials_layout.addWidget(self.username_input)
        credentials_layout.addWidget(password_label)
        credentials_layout.addWidget(self.password_input)
        
        ssh_layout.addLayout(host_layout)
        ssh_layout.addLayout(credentials_layout)
        
        # 创建选项卡窗口
        self.tab_widget = QTabWidget()
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 创建日志收集选项卡
        collection_tab = QWidget()
        collection_layout = QVBoxLayout(collection_tab)
        
        # 日期选择
        date_group = QGroupBox("日期设置")
        date_layout = QVBoxLayout(date_group)
        
        # 日期范围选择
        date_range_layout = QHBoxLayout()
        self.use_date_range = QCheckBox("使用日期范围")
        self.use_date_range.setChecked(True)
        date_range_layout.addWidget(self.use_date_range)
        
        # 开始日期
        start_date_layout = QHBoxLayout()
        start_date_label = QLabel("开始日期:")
        self.start_date = QDateEdit()
        self.start_date.setDate(QDate.currentDate().addDays(-1))  # 默认昨天
        self.start_date.setCalendarPopup(True)
        start_date_layout.addWidget(start_date_label)
        start_date_layout.addWidget(self.start_date)
        
        # 结束日期
        end_date_layout = QHBoxLayout()
        end_date_label = QLabel("结束日期:")
        self.end_date = QDateEdit()
        self.end_date.setDate(QDate.currentDate())  # 默认今天
        self.end_date.setCalendarPopup(True)
        end_date_layout.addWidget(end_date_label)
        end_date_layout.addWidget(self.end_date)
        
        date_range_layout.addLayout(start_date_layout)
        date_range_layout.addLayout(end_date_layout)
        date_layout.addLayout(date_range_layout)
        
        # 添加日期说明
        date_info = QLabel("注意：将自动匹配文件名中包含选定日期范围的日志文件\n支持的文件名格式：xxxx_YYYY-MM-DD.log 或 xxxx_YYYY-MM-DD.zip")
        date_info.setStyleSheet("color: gray;")
        date_layout.addWidget(date_info)
        
        # 日志路径列表
        path_group = QGroupBox("日志文件路径")
        path_layout = QVBoxLayout(path_group)
        
        # 添加路径说明
        path_info = QLabel("请输入日志文件所在的目录，程序会自动查找并下载符合日期条件的日志文件\n支持的文件类型：.log 和 .zip")
        path_info.setStyleSheet("color: gray;")
        path_layout.addWidget(path_info)
        
        # 创建路径列表和按钮的完整容器
        path_list_container = QWidget()
        path_list_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        path_list_layout = QVBoxLayout(path_list_container)
        path_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加路径列表
        self.path_list = QListWidget()
        self.path_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        path_list_layout.addWidget(self.path_list, 1)  # 1是拉伸因子，让列表获得尽可能多的空间
        
        # 路径操作按钮容器，使用水平布局
        path_buttons_container = QWidget()
        path_buttons_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        path_buttons = QHBoxLayout(path_buttons_container)
        path_buttons.setContentsMargins(0, 0, 0, 0)
        
        # 添加按钮
        add_path_btn = QPushButton("添加目录")
        remove_path_btn = QPushButton("删除选中")
        path_buttons.addWidget(add_path_btn)
        path_buttons.addWidget(remove_path_btn)
        path_buttons.addStretch(1)  # 添加空白区域推开按钮
        
        # 添加按钮区域到列表容器
        path_list_layout.addWidget(path_buttons_container)
        
        # 将完整容器添加到路径组布局
        path_layout.addWidget(path_list_container)
        
        # 连接按钮事件
        add_path_btn.clicked.connect(self.add_path)
        remove_path_btn.clicked.connect(self.remove_path)
        
        # 进度显示
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        # 日志显示
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        log_layout.addWidget(self.log_display)
        
        # 操作按钮
        button_layout = QHBoxLayout()
        list_files_btn = QPushButton("列出最新文件")
        list_files_btn.clicked.connect(self.list_files)
        self.start_button = QPushButton("开始收集")
        self.start_button.clicked.connect(self.start_collection)
        button_layout.addWidget(list_files_btn)
        button_layout.addWidget(self.start_button)
        
        # 将组件添加到日志收集选项卡
        collection_layout.addWidget(date_group)
        collection_layout.addWidget(path_group)
        collection_layout.addWidget(self.progress_bar)
        collection_layout.addWidget(log_group)
        collection_layout.addLayout(button_layout)
        
        # 创建日志分析选项卡
        analysis_tab = QWidget()
        analysis_layout = QVBoxLayout(analysis_tab)
        
        # 创建分析选项卡的主分割器（上下布局）
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 上半部分：日期选择和日志列表（并列布局）
        upper_widget = QWidget()
        upper_layout = QHBoxLayout(upper_widget)  # 改为水平布局
        
        # 左侧：日期设置部分
        date_container = QWidget()
        date_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        date_container_layout = QVBoxLayout(date_container)
        
        # 创建日期范围选择
        date_group_analysis = QGroupBox("日期设置")
        date_layout_analysis = QVBoxLayout(date_group_analysis)
        
        # 日期范围选择
        date_range_layout_analysis = QHBoxLayout()
        self.use_date_range_analysis = QCheckBox("使用日期范围")
        self.use_date_range_analysis.setChecked(True)
        date_range_layout_analysis.addWidget(self.use_date_range_analysis)
        
        # 开始日期
        start_date_layout_analysis = QHBoxLayout()
        start_date_label_analysis = QLabel("开始日期:")
        self.start_date_analysis = QDateEdit()
        self.start_date_analysis.setDate(QDate.currentDate().addDays(-1))  # 默认昨天
        self.start_date_analysis.setCalendarPopup(True)
        start_date_layout_analysis.addWidget(start_date_label_analysis)
        start_date_layout_analysis.addWidget(self.start_date_analysis)
        
        # 结束日期
        end_date_layout_analysis = QHBoxLayout()
        end_date_label_analysis = QLabel("结束日期:")
        self.end_date_analysis = QDateEdit()
        self.end_date_analysis.setDate(QDate.currentDate())  # 默认今天
        self.end_date_analysis.setCalendarPopup(True)
        end_date_layout_analysis.addWidget(end_date_label_analysis)
        end_date_layout_analysis.addWidget(self.end_date_analysis)
        
        date_range_layout_analysis.addLayout(start_date_layout_analysis)
        date_range_layout_analysis.addLayout(end_date_layout_analysis)
        date_layout_analysis.addLayout(date_range_layout_analysis)
        
        # 获取日志列表按钮
        logs_btn_layout = QHBoxLayout()
        get_logs_btn = QPushButton("获取日志列表")
        get_logs_btn.clicked.connect(self.get_log_list)
        logs_btn_layout.addWidget(get_logs_btn)
        logs_btn_layout.addStretch(1)
        date_layout_analysis.addLayout(logs_btn_layout)
        
        date_container_layout.addWidget(date_group_analysis)
        date_container_layout.addStretch(1)  # 添加弹性空间，使日期控件在顶部
        
        # 右侧：日志列表框
        log_list_container = QWidget()
        log_list_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_list_layout = QVBoxLayout(log_list_container)
        
        log_list_group = QGroupBox("日志文件列表")
        log_list_inner_layout = QVBoxLayout(log_list_group)
        
        self.log_list_widget = QListWidget()
        self.log_list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        log_list_inner_layout.addWidget(self.log_list_widget)
        
        log_list_layout.addWidget(log_list_group)
        
        # 将左右两部分添加到上半部分布局
        upper_layout.addWidget(date_container, 1)  # 1是拉伸因子
        upper_layout.addWidget(log_list_container, 3)  # 日志列表占更多空间
        
        # 中间部分：关键字搜索
        middle_widget = QWidget()
        middle_layout = QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)  # 减小边距
        
        # 关键字搜索
        keyword_group = QGroupBox("关键字搜索")
        keyword_layout = QVBoxLayout(keyword_group)
        keyword_layout.setContentsMargins(9, 9, 9, 9)  # 减小内边距
        
        keyword_input_layout = QHBoxLayout()
        keyword_label = QLabel("关键字:")
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("输入要搜索的关键字")
        search_btn = QPushButton("搜索")
        search_btn.clicked.connect(self.search_keyword)
        view_full_btn = QPushButton("查看完整日志")
        view_full_btn.clicked.connect(self.view_full_log)
        
        keyword_input_layout.addWidget(keyword_label)
        keyword_input_layout.addWidget(self.keyword_input)
        keyword_input_layout.addWidget(search_btn)
        keyword_input_layout.addWidget(view_full_btn)
        
        keyword_layout.addLayout(keyword_input_layout)
        middle_layout.addWidget(keyword_group)
        
        # 下半部分：搜索结果和操作日志（并列布局）
        lower_widget = QWidget()
        lower_layout = QHBoxLayout(lower_widget)  # 水平布局
        
        # 左侧：搜索结果
        result_group = QGroupBox("搜索结果")
        result_layout = QVBoxLayout(result_group)
        
        self.result_display = QTextEdit()
        self.result_display.setReadOnly(True)
        result_layout.addWidget(self.result_display)
        
        # 导出按钮
        export_layout = QHBoxLayout()
        export_btn = QPushButton("导出结果")
        export_btn.clicked.connect(self.export_results)
        export_layout.addStretch(1)
        export_layout.addWidget(export_btn)
        result_layout.addLayout(export_layout)
        
        # 右侧：操作日志记录
        analysis_log_group = QGroupBox("操作日志")
        analysis_log_layout = QVBoxLayout(analysis_log_group)
        analysis_log_layout.setContentsMargins(9, 9, 9, 9)  # 减小内边距
        
        self.analysis_log_display = QTextEdit()
        self.analysis_log_display.setReadOnly(True)
        analysis_log_layout.addWidget(self.analysis_log_display)
        
        # 添加到下半部分布局
        lower_layout.addWidget(result_group, 3)  # 搜索结果占更多空间
        lower_layout.addWidget(analysis_log_group, 1)
        
        # 将所有部分添加到主分割器
        main_splitter.addWidget(upper_widget)
        main_splitter.addWidget(middle_widget)
        main_splitter.addWidget(lower_widget)
        
        # 设置初始大小比例
        main_splitter.setSizes([300, 80, 400])  # 上半部分更大，中间部分更小
        
        # 将主分割器添加到分析布局
        analysis_layout.addWidget(main_splitter)
        
        # 更新分析选项卡
        analysis_tab.setLayout(analysis_layout)
        
        # 添加选项卡
        self.tab_widget.addTab(collection_tab, "日志收集")
        self.tab_widget.addTab(analysis_tab, "日志分析")
        
        # 添加所有组件到主布局
        main_layout.addWidget(host_select_group)
        main_layout.addWidget(ssh_group)
        main_layout.addWidget(self.tab_widget)
        
        # 设置所有组件为自适应大小
        host_select_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        ssh_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        date_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        path_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        log_group.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 加载配置
        self.load_config()
        # 加载主机列表
        self.load_hosts_data()
    
    def load_hosts_data(self):
        """加载主机数据到下拉框"""
        try:
            hosts_file_path = self.get_hosts_file_path()
            if os.path.exists(hosts_file_path):
                with open(hosts_file_path, 'r', encoding='utf-8') as f:
                    self.hosts_data = yaml.safe_load(f) or []
            else:
                self.hosts_data = []
                
            # 更新下拉框
            self.update_hosts_combo()
        except Exception as e:
            self.log_message(f"加载主机列表失败: {str(e)}")
    
    def update_hosts_combo(self):
        """更新主机下拉框"""
        self.host_combo.clear()
        self.host_combo.addItem("-- 请选择主机 --", None)
        
        for i, host in enumerate(self.hosts_data):
            self.host_combo.addItem(host.get("name", f"未命名主机{i+1}"), i)
    
    def on_host_changed(self, index):
        """主机选择变化时更新界面"""
        if index <= 0:  # 没有选择有效主机
            return
        
        host_index = self.host_combo.currentData()
        if host_index is not None and host_index < len(self.hosts_data):
            host_data = self.hosts_data[host_index]
            
            # 更新SSH信息
            self.host_input.setText(host_data.get("ssh", {}).get("host", ""))
            self.port_input.setValue(host_data.get("ssh", {}).get("port", 22))
            self.username_input.setText(host_data.get("ssh", {}).get("username", ""))
            self.password_input.setText(host_data.get("ssh", {}).get("password", ""))
            
            # 更新路径列表
            self.path_list.clear()
            for path in host_data.get("log_paths", []):
                self.path_list.addItem(path)
    
    def manage_hosts(self):
        """打开主机管理对话框"""
        dialog = HostManagerDialog(self, self.hosts_data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.hosts_data = dialog.get_hosts_data()
            self.save_hosts_data()
            self.update_hosts_combo()
    
    def save_hosts_data(self):
        """保存主机数据到文件"""
        try:
            hosts_file_path = self.get_hosts_file_path()
            with open(hosts_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.hosts_data, f, allow_unicode=True)
        except Exception as e:
            self.log_message(f"保存主机列表失败: {str(e)}")
    
    def get_hosts_file_path(self):
        """获取主机配置文件路径"""
        if getattr(sys, 'frozen', False):
            # 如果是打包后的exe，保存在exe所在目录
            base_path = os.path.dirname(sys.executable)
        else:
            # 如果是开发环境
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        return os.path.join(base_path, 'hosts.yaml')
    
    def load_config(self):
        try:
            # 获取配置文件路径
            if getattr(sys, 'frozen', False):
                # 如果是打包后的exe
                base_path = sys._MEIPASS
            else:
                # 如果是开发环境
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            config_path = os.path.join(base_path, 'config.yaml')
            
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                self.host_input.setText(config['ssh'].get('host', ''))
                self.port_input.setValue(config['ssh'].get('port', 22))
                self.username_input.setText(config['ssh'].get('username', ''))
                self.password_input.setText(config['ssh'].get('password', ''))
                
                for path in config.get('log_paths', []):
                    if path and path.strip() != "/path/to/logs":
                        self.path_list.addItem(path)
        except Exception as e:
            self.log_message(f"加载配置文件失败: {str(e)}")
            # 使用默认配置
            self.host_input.setText("")
            self.port_input.setValue(22)
            self.username_input.setText("")
            self.password_input.setText("")
    
    def save_config(self):
        # 获取当前选择的主机索引
        host_index = self.host_combo.currentData()
        if host_index is not None and host_index < len(self.hosts_data):
            # 更新主机数据
            self.hosts_data[host_index]["ssh"] = {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            }
            self.hosts_data[host_index]["log_paths"] = [
                self.path_list.item(i).text() 
                for i in range(self.path_list.count())
            ]
            
            # 保存主机列表
            self.save_hosts_data()
        
        # 保存常规配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            },
            'log_paths': [self.path_list.item(i).text() 
                         for i in range(self.path_list.count())]
        }
        
        try:
            # 获取配置文件保存路径
            if getattr(sys, 'frozen', False):
                # 如果是打包后的exe，保存在exe所在目录
                base_path = os.path.dirname(sys.executable)
            else:
                # 如果是开发环境
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            config_path = os.path.join(base_path, 'config.yaml')
            
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, allow_unicode=True)
        except Exception as e:
            self.log_message(f"保存配置文件失败: {str(e)}")
    
    def add_path(self):
        dialog = PathInputDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            path = dialog.get_path()
            if path:
                self.path_list.addItem(path)
    
    def remove_path(self):
        current_item = self.path_list.currentItem()
        if current_item:
            self.path_list.takeItem(self.path_list.row(current_item))
    
    def log_message(self, message):
        """添加日志消息到日志显示框"""
        time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        formatted_message = f"{time_str} {message}"
        # 添加到日志收集选项卡的日志显示框
        self.log_display.append(formatted_message)
        # 添加到日志分析选项卡的日志显示框（如果已创建）
        if hasattr(self, 'analysis_log_display'):
            self.analysis_log_display.append(formatted_message)
    
    def get_date_range(self):
        if self.use_date_range.isChecked():
            start_date = self.start_date.date().toPyDate()
            end_date = self.end_date.date().toPyDate()
            return start_date, end_date
        return None, None
    
    def list_files(self):
        if not self.host_input.text() or not self.username_input.text():
            QMessageBox.warning(self, "错误", "请填写主机地址和用户名")
            return
        
        if self.path_list.count() == 0:
            QMessageBox.warning(self, "错误", "请添加至少一个日志文件路径")
            return
        
        # 准备配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            },
            'log_paths': [self.path_list.item(i).text() 
                         for i in range(self.path_list.count())]
        }
        
        # 禁用按钮
        self.start_button.setEnabled(False)
        self.log_message("正在获取文件列表...")
        
        # 创建工作线程
        self.worker = LogCollectorWorker(config, mode='list')
        self.worker.finished.connect(self.collection_finished)
        self.worker.error.connect(self.collection_error)
        self.worker.file_list.connect(self.show_file_list)
        self.worker.start()
    
    def show_file_list(self, file_info_list):
        if not file_info_list:
            self.log_message("目录为空或无法访问")
            return
            
        self.log_message("\n最新文件列表:")
        for info in file_info_list:
            self.log_message(f"目录: {info['path']}")
            self.log_message(f"文件: {info['name']}")
            self.log_message(f"日期: {info['date']}")
            self.log_message("-" * 50)
        
        self.start_button.setEnabled(True)
    
    def start_collection(self):
        if not self.host_input.text() or not self.username_input.text():
            QMessageBox.warning(self, "错误", "请填写主机地址和用户名")
            return
        
        if self.path_list.count() == 0:
            QMessageBox.warning(self, "错误", "请添加至少一个日志文件路径")
            return
        
        # 检查日期范围
        start_date, end_date = self.get_date_range()
        if start_date and end_date and start_date > end_date:
            QMessageBox.warning(self, "错误", "开始日期不能晚于结束日期")
            return
        
        # 保存当前配置
        self.save_config()
        
        # 准备配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            },
            'log_paths': [self.path_list.item(i).text() 
                         for i in range(self.path_list.count())],
            'date_range': {
                'enabled': self.use_date_range.isChecked(),
                'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
                'end_date': end_date.strftime('%Y-%m-%d') if end_date else None
            }
        }
        
        # 禁用开始按钮
        self.start_button.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # 创建工作线程
        self.worker = LogCollectorWorker(config)
        self.worker.finished.connect(self.collection_finished)
        self.worker.error.connect(self.collection_error)
        self.worker.progress.connect(self.update_progress)
        self.worker.start()
        
        self.log_message("开始收集日志文件...")
    
    def update_progress(self, filename, current, total):
        """
        更新进度条显示
        """
        if total <= 0:
            # 防止除零错误
            percent = 0
        else:
            percent = int(current * 100 / total)
        
        self.progress_bar.setValue(percent)
        self.log_message(f"正在下载: {filename} ({percent}%)")
    
    def collection_finished(self, zip_path):
        self.start_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        if zip_path:
            self.log_message(f"日志收集完成！文件保存在: {zip_path}")
            QMessageBox.information(self, "完成", f"日志收集完成！\n文件保存在: {zip_path}")
        else:
            self.log_message("没有找到符合条件的日志文件")
            QMessageBox.warning(self, "提示", "在指定的目录中没有找到符合日期条件的日志文件。\n请检查：\n1. 日期范围是否正确\n2. 目录中是否存在对应日期的日志文件")
    
    def collection_error(self, error_message):
        self.start_button.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.log_message(f"错误: {error_message}")
        QMessageBox.critical(self, "错误", f"操作失败：\n{error_message}")

    def get_log_list(self):
        """获取日志列表"""
        if not self.host_input.text() or not self.username_input.text():
            QMessageBox.warning(self, "错误", "请填写主机地址和用户名")
            return
        
        if self.path_list.count() == 0:
            QMessageBox.warning(self, "错误", "请添加至少一个日志文件路径")
            return
        
        # 检查日期范围
        start_date, end_date = self.get_date_range_analysis()
        if start_date and end_date and start_date > end_date:
            QMessageBox.warning(self, "错误", "开始日期不能晚于结束日期")
            return
        
        # 准备配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            },
            'log_paths': [self.path_list.item(i).text() 
                         for i in range(self.path_list.count())],
            'date_range': {
                'enabled': self.use_date_range_analysis.isChecked(),
                'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
                'end_date': end_date.strftime('%Y-%m-%d') if end_date else None
            }
        }
        
        # 清空日志列表
        self.log_list_widget.clear()
        self.result_display.clear()
        
        # 显示加载信息
        self.log_message("正在获取日志列表...")
        
        # 创建工作线程
        self.analysis_worker = LogAnalysisWorker(config, mode='list')
        self.analysis_worker.log_list.connect(self.display_log_list)
        self.analysis_worker.error.connect(self.analysis_error)
        self.analysis_worker.log_message_signal.connect(self.log_message)
        self.analysis_worker.start()
    
    def get_date_range_analysis(self):
        """获取分析选项卡的日期范围"""
        if self.use_date_range_analysis.isChecked():
            start_date = self.start_date_analysis.date().toPyDate()
            end_date = self.end_date_analysis.date().toPyDate()
            return start_date, end_date
        return None, None
    
    def display_log_list(self, logs):
        """显示日志列表"""
        if not logs:
            self.log_message("没有找到符合条件的日志文件")
            return
        
        self.log_list_widget.clear()
        for log in logs:
            item = QListWidgetItem(f"{log['name']}")
            item.setData(Qt.ItemDataRole.UserRole, log['path'])  # 存储完整路径
            self.log_list_widget.addItem(item)
        
        self.log_message(f"找到 {len(logs)} 个日志文件")
    
    def search_keyword(self):
        """在选中的日志中搜索关键字"""
        current_item = self.log_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "错误", "请先选择一个日志文件")
            return
        
        keyword = self.keyword_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "错误", "请输入关键字")
            return
        
        # 获取日志文件路径
        log_path = current_item.data(Qt.ItemDataRole.UserRole)
        
        # 准备配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            }
        }
        
        # 清空结果显示
        self.result_display.clear()
        self.log_message(f"正在 {current_item.text()} 中搜索关键字: {keyword}")
        
        # 创建工作线程
        self.analysis_worker = LogAnalysisWorker(
            config, mode='search', log_path=log_path, keyword=keyword)
        self.analysis_worker.search_result.connect(self.display_search_result)
        self.analysis_worker.error.connect(self.analysis_error)
        self.analysis_worker.log_message_signal.connect(self.log_message)
        self.analysis_worker.start()
    
    def view_full_log(self):
        """查看完整日志"""
        current_item = self.log_list_widget.currentItem()
        if not current_item:
            QMessageBox.warning(self, "错误", "请先选择一个日志文件")
            return
        
        # 获取日志文件路径
        log_path = current_item.data(Qt.ItemDataRole.UserRole)
        
        # 准备配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            }
        }
        
        # 清空结果显示
        self.result_display.clear()
        self.log_message(f"正在获取 {current_item.text()} 的完整内容...")
        
        # 创建工作线程
        self.analysis_worker = LogAnalysisWorker(
            config, mode='get_log', log_path=log_path)
        self.analysis_worker.complete_log.connect(self.display_full_log)
        self.analysis_worker.error.connect(self.analysis_error)
        self.analysis_worker.log_message_signal.connect(self.log_message)
        self.analysis_worker.start()
    
    def display_search_result(self, keyword, results):
        """显示搜索结果"""
        if not results:
            self.result_display.setPlainText(f"未找到包含关键字 '{keyword}' 的内容")
            return
        
        # 显示结果
        self.result_display.setPlainText("\n".join(results))
        self.log_message(f"找到 {len(results)} 行包含关键字 '{keyword}'")
    
    def display_full_log(self, log_content):
        """显示完整日志"""
        self.result_display.setPlainText(log_content)
        lines = log_content.count('\n') + 1
        self.log_message(f"显示完整日志，共 {lines} 行")
    
    def export_results(self):
        """导出搜索结果"""
        content = self.result_display.toPlainText()
        if not content:
            QMessageBox.warning(self, "错误", "没有可导出的内容")
            return
        
        # 获取保存文件路径
        current_item = self.log_list_widget.currentItem()
        default_name = "analysis_result.txt"
        if current_item:
            file_name = current_item.text()
            if "." in file_name:
                prefix = file_name.rsplit(".", 1)[0]
                default_name = f"{prefix}_analysis.txt"
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", default_name, "文本文件 (*.txt)")
        
        if not file_path:
            return  # 用户取消了保存
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            self.log_message(f"结果已保存到 {file_path}")
            QMessageBox.information(self, "成功", f"结果已保存到:\n{file_path}")
        except Exception as e:
            self.log_message(f"保存结果失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"保存结果失败:\n{str(e)}")
    
    def analysis_error(self, error_message):
        """处理分析过程中的错误"""
        self.log_message(f"错误: {error_message}")
        QMessageBox.critical(self, "错误", f"操作失败：\n{error_message}")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 