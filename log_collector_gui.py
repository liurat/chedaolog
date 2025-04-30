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
                           QSizePolicy, QListWidgetItem, QSplitter, QGridLayout,
                           QProgressDialog)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from log_collector import LogCollector
import re
import functools
import io
import zipfile
import tempfile
import shutil

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
            # 检查是否为本地测试模式
            if self.is_local_test_mode():
                self.handle_local_test_mode()
                return
                
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
                                        except Exception:
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

    def is_local_test_mode(self):
        """检查是否为本地测试模式"""
        return (self.config.get('ssh', {}).get('host') == '127.0.0.1' and 
                self.config.get('ssh', {}).get('username') == 'liurat' and 
                self.config.get('ssh', {}).get('password') == '123456')
    
    def handle_local_test_mode(self):
        """处理本地测试模式"""
        try:
            if self.mode == 'collect':
                self.collect_local_logs()
            elif self.mode == 'list':
                self.list_local_files()
        except Exception as e:
            self.error.emit(f"本地测试模式出错: {str(e)}")
    
    def list_local_files(self):
        """列出本地测试目录中的文件"""
        try:
            file_info_list = []
            
            # 遍历所有日志路径
            for path in self.config['log_paths']:
                if os.path.exists(path) and os.path.isdir(path):
                    # 获取目录中的所有文件
                    files = os.listdir(path)
                    
                    for file in files:
                        file_path = os.path.join(path, file)
                        if os.path.isfile(file_path):
                            # 获取文件修改时间
                            mod_time = os.path.getmtime(file_path)
                            date_str = datetime.fromtimestamp(mod_time).strftime('%Y-%m-%d %H:%M:%S')
                            
                            file_info_list.append({
                                'name': file,
                                'date': date_str,
                                'path': path
                            })
            
            # 按修改时间排序
            file_info_list.sort(key=lambda x: x['date'], reverse=True)
            
            # 仅发送前10个文件
            self.file_list.emit(file_info_list[:10])
        except Exception as e:
            self.error.emit(f"列出本地文件失败: {str(e)}")
    
    def collect_local_logs(self):
        """从本地测试目录收集日志"""
        import zipfile
        import tempfile
        import shutil
        
        # 创建临时目录存放收集的日志
        temp_dir = tempfile.mkdtemp()
        zip_path = None
        
        try:
            # 要收集的文件列表
            collected_files = []
            
            # 遍历所有日志路径
            for path in self.config['log_paths']:
                if os.path.exists(path) and os.path.isdir(path):
                    # 获取目录中的所有文件
                    files = os.listdir(path)
                    
                    # 筛选符合条件的文件
                    for file in files:
                        file_path = os.path.join(path, file)
                        if os.path.isfile(file_path):
                            # 检查文件类型
                            if file.endswith('.log') or file.endswith('.zip'):
                                # 检查日期范围（如果有设置）
                                if self.config.get('use_date_range', False):
                                    start_date = datetime.strptime(self.config.get('start_date', ''), '%Y-%m-%d')
                                    end_date = datetime.strptime(self.config.get('end_date', ''), '%Y-%m-%d')
                                    end_date = end_date.replace(hour=23, minute=59, second=59)  # 设置为当天结束时间
                                    
                                    # 尝试从文件名中提取日期
                                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file)
                                    if date_match:
                                        file_date_str = date_match.group(1)
                                        try:
                                            file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                                            if not (start_date <= file_date <= end_date):
                                                continue  # 跳过不在日期范围内的文件
                                        except ValueError:
                                            pass  # 解析失败，保留文件
                                
                                # 将文件添加到收集列表
                                collected_files.append(file_path)
                                
                                # 复制文件到临时目录
                                dest_path = os.path.join(temp_dir, file)
                                shutil.copy2(file_path, dest_path)
                                
                                # 更新进度
                                file_size = os.path.getsize(file_path)
                                self.update_progress(file, file_size, file_size)
            
            if collected_files:
                # 创建zip文件
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                zip_path = os.path.join(os.path.expanduser('~'), f'logs_{timestamp}.zip')
                
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in os.listdir(temp_dir):
                        file_path = os.path.join(temp_dir, file)
                        zipf.write(file_path, arcname=file)
                
                # 发送完成信号
                self.finished.emit(zip_path)
            else:
                self.error.emit("没有找到符合条件的日志文件")
                
        except Exception as e:
            self.error.emit(f"收集日志失败: {str(e)}")
        finally:
            # 清理临时目录
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
    
    def update_progress(self, filename, current, total):
        """更新进度信号"""
        self.progress.emit(filename, current, total)

class PathInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加日志路径")
        self.setMinimumWidth(400)
        
        # 创建布局
        layout = QVBoxLayout(self)
        
        # 创建表单
        form_layout = QHBoxLayout()
        path_label = QLabel("路径:")
        self.path_input = QLineEdit()
        browse_btn = QPushButton("浏览...")
        
        form_layout.addWidget(path_label)
        form_layout.addWidget(self.path_input, 1)  # 1是拉伸因子，让输入框获得更多空间
        form_layout.addWidget(browse_btn)
        
        # 添加表单到主布局
        layout.addLayout(form_layout)
        
        # 提示信息
        info_label = QLabel("请输入远程服务器上的日志目录路径，程序将递归查找该目录下的所有日志文件。")
        info_label.setStyleSheet("color: gray;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 添加确定取消按钮
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 连接按钮事件
        browse_btn.clicked.connect(self.browse_path)
    
    def browse_path(self):
        # 打开文件对话框选择目录
        path = QFileDialog.getExistingDirectory(
            self, "选择日志目录", os.path.expanduser("~")
        )
        if path:
            self.path_input.setText(path)
    
    def get_path(self):
        return self.path_input.text().strip()

class HostInputDialog(QDialog):
    def __init__(self, parent=None, host_data=None):
        super().__init__(parent)
        self.setWindowTitle("添加主机")
        self.setMinimumWidth(500)
        
        # 创建布局
        layout = QVBoxLayout(self)
        
        # 主机名称
        name_layout = QHBoxLayout()
        name_label = QLabel("名称:")
        self.name_input = QLineEdit()
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # SSH连接设置
        ssh_group = QGroupBox("SSH连接设置")
        ssh_layout = QVBoxLayout(ssh_group)
        
        # 主机设置
        host_layout = QHBoxLayout()
        host_label = QLabel("主机地址:")
        self.host_input = QLineEdit()
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
        
        layout.addWidget(ssh_group)
        
        # 日志路径列表
        path_group = QGroupBox("日志文件路径")
        path_layout = QVBoxLayout(path_group)
        
        # 创建路径列表和按钮的完整容器
        path_list_container = QWidget()
        path_list_layout = QVBoxLayout(path_list_container)
        path_list_layout.setContentsMargins(0, 0, 0, 0)
        
        # 添加路径列表
        self.path_list = QListWidget()
        path_list_layout.addWidget(self.path_list)
        
        # 路径操作按钮容器，使用水平布局
        path_buttons_container = QWidget()
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
        """添加日志路径"""
        dialog = PathInputDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            path = dialog.get_path()
            if path:
                self.path_list.addItem(path)
    
    def remove_path(self):
        """删除选中的路径"""
        selected_items = self.path_list.selectedItems()
        for item in selected_items:
            self.path_list.takeItem(self.path_list.row(item))
    
    def get_host_data(self):
        """获取主机数据"""
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
        self.setMinimumSize(600, 400)
        
        # 主机数据
        self.hosts_data = hosts_data or []
        
        # 创建布局
        layout = QVBoxLayout(self)
        
        # 主机列表区域
        host_list_layout = QHBoxLayout()
        
        # 主机列表
        self.host_list = QListWidget()
        self.host_list.setMinimumWidth(150)
        host_list_layout.addWidget(self.host_list, 1)
        
        # 按钮区域
        button_layout = QVBoxLayout()
        self.add_btn = QPushButton("添加")
        self.edit_btn = QPushButton("编辑")
        self.delete_btn = QPushButton("删除")
        button_layout.addWidget(self.add_btn)
        button_layout.addWidget(self.edit_btn)
        button_layout.addWidget(self.delete_btn)
        button_layout.addStretch(1)
        host_list_layout.addLayout(button_layout)
        
        layout.addLayout(host_list_layout)
        
        # 添加确定取消按钮
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
        
        # 连接信号
        self.add_btn.clicked.connect(self.add_host)
        self.edit_btn.clicked.connect(self.edit_host)
        self.delete_btn.clicked.connect(self.delete_host)
        
        # 加载主机列表
        self.load_hosts()
    
    def load_hosts(self):
        """加载主机列表"""
        self.host_list.clear()
        for i, host in enumerate(self.hosts_data):
            name = host.get("name", f"未命名主机{i+1}")
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, i)  # 存储主机索引
            self.host_list.addItem(item)
    
    def add_host(self):
        """添加新主机"""
        dialog = HostInputDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            host_data = dialog.get_host_data()
            self.hosts_data.append(host_data)
            self.load_hosts()
    
    def edit_host(self):
        """编辑选中的主机"""
        selected_items = self.host_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请先选择要编辑的主机")
            return
        
        item = selected_items[0]
        host_index = item.data(Qt.ItemDataRole.UserRole)
        host_data = self.hosts_data[host_index]
        
        dialog = HostInputDialog(self, host_data)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.hosts_data[host_index] = dialog.get_host_data()
            self.load_hosts()
    
    def delete_host(self):
        """删除选中的主机"""
        selected_items = self.host_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请先选择要删除的主机")
            return
        
        item = selected_items[0]
        host_index = item.data(Qt.ItemDataRole.UserRole)
        
        # 确认删除
        result = QMessageBox.question(self, "确认删除", 
                                     f"确定要删除主机 \"{item.text()}\" 吗？", 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if result == QMessageBox.StandardButton.Yes:
            del self.hosts_data[host_index]
            self.load_hosts()
    
    def get_hosts_data(self):
        """获取主机数据"""
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
        """发送日志消息"""
        self.log_message_signal.emit(message)
    
    def run(self):
        try:
            # 检查是否为本地测试模式
            if self.is_local_test_mode():
                self.handle_local_test_mode()
                return
                
            collector = LogCollector(config_file=None)
            collector.config = self.config
            collector.connect()
            
            try:
                if self.mode == 'list':
                    # 获取日志文件列表
                    files = self.get_log_files(collector)
                    self.log_list.emit(files)
                elif self.mode == 'search':
                    # 搜索关键字
                    self.search_keyword(collector)
                elif self.mode == 'full':
                    # 获取完整日志
                    self.get_full_log(collector)
            finally:
                collector.close()
        except Exception as e:
            self.error.emit(str(e))
    
    def get_log_files(self, collector):
        """获取日志文件列表"""
        log_files = []
        
        # 获取日期范围
        start_date = datetime.strptime(self.config.get('start_date_analysis', ''), '%Y-%m-%d')
        end_date = datetime.strptime(self.config.get('end_date_analysis', ''), '%Y-%m-%d')
        end_date = end_date.replace(hour=23, minute=59, second=59)  # 设置为当天结束时间
        
        # 遍历所有日志路径
        for path in self.config['log_paths']:
            self.log_message(f"获取目录中的日志文件: {path}")
            
            # 根据系统类型选择命令
            if collector.is_remote_windows():
                # Windows系统使用dir命令
                cmd = f'dir /S /B "{path}\\*.log" "{path}\\*.zip"'
                try:
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        files = stdout.read().decode('gbk').splitlines()
                    except UnicodeDecodeError:
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        files = stdout.read().decode('utf-8', errors='ignore').splitlines()
                except:
                    # 如果出错，尝试不使用/S参数（不递归子目录）
                    cmd = f'dir /B "{path}\\*.log" "{path}\\*.zip"'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        files = stdout.read().decode('gbk').splitlines()
                    except UnicodeDecodeError:
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        files = stdout.read().decode('utf-8', errors='ignore').splitlines()
                
                # 遍历找到的文件
                for file_path in files:
                    if "File Not Found" in file_path:
                        continue
                    
                    # 提取文件名
                    file_name = os.path.basename(file_path)
                    
                    # 尝试从文件名中提取日期
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_name)
                    if date_match:
                        file_date_str = date_match.group(1)
                        try:
                            file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                            if not (start_date <= file_date <= end_date):
                                continue  # 跳过不在日期范围内的文件
                        except ValueError:
                            pass  # 解析失败，保留文件
                    
                    # 获取文件信息
                    cmd = f'dir "{file_path}"'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        file_info = stdout.read().decode('gbk').splitlines()
                    except UnicodeDecodeError:
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        file_info = stdout.read().decode('utf-8', errors='ignore').splitlines()
                    
                    # 从dir命令输出中提取文件大小
                    size_str = "未知"
                    date_str = "未知"
                    for line in file_info:
                        if file_name in line:
                            parts = line.strip().split()
                            if len(parts) >= 4:
                                try:
                                    # 尝试提取日期和大小
                                    date_str = parts[0]
                                    size = int(parts[3].replace(',', ''))
                                    if size < 1024:
                                        size_str = f"{size} B"
                                    elif size < 1024 * 1024:
                                        size_str = f"{size / 1024:.2f} KB"
                                    else:
                                        size_str = f"{size / (1024 * 1024):.2f} MB"
                                except:
                                    pass
                    
                    log_files.append({
                        'path': file_path,
                        'name': file_name,
                        'size': size_str,
                        'date': date_str
                    })
            else:
                # Linux系统使用find命令查找日志文件
                cmd = f'find {path} -type f \\( -name "*.log" -o -name "*.zip" \\) -print'
                stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                
                try:
                    files = stdout.read().decode('utf-8').splitlines()
                except UnicodeDecodeError:
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    files = stdout.read().decode('utf-8', errors='ignore').splitlines()
                
                # 遍历找到的文件
                for file_path in files:
                    if not file_path.strip():
                        continue
                    
                    # 提取文件名
                    file_name = os.path.basename(file_path)
                    
                    # 尝试从文件名中提取日期
                    date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file_name)
                    if date_match:
                        file_date_str = date_match.group(1)
                        try:
                            file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                            if not (start_date <= file_date <= end_date):
                                continue  # 跳过不在日期范围内的文件
                        except ValueError:
                            pass  # 解析失败，保留文件
                    
                    # 获取文件信息
                    cmd = f'ls -lh "{file_path}"'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    
                    try:
                        file_info = stdout.read().decode('utf-8').strip()
                    except UnicodeDecodeError:
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        file_info = stdout.read().decode('utf-8', errors='ignore').strip()
                    
                    # 从ls命令输出中提取文件大小和日期
                    parts = file_info.split()
                    size_str = "未知"
                    date_str = "未知"
                    if len(parts) >= 8:
                        try:
                            size_str = parts[4]
                            date_str = ' '.join(parts[5:8])
                        except:
                            pass
                    
                    log_files.append({
                        'path': file_path,
                        'name': file_name,
                        'size': size_str,
                        'date': date_str
                    })
        
        return log_files
    
    def search_keyword(self, collector):
        """在日志文件中搜索关键字"""
        if not self.log_path or not self.keyword:
            self.error.emit("缺少日志文件路径或关键字")
            return
        
        try:
            # 从日志文件路径中提取文件名
            log_name = os.path.basename(self.log_path)
            
            # 检查是否为zip文件
            if self.log_path.lower().endswith('.zip'):
                # 对压缩文件先获取到本地缓存，然后进行搜索
                cached_file = self._get_cached_file(self.log_path, collector)
                if not cached_file:
                    self.error.emit(f"无法获取日志文件: {self.log_path}")
                    return
                
                # 读取压缩文件内容
                import zipfile
                import tempfile
                
                # 创建临时目录存放解压的文件
                temp_dir = tempfile.mkdtemp()
                results = []
                
                try:
                    # 解压文件
                    with zipfile.ZipFile(cached_file, 'r') as zip_ref:
                        # 获取zip文件中的所有文件
                        file_list = zip_ref.namelist()
                        
                        # 遍历压缩包中的每个文件
                        for file_name in file_list:
                            # 只处理日志文件
                            if not file_name.lower().endswith('.log'):
                                continue
                            
                            # 解压到临时目录
                            zip_ref.extract(file_name, temp_dir)
                            extracted_file = os.path.join(temp_dir, file_name)
                            
                            # 读取文件内容
                            content = self._read_file_content(extracted_file)
                            
                            # 搜索关键字
                            found_lines = []
                            for i, line in enumerate(content.splitlines()):
                                if self.keyword.lower() in line.lower():
                                    found_lines.append({
                                        'line_num': i + 1,
                                        'content': line.strip(),
                                        'file': file_name
                                    })
                            
                            # 如果找到结果，添加到结果列表
                            if found_lines:
                                results.extend(found_lines)
                    
                    # 发送搜索结果
                    self.search_result.emit(self.keyword, results)
                finally:
                    # 清理临时目录
                    import shutil
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
            else:
                # 处理普通日志文件
                # 根据系统类型选择命令
                if collector.is_remote_windows():
                    # Windows上使用findstr命令
                    cmd = f'findstr /N /I "{self.keyword}" "{self.log_path}"'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        output = stdout.read().decode('gbk')
                    except UnicodeDecodeError:
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        output = stdout.read().decode('utf-8', errors='ignore')
                else:
                    # Linux上使用grep命令
                    cmd = f'grep -n -i "{self.keyword}" "{self.log_path}"'
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    output = stdout.read().decode('utf-8')
                
                # 解析搜索结果
                results = []
                for line in output.splitlines():
                    if not line.strip():
                        continue
                    
                    # 尝试解析行号和内容
                    try:
                        if ':' in line:
                            parts = line.split(':', 1)
                            line_num = int(parts[0])
                            content = parts[1].strip()
                            results.append({
                                'line_num': line_num,
                                'content': content,
                                'file': log_name
                            })
                    except:
                        # 如果解析失败，将整行作为内容
                        results.append({
                            'line_num': 0,
                            'content': line.strip(),
                            'file': log_name
                        })
                
                # 发送搜索结果
                self.search_result.emit(self.keyword, results)
        except Exception as e:
            self.error.emit(f"搜索关键字时出错: {str(e)}")
    
    def get_full_log(self, collector):
        """获取完整的日志内容"""
        if not self.log_path:
            self.error.emit("缺少日志文件路径")
            return
        
        try:
            # 检查是否为zip文件
            if self.log_path.lower().endswith('.zip'):
                # 对压缩文件先获取到本地缓存，然后进行处理
                cached_file = self._get_cached_file(self.log_path, collector)
                if not cached_file:
                    self.error.emit(f"无法获取日志文件: {self.log_path}")
                    return
                
                # 读取压缩文件内容
                import zipfile
                import tempfile
                
                # 创建临时目录存放解压的文件
                temp_dir = tempfile.mkdtemp()
                full_content = ""
                
                try:
                    # 解压文件
                    with zipfile.ZipFile(cached_file, 'r') as zip_ref:
                        # 获取zip文件中的所有文件
                        file_list = zip_ref.namelist()
                        
                        # 遍历压缩包中的每个文件
                        for file_name in file_list:
                            # 只处理日志文件
                            if not file_name.lower().endswith('.log'):
                                continue
                            
                            # 解压到临时目录
                            zip_ref.extract(file_name, temp_dir)
                            extracted_file = os.path.join(temp_dir, file_name)
                            
                            # 读取文件内容
                            content = self._read_file_content(extracted_file)
                            
                            # 添加文件名标题
                            full_content += f"\n\n===== {file_name} =====\n\n"
                            full_content += content
                    
                    # 发送完整日志内容
                    self.complete_log.emit(full_content)
                finally:
                    # 清理临时目录
                    import shutil
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
            else:
                # 处理普通日志文件
                # 获取文件内容
                cached_file = self._get_cached_file(self.log_path, collector)
                if cached_file:
                    # 读取本地缓存文件
                    content = self._read_file_content(cached_file)
                    self.complete_log.emit(content)
                else:
                    # 直接从远程读取文件内容
                    if collector.is_remote_windows():
                        cmd = f'type "{self.log_path}"'
                    else:
                        cmd = f'cat "{self.log_path}"'
                    
                    stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                    try:
                        if collector.is_remote_windows():
                            content = stdout.read().decode('gbk')
                        else:
                            content = stdout.read().decode('utf-8')
                    except UnicodeDecodeError:
                        content = stdout.read().decode('utf-8', errors='ignore')
                    
                    self.complete_log.emit(content)
        except Exception as e:
            self.error.emit(f"获取完整日志时出错: {str(e)}")
    
    def _get_cached_file(self, remote_path, collector):
        """获取远程文件的本地缓存"""
        import tempfile
        import os
        import hashlib
        
        # 创建缓存目录
        cache_dir = os.path.join(tempfile.gettempdir(), "log_cache")
        os.makedirs(cache_dir, exist_ok=True)
        
        # 计算文件哈希作为缓存文件名
        file_hash = hashlib.md5(remote_path.encode()).hexdigest()
        file_ext = os.path.splitext(remote_path)[1]
        cached_file = os.path.join(cache_dir, f"{file_hash}{file_ext}")
        
        # 如果缓存文件已存在，直接返回
        if os.path.exists(cached_file):
            return cached_file
        
        # 下载文件到缓存目录
        try:
            self.log_message(f"下载文件到本地缓存: {os.path.basename(remote_path)}")
            collector.download_file(remote_path, cached_file)
            return cached_file
        except Exception as e:
            self.log_message(f"下载文件失败: {str(e)}")
            return None
    
    def _read_file_with_encoding(self, file_path):
        """尝试不同编码读取文件内容"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'iso-8859-1']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue
        
        # 如果所有编码都失败，使用二进制模式读取
        with open(file_path, 'rb') as f:
            binary_content = f.read()
            return binary_content.decode('utf-8', errors='ignore')
    
    def _read_file_content(self, file_path):
        """读取文件内容，尝试自动检测换行符和编码"""
        try:
            # 尝试使用不同的编码读取文件
            content = self._read_file_with_encoding(file_path)
            
            # 检查文件大小，如果超过一定大小，可能会导致UI卡顿
            if len(content) > 5 * 1024 * 1024:  # 5MB
                self.log_message("文件较大，仅显示前后部分内容...")
                lines = content.splitlines()
                if len(lines) > 2000:
                    # 只保留前1000行和后1000行
                    first_part = '\n'.join(lines[:1000])
                    last_part = '\n'.join(lines[-1000:])
                    content = first_part + "\n\n...... [文件过大，中间内容已省略] ......\n\n" + last_part
            
            return content
        except Exception as e:
            self.log_message(f"读取文件内容失败: {str(e)}")
            return f"无法读取文件内容: {str(e)}"
    
    def is_local_test_mode(self):
        """检查是否为本地测试模式"""
        return (self.config.get('ssh', {}).get('host') == '127.0.0.1' and 
                self.config.get('ssh', {}).get('username') == 'liurat' and 
                self.config.get('ssh', {}).get('password') == '123456')
    
    def handle_local_test_mode(self):
        """处理本地测试模式"""
        try:
            if self.mode == 'list':
                self.get_local_log_files()
            elif self.mode == 'search':
                self.search_local_keyword()
            elif self.mode == 'full':
                self.get_local_full_log()
        except Exception as e:
            self.error.emit(f"本地测试模式出错: {str(e)}")
    
    def get_local_log_files(self):
        """获取本地日志文件列表"""
        log_files = []
        
        # 获取日期范围
        start_date = datetime.strptime(self.config.get('start_date_analysis', ''), '%Y-%m-%d')
        end_date = datetime.strptime(self.config.get('end_date_analysis', ''), '%Y-%m-%d')
        end_date = end_date.replace(hour=23, minute=59, second=59)  # 设置为当天结束时间
        
        # 遍历所有日志路径
        for path in self.config['log_paths']:
            self.log_message(f"获取目录中的日志文件: {path}")
            
            if os.path.exists(path) and os.path.isdir(path):
                # 递归遍历目录
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file.endswith('.log') or file.endswith('.zip'):
                            file_path = os.path.join(root, file)
                            
                            # 尝试从文件名中提取日期
                            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', file)
                            if date_match:
                                file_date_str = date_match.group(1)
                                try:
                                    file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                                    if not (start_date <= file_date <= end_date):
                                        continue  # 跳过不在日期范围内的文件
                                except ValueError:
                                    pass  # 解析失败，保留文件
                            
                            # 获取文件信息
                            try:
                                file_stat = os.stat(file_path)
                                size = file_stat.st_size
                                if size < 1024:
                                    size_str = f"{size} B"
                                elif size < 1024 * 1024:
                                    size_str = f"{size / 1024:.2f} KB"
                                else:
                                    size_str = f"{size / (1024 * 1024):.2f} MB"
                                
                                mod_time = datetime.fromtimestamp(file_stat.st_mtime)
                                date_str = mod_time.strftime('%Y-%m-%d %H:%M:%S')
                                
                                log_files.append({
                                    'path': file_path,
                                    'name': file,
                                    'size': size_str,
                                    'date': date_str
                                })
                            except:
                                # 如果获取文件信息失败，使用默认值
                                log_files.append({
                                    'path': file_path,
                                    'name': file,
                                    'size': '未知',
                                    'date': '未知'
                                })
            else:
                self.log_message(f"目录不存在: {path}")
        
        self.log_list.emit(log_files)
    
    def search_local_keyword(self):
        """在本地日志文件中搜索关键字"""
        if not self.log_path or not self.keyword:
            self.error.emit("缺少日志文件路径或关键字")
            return
        
        try:
            # 从日志文件路径中提取文件名
            log_name = os.path.basename(self.log_path)
            
            # 检查是否为zip文件
            if self.log_path.lower().endswith('.zip'):
                # 读取压缩文件内容
                import zipfile
                import tempfile
                
                # 创建临时目录存放解压的文件
                temp_dir = tempfile.mkdtemp()
                results = []
                
                try:
                    # 解压文件
                    with zipfile.ZipFile(self.log_path, 'r') as zip_ref:
                        # 获取zip文件中的所有文件
                        file_list = zip_ref.namelist()
                        
                        # 遍历压缩包中的每个文件
                        for file_name in file_list:
                            # 只处理日志文件
                            if not file_name.lower().endswith('.log'):
                                continue
                            
                            # 解压到临时目录
                            zip_ref.extract(file_name, temp_dir)
                            extracted_file = os.path.join(temp_dir, file_name)
                            
                            # 读取文件内容
                            content = self._read_file_content(extracted_file)
                            
                            # 搜索关键字
                            found_lines = []
                            for i, line in enumerate(content.splitlines()):
                                if self.keyword.lower() in line.lower():
                                    found_lines.append({
                                        'line_num': i + 1,
                                        'content': line.strip(),
                                        'file': file_name
                                    })
                            
                            # 如果找到结果，添加到结果列表
                            if found_lines:
                                results.extend(found_lines)
                    
                    # 发送搜索结果
                    self.search_result.emit(self.keyword, results)
                finally:
                    # 清理临时目录
                    import shutil
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
            else:
                # 处理普通日志文件
                # 读取文件内容
                content = self._read_file_content(self.log_path)
                
                # 搜索关键字
                results = []
                for i, line in enumerate(content.splitlines()):
                    if self.keyword.lower() in line.lower():
                        results.append({
                            'line_num': i + 1,
                            'content': line.strip(),
                            'file': log_name
                        })
                
                # 发送搜索结果
                self.search_result.emit(self.keyword, results)
        except Exception as e:
            self.error.emit(f"搜索关键字时出错: {str(e)}")
    
    def get_local_full_log(self):
        """获取本地日志文件的完整内容"""
        if not self.log_path:
            self.error.emit("缺少日志文件路径")
            return
        
        try:
            # 检查是否为zip文件
            if self.log_path.lower().endswith('.zip'):
                # 读取压缩文件内容
                import zipfile
                import tempfile
                
                # 创建临时目录存放解压的文件
                temp_dir = tempfile.mkdtemp()
                full_content = ""
                
                try:
                    # 解压文件
                    with zipfile.ZipFile(self.log_path, 'r') as zip_ref:
                        # 获取zip文件中的所有文件
                        file_list = zip_ref.namelist()
                        
                        # 遍历压缩包中的每个文件
                        for file_name in file_list:
                            # 只处理日志文件
                            if not file_name.lower().endswith('.log'):
                                continue
                            
                            # 解压到临时目录
                            zip_ref.extract(file_name, temp_dir)
                            extracted_file = os.path.join(temp_dir, file_name)
                            
                            # 读取文件内容
                            content = self._read_file_content(extracted_file)
                            
                            # 添加文件名标题
                            full_content += f"\n\n===== {file_name} =====\n\n"
                            full_content += content
                    
                    # 发送完整日志内容
                    self.complete_log.emit(full_content)
                finally:
                    # 清理临时目录
                    import shutil
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
            else:
                # 处理普通日志文件
                # 读取文件内容
                content = self._read_file_content(self.log_path)
                
                # 发送完整日志内容
                self.complete_log.emit(content)
        except Exception as e:
            self.error.emit(f"获取完整日志时出错: {str(e)}")
    
    def _get_full_log_context(self, file_content, earliest_time, latest_time, time_pattern):
        """获取指定时间范围内的日志上下文"""
        lines = file_content.splitlines()
        result_lines = []
        
        # 尝试匹配每行的时间戳
        for line in lines:
            match = re.search(time_pattern, line)
            if match:
                try:
                    # 解析时间戳
                    time_str = match.group(1)
                    time = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    
                    # 检查是否在时间范围内
                    if earliest_time <= time <= latest_time:
                        result_lines.append(line)
                except:
                    # 如果解析失败，保留这行（可能是多行日志的一部分）
                    if result_lines:
                        result_lines.append(line)
            else:
                # 如果没有时间戳，可能是上一条日志的延续
                if result_lines:
                    result_lines.append(line)
        
        return '\n'.join(result_lines)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("车道系统日志收集分析工具")
        self.setMinimumSize(800, 600)
        
        # 主机配置数据
        self.hosts_data = []
        
        # 创建菜单栏
        self.create_menu_bar()
        
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
        
        # 创建功能选项卡容器
        function_tabs = QTabWidget()
        function_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        
        # 创建日志收集页
        collect_tab = QWidget()
        collect_layout = QVBoxLayout(collect_tab)
        
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
        date_info = QLabel("注意：将自动匹配文件名中包含选定日期范围的日志文件支持的文件名格式：xxxx_YYYY-MM-DD.log 或 xxxx_YYYY-MM-DD.zip")
        date_info.setStyleSheet("color: gray;")
        date_layout.addWidget(date_info)
        
        # 日志路径列表
        path_group = QGroupBox("日志文件路径")
        path_layout = QVBoxLayout(path_group)
        
        # 添加路径说明
        path_info = QLabel("请输入日志文件所在的目录，程序会自动查找并下载符合日期条件的日志文件支持的文件类型：.log 和 .zip")
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
        
        # 文件列表和操作区域合并
        file_list_group = QGroupBox("文件列表和操作")
        file_list_layout = QVBoxLayout(file_list_group)
        
        # 操作按钮区域
        operations_layout = QHBoxLayout()
        
        # 创建操作按钮
        list_btn = QPushButton("列出文件")
        collect_btn = QPushButton("收集日志")
        operations_layout.addWidget(list_btn)
        operations_layout.addWidget(collect_btn)
        operations_layout.addStretch(1)
        
        # 添加操作按钮区域到文件列表布局
        file_list_layout.addLayout(operations_layout)
        
        # 文件列表视图
        self.file_list = QTableWidget()
        self.file_list.setColumnCount(3)
        self.file_list.setHorizontalHeaderLabels(["文件名", "大小", "日期"])
        self.file_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.file_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.file_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        file_list_layout.addWidget(self.file_list)
        
        # 连接按钮事件
        list_btn.clicked.connect(self.list_files)
        collect_btn.clicked.connect(self.start_collection)
        
        # 进度显示
        progress_group = QGroupBox("进度")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v / %m KB (%p%)")
        progress_layout.addWidget(self.progress_bar)
        
        # 将各组件添加到收集选项卡
        collect_layout.addWidget(date_group)
        collect_layout.addWidget(path_group)
        collect_layout.addWidget(file_list_group)
        collect_layout.addWidget(progress_group)
        
        # 创建日志分析页
        analysis_tab = QWidget()
        analysis_layout = QVBoxLayout(analysis_tab)
        
        # 时间范围选择
        analysis_date_group = QGroupBox("时间范围选择")
        analysis_date_layout = QHBoxLayout(analysis_date_group)
        
        analysis_start_date_label = QLabel("开始日期:")
        self.analysis_start_date = QDateEdit()
        self.analysis_start_date.setDate(QDate.currentDate().addDays(-1))
        self.analysis_start_date.setCalendarPopup(True)
        
        analysis_end_date_label = QLabel("结束日期:")
        self.analysis_end_date = QDateEdit()
        self.analysis_end_date.setDate(QDate.currentDate())
        self.analysis_end_date.setCalendarPopup(True)
        
        list_logs_btn = QPushButton("获取日志列表")
        
        analysis_date_layout.addWidget(analysis_start_date_label)
        analysis_date_layout.addWidget(self.analysis_start_date)
        analysis_date_layout.addWidget(analysis_end_date_label)
        analysis_date_layout.addWidget(self.analysis_end_date)
        analysis_date_layout.addWidget(list_logs_btn)
        analysis_date_layout.addStretch(1)
        
        # 连接按钮事件
        list_logs_btn.clicked.connect(self.get_log_list)
        
        # 日志文件列表
        log_list_group = QGroupBox("日志文件列表")
        log_list_layout = QVBoxLayout(log_list_group)
        
        self.log_list = QTableWidget()
        self.log_list.setColumnCount(3)
        self.log_list.setHorizontalHeaderLabels(["日志名称", "大小", "日期"])
        self.log_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.log_list.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.log_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.log_list.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        
        log_list_layout.addWidget(self.log_list)
        
        # 搜索区域
        search_group = QGroupBox("关键字搜索")
        search_layout = QVBoxLayout(search_group)
        
        search_input_layout = QHBoxLayout()
        keyword_label = QLabel("关键字:")
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("输入要搜索的关键字")
        search_btn = QPushButton("搜索")
        view_full_btn = QPushButton("查看完整日志")
        
        search_input_layout.addWidget(keyword_label)
        search_input_layout.addWidget(self.keyword_input)
        search_input_layout.addWidget(search_btn)
        search_input_layout.addWidget(view_full_btn)
        
        # 连接按钮事件
        search_btn.clicked.connect(self.search_keyword)
        view_full_btn.clicked.connect(self.view_full_log)
        
        search_layout.addLayout(search_input_layout)
        
        # 搜索结果区域
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        
        search_layout.addWidget(self.result_text)
        
        # 添加导出结果和导出时间范围日志的按钮
        export_btns_layout = QHBoxLayout()
        export_btn = QPushButton("导出搜索结果")
        export_time_range_btn = QPushButton("导出时间范围日志")
        
        export_btns_layout.addWidget(export_btn)
        export_btns_layout.addWidget(export_time_range_btn)
        export_btns_layout.addStretch(1)
        
        search_layout.addLayout(export_btns_layout)
        
        # 连接导出按钮事件
        export_btn.clicked.connect(self.export_results)
        export_time_range_btn.clicked.connect(self.export_time_range_logs)
        
        # 将各组件添加到分析选项卡
        analysis_layout.addWidget(analysis_date_group)
        analysis_layout.addWidget(log_list_group)
        analysis_layout.addWidget(search_group)
        
        # 添加两个选项卡到功能选项卡容器
        function_tabs.addTab(collect_tab, "日志收集")
        function_tabs.addTab(analysis_tab, "日志分析")
        
        # 消息区域
        log_group = QGroupBox("操作日志")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        # 将选项卡和其他组件添加到主布局
        main_layout.addWidget(host_select_group)
        main_layout.addWidget(ssh_group)
        main_layout.addWidget(function_tabs)
        main_layout.addWidget(log_group)
        
        # 加载主机数据和配置
        self.load_hosts_data()
        
        # 显示初始消息
        self.log_message("程序已启动，请选择或配置主机信息")
    
    def create_menu_bar(self):
        """创建菜单栏"""
        menu_bar = self.menuBar()
        
        # 文件菜单
        file_menu = menu_bar.addMenu("文件")
        
        # 清除缓存动作
        clear_cache_action = file_menu.addAction("清除日志缓存")
        clear_cache_action.triggered.connect(self.clear_log_cache)
        
        # 退出动作
        exit_action = file_menu.addAction("退出")
        exit_action.triggered.connect(self.close)
    
    def clear_log_cache(self):
        """清除日志缓存文件"""
        try:
            import tempfile
            import os
            import shutil
            
            # 获取缓存目录
            cache_dir = os.path.join(tempfile.gettempdir(), "log_cache")
            
            if os.path.exists(cache_dir):
                # 计算缓存文件数量和总大小
                file_count = 0
                total_size = 0
                for file_name in os.listdir(cache_dir):
                    file_path = os.path.join(cache_dir, file_name)
                    if os.path.isfile(file_path):
                        file_count += 1
                        total_size += os.path.getsize(file_path)
                
                # 删除缓存目录
                shutil.rmtree(cache_dir)
                
                # 显示成功消息
                size_mb = total_size / (1024 * 1024)
                self.log_message(f"缓存清除成功！删除了 {file_count} 个缓存文件，释放了 {size_mb:.2f} MB 空间")
                QMessageBox.information(self, "清除缓存", f"缓存清除成功！\n删除了 {file_count} 个缓存文件，释放了 {size_mb:.2f} MB 空间")
            else:
                self.log_message("缓存目录不存在，无需清理")
                QMessageBox.information(self, "清除缓存", "缓存目录不存在，无需清理")
        except Exception as e:
            self.log_message(f"清除缓存失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"清除缓存失败：\n{str(e)}")
    
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
                # 如果是打包后的exe
                base_path = os.path.dirname(sys.executable)
            else:
                # 如果是开发环境
                base_path = os.path.dirname(os.path.abspath(__file__))
            
            config_path = os.path.join(base_path, 'config.yaml')
            
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            self.log_message(f"保存配置失败: {str(e)}")
    
    def add_path(self):
        """添加日志路径"""
        dialog = PathInputDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            path = dialog.get_path()
            if path:
                self.path_list.addItem(path)
    
    def remove_path(self):
        """删除选中的路径"""
        selected_items = self.path_list.selectedItems()
        for item in selected_items:
            self.path_list.takeItem(self.path_list.row(item))
    
    def log_message(self, message):
        """添加日志消息"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        # 滚动到底部
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())
    
    def get_date_range(self):
        """获取日期范围设置"""
        if not self.use_date_range.isChecked():
            return None, None
        
        start_date = self.start_date.date().toString('yyyy-MM-dd')
        end_date = self.end_date.date().toString('yyyy-MM-dd')
        return start_date, end_date
    
    def list_files(self):
        """列出远程服务器上的日志文件"""
        # 获取SSH连接配置
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
        
        # 检查配置是否完整
        if not config['ssh']['host'] or not config['ssh']['username'] or not config['ssh']['password']:
            QMessageBox.warning(self, "配置不完整", "请填写SSH连接信息")
            return
        
        if not config['log_paths']:
            QMessageBox.warning(self, "配置不完整", "请添加至少一个日志路径")
            return
        
        # 清空文件列表
        self.file_list.setRowCount(0)
        
        # 创建并启动工作线程
        self.log_message("开始列出文件...")
        self.worker = LogCollectorWorker(config, mode='list')
        self.worker.file_list.connect(self.show_file_list)
        self.worker.error.connect(self.collection_error)
        self.worker.start()
    
    def show_file_list(self, file_info_list):
        """显示文件列表"""
        self.file_list.setRowCount(len(file_info_list))
        
        for row, file_info in enumerate(file_info_list):
            # 文件名
            name_item = QTableWidgetItem(file_info.get('name', ''))
            self.file_list.setItem(row, 0, name_item)
            
            # 文件大小（如果有）
            size_item = QTableWidgetItem(file_info.get('size', 'N/A'))
            self.file_list.setItem(row, 1, size_item)
            
            # 日期
            date_item = QTableWidgetItem(file_info.get('date', ''))
            self.file_list.setItem(row, 2, date_item)
            
            # 存储完整路径
            name_item.setData(Qt.ItemDataRole.UserRole, file_info.get('path'))
        
        self.log_message(f"列出了 {len(file_info_list)} 个文件")
    
    def start_collection(self):
        """开始收集日志"""
        # 获取SSH连接配置
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
        
        # 检查配置是否完整
        if not config['ssh']['host'] or not config['ssh']['username'] or not config['ssh']['password']:
            QMessageBox.warning(self, "配置不完整", "请填写SSH连接信息")
            return
        
        if not config['log_paths']:
            QMessageBox.warning(self, "配置不完整", "请添加至少一个日志路径")
            return
        
        # 添加日期范围设置
        start_date, end_date = self.get_date_range()
        if start_date and end_date:
            config['use_date_range'] = True
            config['start_date'] = start_date
            config['end_date'] = end_date
        else:
            config['use_date_range'] = False
        
        # 创建并启动工作线程
        self.log_message("开始收集日志...")
        self.worker = LogCollectorWorker(config, mode='collect')
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.collection_finished)
        self.worker.error.connect(self.collection_error)
        self.worker.start()
        
        # 保存配置
        self.save_config()
    
    def update_progress(self, filename, current, total):
        """更新进度条"""
        self.progress_bar.setMaximum(int(total / 1024))
        self.progress_bar.setValue(int(current / 1024))
        
        # 更新进度条文本
        progress_text = f"{filename} - {current / 1024:.2f} / {total / 1024:.2f} KB ({current / total * 100:.2f}%)"
        self.log_message(progress_text)
    
    def collection_finished(self, zip_path):
        """收集完成的处理"""
        self.log_message(f"日志收集完成，保存在: {zip_path}")
        QMessageBox.information(self, "收集完成", f"日志收集完成，保存在:\n{zip_path}")
        
        # 清除进度条
        self.progress_bar.setValue(0)
    
    def collection_error(self, error_message):
        """错误处理"""
        self.log_message(f"错误: {error_message}")
        QMessageBox.critical(self, "错误", error_message)
    
    def get_log_list(self):
        """获取日志文件列表"""
        # 获取SSH连接配置
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
        
        # 检查配置是否完整
        if not config['ssh']['host'] or not config['ssh']['username'] or not config['ssh']['password']:
            QMessageBox.warning(self, "配置不完整", "请填写SSH连接信息")
            return
        
        if not config['log_paths']:
            QMessageBox.warning(self, "配置不完整", "请添加至少一个日志路径")
            return
        
        # 添加日期范围设置
        start_date = self.analysis_start_date.date().toString('yyyy-MM-dd')
        end_date = self.analysis_end_date.date().toString('yyyy-MM-dd')
        config['start_date_analysis'] = start_date
        config['end_date_analysis'] = end_date
        
        # 清空日志列表
        self.log_list.setRowCount(0)
        
        # 创建并启动工作线程
        self.log_message("正在获取日志文件列表...")
        self.analysis_worker = LogAnalysisWorker(config, mode='list')
        self.analysis_worker.log_list.connect(self.display_log_list)
        self.analysis_worker.error.connect(self.analysis_error)
        self.analysis_worker.log_message_signal.connect(self.log_message)
        self.analysis_worker.start()
    
    def get_date_range_analysis(self):
        """获取分析选项卡的日期范围设置"""
        start_date = self.analysis_start_date.date().toString('yyyy-MM-dd')
        end_date = self.analysis_end_date.date().toString('yyyy-MM-dd')
        return start_date, end_date
    
    def display_log_list(self, logs):
        """显示日志文件列表"""
        self.log_list.setRowCount(len(logs))
        
        for row, log in enumerate(logs):
            # 文件名
            name_item = QTableWidgetItem(log.get('name', ''))
            self.log_list.setItem(row, 0, name_item)
            
            # 文件大小
            size_item = QTableWidgetItem(log.get('size', ''))
            self.log_list.setItem(row, 1, size_item)
            
            # 日期
            date_item = QTableWidgetItem(log.get('date', ''))
            self.log_list.setItem(row, 2, date_item)
            
            # 存储完整路径
            name_item.setData(Qt.ItemDataRole.UserRole, log.get('path'))
        
        self.log_message(f"找到 {len(logs)} 个日志文件")
    
    def search_keyword(self):
        """搜索关键字"""
        # 获取关键字
        keyword = self.keyword_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "警告", "请输入要搜索的关键字")
            return
        
        # 获取选中的日志文件
        selected_rows = self.log_list.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请先选择要搜索的日志文件")
            return
        
        # 获取选中文件的路径和文件名
        selected_files = []
        file_prefixes = {}  # 用于存储文件前缀
        file_names = {}     # 用于存储文件名
        for row in selected_rows:
            file_name = self.log_list.item(row.row(), 0).text()
            file_path = self.log_list.item(row.row(), 0).data(Qt.ItemDataRole.UserRole)
            if file_path:
                selected_files.append(file_path)
                # 提取文件前缀，例如从 "RsuLogic_2025-03-31.log" 提取 "RsuLogic"
                file_prefix = re.match(r'([^_]+)_?', file_name)
                prefix = file_prefix.group(1) if file_prefix else "LOG"
                file_prefixes[file_path] = prefix
                file_names[file_path] = file_name
        
        # 清空结果显示区
        self.result_text.clear()
        
        # 创建进度对话框
        progress = QProgressDialog("正在搜索关键字...", "取消", 0, len(selected_files), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.show()
        
        # 开始搜索
        try:
            self.log_message("开始搜索关键字: " + keyword)
            keyword_results = []  # 包含关键字的结果
            all_file_contents = {}  # 存储每个文件的完整内容
            # 修改为匹配行首的时间戳格式，支持有无毫秒的情况
            time_pattern = r'^(\d{2}:\d{2}:\d{2}(?:\.\d{3})?)'
            # 不再匹配和使用RegTime
            earliest_time = None
            latest_time = None
            
            # 初始化SSH连接（如果需要搜索远程文件）
            for i, file_path in enumerate(selected_files):
                # 更新进度
                progress.setValue(i)
                if progress.wasCanceled():
                    break
                
                # 获取文件前缀和文件名
                prefix = file_prefixes.get(file_path, "LOG")
                file_name = file_names.get(file_path, os.path.basename(file_path))
                
                # 判断是否为本地文件
                if os.path.exists(file_path):
                    # 处理本地文件
                    # 检查文件是否为压缩文件
                    if file_path.endswith('.zip'):
                        # 处理压缩文件
                        with zipfile.ZipFile(file_path, 'r') as zip_ref:
                            for name in zip_ref.namelist():
                                # 为zip内每个文件提取前缀
                                name_prefix = re.match(r'([^_]+)_?', os.path.basename(name))
                                inner_prefix = name_prefix.group(1) if name_prefix else prefix
                                
                                with zip_ref.open(name) as f:
                                    # 尝试不同的编码读取zip文件内容
                                    try:
                                        content_lines = []
                                        for line in io.TextIOWrapper(f, encoding='utf-8'):
                                            content_lines.append(line.strip())
                                            if keyword in line:
                                                # 提取时间并更新最早/最晚时间
                                                time_match = re.search(time_pattern, line)
                                                if time_match:
                                                    # 使用常规时间戳
                                                    time_str = time_match.group(1)
                                                    try:
                                                        # 根据时间格式进行灵活解析
                                                        if '.' in time_str:
                                                            # 含有毫秒的时间格式 HH:MM:SS.fff
                                                            time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                                        else:
                                                            # 不含毫秒的时间格式 HH:MM:SS
                                                            time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                                    except ValueError as e:
                                                        print(f"时间解析错误: {str(e)}")
                                                    if earliest_time is None or time_obj < earliest_time:
                                                        earliest_time = time_obj
                                                    if latest_time is None or time_obj > latest_time:
                                                        latest_time = time_obj
                                                
                                                # 只显示文件名，不显示完整路径
                                                keyword_results.append(f"[{inner_prefix}] {line.strip()}")
                                        
                                        # 存储文件内容
                                        all_file_contents[f"{file_path}/{name}"] = {
                                            'content': content_lines, 
                                            'prefix': inner_prefix,
                                            'file_name': os.path.basename(name)
                                        }
                                    except UnicodeDecodeError:
                                        # 如果UTF-8失败，尝试GBK
                                        f.seek(0)  # 重置文件指针
                                        try:
                                            content_lines = []
                                            for line in io.TextIOWrapper(f, encoding='gbk'):
                                                content_lines.append(line.strip())
                                                if keyword in line:
                                                    # 提取时间并更新
                                                    time_match = re.search(time_pattern, line)
                                                    if time_match:
                                                        # 使用常规时间戳
                                                        time_str = time_match.group(1)
                                                        try:
                                                            # 根据时间格式进行灵活解析
                                                            if '.' in time_str:
                                                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                                            else:
                                                                # 不含毫秒的时间格式 HH:MM:SS
                                                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                                        except ValueError as e:
                                                            print(f"时间解析错误: {str(e)}")
                                                        if earliest_time is None or time_obj < earliest_time:
                                                            earliest_time = time_obj
                                                        if latest_time is None or time_obj > latest_time:
                                                            latest_time = time_obj
                                                    
                                                    keyword_results.append(f"[{inner_prefix}] {line.strip()}")
                                            
                                            # 存储文件内容
                                            all_file_contents[f"{file_path}/{name}"] = {
                                                'content': content_lines, 
                                                'prefix': inner_prefix,
                                                'file_name': os.path.basename(name)
                                            }
                                        except UnicodeDecodeError:
                                            # 如果GBK也失败，使用Latin1（可处理任何字节）
                                            f.seek(0)
                                            content_lines = []
                                            for line in io.TextIOWrapper(f, encoding='latin1'):
                                                content_lines.append(line.strip())
                                                if keyword in line:
                                                    # 提取时间并更新
                                                    time_match = re.search(time_pattern, line)
                                                    if time_match:
                                                        # 使用常规时间戳
                                                        time_str = time_match.group(1)
                                                        try:
                                                            # 根据时间格式进行灵活解析
                                                            if '.' in time_str:
                                                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                                            else:
                                                                # 不含毫秒的时间格式 HH:MM:SS
                                                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                                        except ValueError as e:
                                                            print(f"时间解析错误: {str(e)}")
                                                        if earliest_time is None or time_obj < earliest_time:
                                                            earliest_time = time_obj
                                                        if latest_time is None or time_obj > latest_time:
                                                            latest_time = time_obj
                                                    
                                                    keyword_results.append(f"[{inner_prefix}] {line.strip()}")
                                            
                                            # 存储文件内容
                                            all_file_contents[f"{file_path}/{name}"] = {
                                                'content': content_lines, 
                                                'prefix': inner_prefix,
                                                'file_name': os.path.basename(name)
                                            }
                                            # 如果成功读取，跳出循环
                                            break
                    else:
                        # 处理普通文本文件，尝试多种编码
                        encodings = ['utf-8', 'gbk', 'gb18030', 'latin1']
                        file_content = None
                        
                        # 依次尝试不同的编码
                        for encoding in encodings:
                            try:
                                with open(file_path, 'r', encoding=encoding) as f:
                                    file_content = f.readlines()
                                self.log_message(f"成功使用 {encoding} 编码读取文件")
                                # 如果成功读取，跳出循环
                                break
                            except UnicodeDecodeError:
                                self.log_message(f"{encoding} 编码读取失败，尝试下一种编码")
                                continue
                            except Exception as e:
                                self.log_message(f"读取文件时出错 ({encoding}): {str(e)}")
                        
                        # 如果所有编码都失败，使用二进制模式读取并强制解码
                        if not file_content:
                            try:
                                self.log_message("尝试二进制模式读取文件")
                                with open(file_path, 'rb') as f:
                                    binary_content = f.read()
                                    text_content = binary_content.decode('utf-8', errors='ignore')
                                    file_content = text_content.splitlines(True)
                            except Exception as e:
                                self.log_message(f"二进制模式读取失败: {str(e)}")
                                # 最后的尝试，使用最宽松的解码方式
                                try:
                                    with open(file_path, 'r', encoding='latin1') as f:
                                        file_content = f.readlines()
                                    self.log_message("使用latin1编码成功读取文件")
                                except Exception as e:
                                    self.log_message(f"所有读取方式都失败: {str(e)}")
                                    continue
                        
                        # 存储文件内容并搜索匹配行
                        if file_content:
                            content_lines = []
                            for line in file_content:
                                line = line.strip()
                                content_lines.append(line)
                                if keyword in line:
                                    # 提取时间并更新最早/最晚时间
                                    time_match = re.search(time_pattern, line)
                                    if time_match:
                                        # 使用常规时间戳
                                        time_str = time_match.group(1)
                                        try:
                                            # 根据时间格式进行灵活解析
                                            if '.' in time_str:
                                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                            else:
                                                # 不含毫秒的时间格式 HH:MM:SS
                                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                        except ValueError as e:
                                            print(f"时间解析错误: {str(e)}")
                                        if earliest_time is None or time_obj < earliest_time:
                                            earliest_time = time_obj
                                        if latest_time is None or time_obj > latest_time:
                                            latest_time = time_obj
                                    
                                    # 只显示文件名，不显示完整路径
                                    keyword_results.append(f"[{prefix}] {line}")
                            
                            # 存储文件内容
                            all_file_contents[file_path] = {
                                'content': content_lines, 
                                'prefix': prefix,
                                'file_name': file_name
                            }
                else:
                    # 通过SSH搜索远程文件
                    # 初始化SSH连接（如果还没有）
                    if not hasattr(self, 'log_collector') or not self.log_collector.is_connected():
                        # 获取SSH连接配置
                        config = {
                            'ssh': {
                                'host': self.host_input.text(),
                                'port': self.port_input.value(),
                                'username': self.username_input.text(),
                                'password': self.password_input.text()
                            }
                        }
                        # 创建连接
                        self.log_collector = LogCollector(config_file=None)
                        self.log_collector.config = config
                        self.log_collector.connect()
                        self.log_message("已连接到服务器")
                    
                    # 检查文件是否为压缩文件
                    if file_path.endswith('.zip'):
                        # 下载压缩文件到临时目录
                        temp_dir = tempfile.mkdtemp()
                        local_zip = os.path.join(temp_dir, os.path.basename(file_path))
                        self.log_collector.download_file(file_path, local_zip)
                        
                        # 解压并搜索
                        with zipfile.ZipFile(local_zip, 'r') as zip_ref:
                            for name in zip_ref.namelist():
                                # 为zip内每个文件提取前缀
                                name_prefix = re.match(r'([^_]+)_?', os.path.basename(name))
                                inner_prefix = name_prefix.group(1) if name_prefix else prefix
                                
                                with zip_ref.open(name) as f:
                                    # 尝试多种编码读取文件内容
                                    encodings = ['utf-8', 'gbk', 'gb18030', 'latin1']
                                    content_lines = []
                                    for encoding in encodings:
                                        try:
                                            f.seek(0)  # 重置文件指针
                                            content_lines = []
                                            for line in io.TextIOWrapper(f, encoding=encoding):
                                                line = line.strip()
                                                content_lines.append(line)
                                                if keyword in line:
                                                    # 提取时间并更新最早/最晚时间
                                                    time_match = re.search(time_pattern, line)
                                                    if time_match:
                                                        # 使用常规时间戳
                                                        time_str = time_match.group(1)
                                                        try:
                                                            # 根据时间格式进行灵活解析
                                                            if '.' in time_str:
                                                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                                            else:
                                                                # 不含毫秒的时间格式 HH:MM:SS
                                                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                                        except ValueError as e:
                                                            print(f"时间解析错误: {str(e)}")
                                                        if earliest_time is None or time_obj < earliest_time:
                                                            earliest_time = time_obj
                                                        if latest_time is None or time_obj > latest_time:
                                                            latest_time = time_obj
                                                    
                                                    keyword_results.append(f"[{inner_prefix}] {line}")
                                            
                                            # 存储文件内容
                                            all_file_contents[f"{file_path}/{name}"] = {
                                                'content': content_lines, 
                                                'prefix': inner_prefix,
                                                'file_name': os.path.basename(name)
                                            }
                                            # 如果成功读取，跳出循环
                                            break
                                        except UnicodeDecodeError:
                                            # 尝试下一种编码
                                            continue
                                        except Exception as e:
                                            self.log_message(f"读取压缩文件时出错 ({encoding}): {str(e)}")
                        
                        # 清理临时文件
                        shutil.rmtree(temp_dir)
                    else:
                        # 获取完整文件内容
                        # 首先下载文件到本地临时文件
                        temp_dir = tempfile.mkdtemp()
                        local_file = os.path.join(temp_dir, os.path.basename(file_path))
                        try:
                            self.log_collector.download_file(file_path, local_file)
                            
                            # 读取文件内容
                            encodings = ['utf-8', 'gbk', 'gb18030', 'latin1']
                            content_lines = []
                            for encoding in encodings:
                                try:
                                    with open(local_file, 'r', encoding=encoding) as f:
                                        content_lines = [line.strip() for line in f.readlines()]
                                    break
                                except UnicodeDecodeError:
                                    continue
                            
                            # 如果所有编码都失败，使用二进制模式读取
                            if not content_lines:
                                with open(local_file, 'rb') as f:
                                    content = f.read().decode('utf-8', errors='ignore')
                                    content_lines = [line.strip() for line in content.splitlines()]
                            
                            # 搜索关键字并保存文件内容
                            all_file_contents[file_path] = {
                                'content': content_lines,
                                'prefix': prefix
                            }
                            
                            # 在内容中搜索关键字
                            for line in content_lines:
                                if keyword in line:
                                    # 提取时间并更新最早/最晚时间
                                    time_match = re.search(time_pattern, line)
                                    if time_match:
                                        # 使用常规时间戳
                                        time_str = time_match.group(1)
                                        try:
                                            # 根据时间格式进行灵活解析
                                            if '.' in time_str:
                                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                            else:
                                                # 不含毫秒的时间格式 HH:MM:SS
                                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                        except ValueError as e:
                                            print(f"时间解析错误: {str(e)}")
                                        if earliest_time is None or time_obj < earliest_time:
                                            earliest_time = time_obj
                                        if latest_time is None or time_obj > latest_time:
                                            latest_time = time_obj
                                    
                                    keyword_results.append(f"[{prefix}] {line}")
                        
                        except Exception as e:
                            self.log_message(f"下载或处理远程文件失败: {str(e)}")
                            # 直接在远程搜索
                            command = f"grep -F '{keyword}' '{file_path}'"
                            self.log_message(f"执行搜索命令: {command}")
                            output = self.log_collector.execute_command(command)
                            
                            # 处理命令输出结果
                            if output:
                                # 尝试多种编码解码输出
                                output_lines = None
                                try:
                                    output_lines = output.splitlines()
                                except UnicodeDecodeError:
                                    # 可能字符编码有问题，尝试不同的编码
                                    try:
                                        output_lines = output.decode('gbk').splitlines()
                                    except UnicodeDecodeError:
                                        try:
                                            output_lines = output.decode('utf-8', errors='ignore').splitlines()
                                        except Exception as e:
                                            self.log_message(f"解码命令输出出错: {str(e)}")
                                            output_lines = []
                                
                                # 处理每一行结果
                                for line in output_lines:
                                    line = line.strip()
                                    # 提取时间并更新最早/最晚时间
                                    time_match = re.search(time_pattern, line)
                                    if time_match:
                                        # 使用常规时间戳
                                        time_str = time_match.group(1)
                                        try:
                                            # 根据时间格式进行灵活解析
                                            if '.' in time_str:
                                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                            else:
                                                # 不含毫秒的时间格式 HH:MM:SS
                                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                        except ValueError as e:
                                            print(f"时间解析错误: {str(e)}")
                                        if earliest_time is None or time_obj < earliest_time:
                                            earliest_time = time_obj
                                        if latest_time is None or time_obj > latest_time:
                                            latest_time = time_obj
                                    
                                    self.log_message(f"处理搜索结果: {line[:100]}")  # 只显示前100个字符以免日志过长
                                    keyword_results.append(f"[{prefix}] {line}")
                        finally:
                            # 清理临时文件
                            shutil.rmtree(temp_dir)
            
            # 检查是否找到了时间范围
            if earliest_time and latest_time:
                self.log_message(f"找到时间范围: {earliest_time.strftime('%H:%M:%S.%f')[:-3]} - {latest_time.strftime('%H:%M:%S.%f')[:-3]}")
                
                # 如果最早和最晚时间相同，扩展时间范围（前后5分钟）
                if earliest_time == latest_time:
                    earliest_time = earliest_time - timedelta(minutes=5)
                    latest_time = latest_time + timedelta(minutes=5)
                    self.log_message(f"扩展时间范围: {earliest_time.strftime('%H:%M:%S.%f')[:-3]} - {latest_time.strftime('%H:%M:%S.%f')[:-3]}")
                
                # 整理所有结果，确保正确添加前缀
                sorted_results = []
                displayed_lines = set()  # 用于跟踪已经添加的行，避免重复
                
                # 优化时间范围处理：确保开始时间正确设置
                if earliest_time == latest_time:
                    # 如果开始时间和结束时间相同，向前扩展一分钟
                    earliest_time = earliest_time - timedelta(minutes=1)
                
                self.log_message(f"时间范围: {earliest_time.strftime('%H:%M:%S.%f')} - {latest_time.strftime('%H:%M:%S.%f')}")
                
                # 第二阶段：在确定的时间范围内，提取所有日志行并显示
                self.log_message(f"提取时间范围内的所有日志行")
                
                # 遍历所有文件，提取在时间范围内的所有日志
                for file_path, file_data in all_file_contents.items():
                    content_lines = file_data['content']
                    prefix = file_data['prefix']
                    
                    # 识别所有时间戳行
                    i = 0
                    while i < len(content_lines):
                        line = content_lines[i].strip()
                        
                        # 检查是否包含时间戳（可能是日志块开始）
                        time_match = re.search(time_pattern, line)
                        
                        # 不再单独处理含有RegTime的JSON行
                        if time_match:
                            # 提取时间
                            time_str = time_match.group(1)
                            try:
                                # 根据时间格式进行灵活解析
                                if '.' in time_str:
                                    # 含有毫秒的时间格式 HH:MM:SS.fff
                                    time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                                else:
                                    # 不含毫秒的时间格式 HH:MM:SS
                                    time_obj = datetime.strptime(time_str, '%H:%M:%S')
                                
                                # 检查是否在时间范围内
                                if earliest_time <= time_obj <= latest_time:
                                    # 确定日志块的结束
                                    block_end = i
                                    for j in range(i+1, min(len(content_lines), i+20)):
                                        next_line = content_lines[j].strip()
                                        # 只检查常规时间戳，不将RegTime视为新日志块的开始
                                        if re.search(time_pattern, next_line) is not None:
                                            # 发现下一个时间戳，本块结束
                                            break
                                        block_end = j
                                    
                                    # 获取完整的日志块
                                    block_lines = content_lines[i:block_end+1]
                                    
                                    # 检查此日志块是否已被处理，避免重复
                                    block_text = '\n'.join(block_lines)
                                    if block_text not in displayed_lines:
                                        # 格式化并添加日志块
                                        # 只为第一行（时间行）添加前缀
                                        formatted_block = [f"[{prefix}] {block_lines[0]}"]
                                        formatted_block.extend(block_lines[1:])
                                        
                                        # 添加到排序结果
                                        sorted_results.append((time_obj, '\n'.join(formatted_block)))
                                        
                                        # 标记为已处理
                                        displayed_lines.add(block_text)
                                    
                                    # 跳过已处理的行
                                    i = block_end + 1
                                    continue
                            except ValueError:
                                # 时间解析错误，继续处理
                                pass
                        i += 1
                
                # 如果关键字匹配的结果中有一些不在文件内容中（例如直接grep输出），也需要处理
                for line in keyword_results:
                    # 检查是否已经处理过这行
                    if line in displayed_lines:
                        continue
                    
                    # 从行中提取内容
                    content = line.split('] ', 1)[1] if '] ' in line else line
                    
                    # 只检查常规时间戳，不处理RegTime
                    time_match = re.search(time_pattern, content)
                    if time_match:
                        # 使用常规时间戳
                        time_str = time_match.group(1)
                        try:
                            # 根据时间格式进行灵活解析
                            if '.' in time_str:
                                # 含有毫秒的时间格式 HH:MM:SS.fff
                                time_obj = datetime.strptime(time_str, '%H:%M:%S.%f')
                            else:
                                # 不含毫秒的时间格式 HH:MM:SS
                                time_obj = datetime.strptime(time_str, '%H:%M:%S')
                            
                            # 如果成功提取到时间并在范围内，尝试构建日志块
                            if earliest_time <= time_obj <= latest_time:
                                # 查找该行在 keyword_results 中的索引
                                try:
                                    line_index = keyword_results.index(line)
                                    
                                    # 尝试构建日志块，最多查找后面10行
                                    block_lines = [line]
                                    for j in range(line_index + 1, min(len(keyword_results), line_index + 10)):
                                        next_line = keyword_results[j]
                                        next_content = next_line.split('] ', 1)[1] if '] ' in next_line else next_line
                                        
                                        # 只检查常规时间戳，不检查RegTime
                                        if re.search(time_pattern, next_content) is not None:
                                            break
                                            
                                        # 将行添加到当前块
                                        block_lines.append(next_line)
                                    
                                    # 合并日志块文本
                                    block_text = '\n'.join(block_lines)
                                    
                                    # 检查此日志块是否已处理
                                    if not any(block_text in existing for existing in displayed_lines):
                                        sorted_results.append((time_obj, block_text))
                                        
                                        # 将块中所有行标记为已处理
                                        for block_line in block_lines:
                                            displayed_lines.add(block_line)
                                except ValueError:
                                    # 如果无法找到该行的索引，添加单行
                                    if line not in displayed_lines:
                                        sorted_results.append((time_obj, line))
                                        displayed_lines.add(line)
                        except ValueError:
                            # 时间解析错误，继续下一行
                            continue
                
                # 按时间排序
                sorted_results.sort(key=lambda x: x[0])
                
                # 提取排序后结果中的最早和最晚时间
                if sorted_results:
                    actual_earliest_time = sorted_results[0][0]
                    actual_latest_time = sorted_results[-1][0]
                    self.log_message(f"实际日志块时间范围: {actual_earliest_time.strftime('%H:%M:%S.%f')[:-3]} - {actual_latest_time.strftime('%H:%M:%S.%f')[:-3]}")
                    
                    # 计算时间差异
                    if actual_earliest_time > earliest_time:
                        time_diff = actual_earliest_time - earliest_time
                        self.log_message(f"注意: 实际最早时间比设定晚 {time_diff.total_seconds():.3f} 秒")
                    elif actual_earliest_time < earliest_time:
                        time_diff = earliest_time - actual_earliest_time
                        self.log_message(f"注意: 实际最早时间比设定早 {time_diff.total_seconds():.3f} 秒")
                        
                    if actual_latest_time < latest_time:
                        time_diff = latest_time - actual_latest_time
                        self.log_message(f"注意: 实际最晚时间比设定早 {time_diff.total_seconds():.3f} 秒")
                    elif actual_latest_time > latest_time:
                        time_diff = actual_latest_time - latest_time
                        self.log_message(f"注意: 实际最晚时间比设定晚 {time_diff.total_seconds():.3f} 秒")
                
                # 只保留排序后的内容
                final_results = [item[1] for item in sorted_results]
                
                # 显示搜索结果
                self.result_text.setPlainText('\n'.join(final_results))
                self.log_message(f"搜索完成，找到 {len(final_results)} 个时间范围内的日志块")
            else:
                # 如果没找到时间范围，处理原始搜索结果
                processed_results = []
                displayed_lines = set()  # 用于跟踪已经添加的行，避免重复
                
                # 对keyword_results中的每个结果进行分析和格式化
                for line in keyword_results:
                    # 检查是否已经处理过这行
                    if line in displayed_lines:
                        continue
                    
                    # 提取内容
                    content = line.split('] ', 1)[1] if '] ' in line else line
                    
                    # 检查是否包含时间戳，只匹配常规时间戳
                    has_timestamp = re.search(time_pattern, content) is not None
                    
                    # 如果含有时间戳，尝试构建日志块
                    if has_timestamp:
                        try:
                            line_index = keyword_results.index(line)
                            
                            # 尝试构建日志块，最多查找后面10行
                            block_lines = [line]
                            for j in range(line_index + 1, min(len(keyword_results), line_index + 10)):
                                next_line = keyword_results[j]
                                next_content = next_line.split('] ', 1)[1] if '] ' in next_line else next_line
                                
                                # 只检查是否有常规时间戳
                                if re.search(time_pattern, next_content) is not None:
                                    break
                                    
                                # 将行添加到当前块
                                block_lines.append(next_line)
                            
                            # 合并日志块文本
                            block_text = '\n'.join(block_lines)
                            
                            # 将整个块添加到结果中
                            processed_results.append(block_text)
                            
                            # 标记所有行为已处理
                            for block_line in block_lines:
                                displayed_lines.add(block_line)
                            
                            # 继续处理下一行
                            continue
                        except ValueError:
                            # 如果构建块失败，回退到单行处理
                            pass
                    
                    # 单行处理：只保留有常规时间戳的行
                    if has_timestamp:
                        processed_results.append(line)
                        displayed_lines.add(line)
                
                # 显示处理结果
                self.result_text.setPlainText('\n'.join(processed_results))
                self.log_message(f"搜索完成，找到 {len(processed_results)} 个有效匹配项，未找到时间范围")
        except Exception as e:
            self.log_message(f"搜索失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"搜索失败：\n{str(e)}")
        finally:
            # 关闭进度对话框
            progress.setValue(len(selected_files))

    def export_results(self):
        """导出搜索结果"""
        # 获取搜索结果
        results = self.result_text.toPlainText()
        if not results:
            QMessageBox.warning(self, "警告", "没有搜索结果可导出")
            return
        
        # 选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存搜索结果", os.path.expanduser("~") + "/search_results.txt", "文本文件 (*.txt)"
        )
        
        if not file_path:
            return
        
        # 保存文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(results)
            
            self.log_message(f"搜索结果已导出到: {file_path}")
            QMessageBox.information(self, "导出成功", f"搜索结果已导出到:\n{file_path}")
        except Exception as e:
            self.log_message(f"导出失败: {str(e)}")
            QMessageBox.critical(self, "导出失败", f"导出失败：\n{str(e)}")
    
    def view_full_log(self):
        """查看完整日志"""
        # 获取选中的日志文件
        selected_rows = self.log_list.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请先选择要查看的日志文件")
            return
        
        # 只处理第一个选中的文件
        row = selected_rows[0].row()
        name_item = self.log_list.item(row, 0)
        file_path = name_item.data(Qt.ItemDataRole.UserRole)
        
        if not file_path:
            QMessageBox.warning(self, "警告", "无法获取文件路径")
            return
        
        # 获取SSH连接配置
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
        
        # 清空结果显示区
        self.result_text.clear()
        self.result_text.setPlainText("正在加载完整日志，请稍候...")
        
        # 创建并启动工作线程
        self.log_message(f"正在获取完整日志: {os.path.basename(file_path)}")
        self.analysis_worker = LogAnalysisWorker(config, mode='full', log_path=file_path)
        self.analysis_worker.complete_log.connect(self.display_full_log)
        self.analysis_worker.error.connect(self.analysis_error)
        self.analysis_worker.log_message_signal.connect(self.log_message)
        self.analysis_worker.start()
    
    def display_full_log(self, content):
        """显示完整日志"""
        self.result_text.setPlainText(content)
        self.log_message("完整日志加载完成")
    
    def analysis_error(self, error_message):
        """错误处理"""
        self.log_message(f"错误: {error_message}")
        QMessageBox.critical(self, "错误", error_message)
    
    def export_time_range_logs(self):
        """导出时间范围内的日志"""
        # 获取选中的日志文件
        selected_rows = self.log_list.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.warning(self, "警告", "请先选择要导出的日志文件")
            return
        
        # 获取选中文件的路径
        selected_files = []
        for row in selected_rows:
            name_item = self.log_list.item(row.row(), 0)
            file_path = name_item.data(Qt.ItemDataRole.UserRole)
            if file_path:
                selected_files.append(file_path)
        
        if not selected_files:
            QMessageBox.warning(self, "警告", "无法获取文件路径")
            return
        
        # 获取时间范围
        start_date, end_date = self.get_date_range_analysis()
        earliest_time = datetime.strptime(start_date, '%Y-%m-%d')
        latest_time = datetime.strptime(end_date, '%Y-%m-%d')
        latest_time = latest_time.replace(hour=23, minute=59, second=59)
        
        # 选择保存路径
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存时间范围日志", os.path.expanduser("~") + f"/logs_{start_date}_to_{end_date}.txt", "文本文件 (*.txt)"
        )
        
        if not file_path:
            return
        
        # 获取SSH连接配置
        config = {
            'ssh': {
                'host': self.host_input.text(),
                'port': self.port_input.value(),
                'username': self.username_input.text(),
                'password': self.password_input.text()
            }
        }
        
        # 创建进度对话框
        progress_dialog = QProgressDialog("正在导出时间范围日志...", "取消", 0, len(selected_files), self)
        progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dialog.show()
        
        # 开始导出
        try:
            # 匹配时间戳的正则表达式模式，这里假设日志中的时间格式为yyyy-MM-dd HH:mm:ss
            time_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
            
            # 连接到服务器
            collector = LogCollector(config_file=None)
            collector.config = config
            collector.connect()
            
            # 创建输出文件
            with open(file_path, 'w', encoding='utf-8') as output_file:
                # 写入头部信息
                output_file.write(f"# 时间范围日志导出\n")
                output_file.write(f"# 时间范围: {start_date} 到 {end_date}\n")
                output_file.write(f"# 导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                # 处理每个文件
                for i, log_path in enumerate(selected_files):
                    progress_dialog.setValue(i)
                    if progress_dialog.wasCanceled():
                        break
                    
                    log_name = os.path.basename(log_path)
                    
                    # 检查是否为zip文件
                    if log_path.lower().endswith('.zip'):
                        # 处理压缩文件
                        self.log_message(f"处理压缩文件: {log_name}")
                        
                        # 获取到本地缓存
                        cache_path = None
                        try:
                            import tempfile
                            import hashlib
                            
                            # 创建缓存目录
                            cache_dir = os.path.join(tempfile.gettempdir(), "log_cache")
                            os.makedirs(cache_dir, exist_ok=True)
                            
                            # 计算文件哈希作为缓存文件名
                            file_hash = hashlib.md5(log_path.encode()).hexdigest()
                            file_ext = os.path.splitext(log_path)[1]
                            cache_path = os.path.join(cache_dir, f"{file_hash}{file_ext}")
                            
                            # 如果缓存不存在，下载文件
                            if not os.path.exists(cache_path):
                                self.log_message(f"下载文件到本地缓存: {log_name}")
                                collector.sftp.get(log_path, cache_path)
                            
                            # 解压并处理文件
                            import zipfile
                            import tempfile
                            
                            # 创建临时目录
                            temp_dir = tempfile.mkdtemp()
                            
                            try:
                                with zipfile.ZipFile(cache_path, 'r') as zip_ref:
                                    # 解压所有文件
                                    zip_ref.extractall(temp_dir)
                                    
                                    # 处理解压后的每个文件
                                    for root, dirs, files in os.walk(temp_dir):
                                        for file in files:
                                            if file.endswith('.log'):
                                                file_path = os.path.join(root, file)
                                                
                                                # 读取文件内容
                                                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                                    content = f.read()
                                                
                                                # 写入文件标题
                                                output_file.write(f"\n\n===== {log_name}/{file} =====\n\n")
                                                
                                                # 过滤时间范围内的日志
                                                filtered_lines = []
                                                for line in content.splitlines():
                                                    match = re.search(time_pattern, line)
                                                    if match:
                                                        try:
                                                            timestamp_str = match.group(1)
                                                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                                            if earliest_time <= timestamp <= latest_time:
                                                                filtered_lines.append(line)
                                                        except:
                                                            # 如果时间解析失败，保留这一行
                                                            if filtered_lines:
                                                                filtered_lines.append(line)
                                                    else:
                                                        # 如果没有时间戳，可能是上一条日志的延续
                                                        if filtered_lines:
                                                            filtered_lines.append(line)
                                                
                                                # 写入过滤后的内容
                                                output_file.write('\n'.join(filtered_lines))
                            finally:
                                # 清理临时目录
                                import shutil
                                shutil.rmtree(temp_dir)
                        except Exception as e:
                            self.log_message(f"处理压缩文件失败: {str(e)}")
                            continue
                    else:
                        # 处理普通日志文件
                        self.log_message(f"处理日志文件: {log_name}")
                        
                        # 获取文件内容
                        if collector.is_remote_windows():
                            cmd = f'type "{log_path}"'
                        else:
                            cmd = f'cat "{log_path}"'
                        
                        stdin, stdout, stderr = collector.ssh.exec_command(cmd)
                        try:
                            content = stdout.read().decode('utf-8', errors='ignore')
                        except:
                            content = stdout.read().decode('gbk', errors='ignore')
                        
                        # 写入文件标题
                        output_file.write(f"\n\n===== {log_name} =====\n\n")
                        
                        # 过滤时间范围内的日志
                        filtered_lines = []
                        for line in content.splitlines():
                            match = re.search(time_pattern, line)
                            if match:
                                try:
                                    timestamp_str = match.group(1)
                                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                    if earliest_time <= timestamp <= latest_time:
                                        filtered_lines.append(line)
                                except:
                                    # 如果时间解析失败，保留这一行
                                    if filtered_lines:
                                        filtered_lines.append(line)
                            else:
                                # 如果没有时间戳，可能是上一条日志的延续
                                if filtered_lines:
                                    filtered_lines.append(line)
                        
                        # 写入过滤后的内容
                        output_file.write('\n'.join(filtered_lines))
                
                self.log_message(f"时间范围日志已导出到: {file_path}")
                QMessageBox.information(self, "导出成功", f"时间范围日志已导出到:\n{file_path}")
        except Exception as e:
            self.log_message(f"导出时间范围日志失败: {str(e)}")
            QMessageBox.critical(self, "导出失败", f"导出失败：\n{str(e)}")
        finally:
            # 关闭连接并关闭进度对话框
            if 'collector' in locals():
                collector.close()
            progress_dialog.accept()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
 