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
                           QSizePolicy)
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
                                files = stdout.read().decode('utf-8').splitlines()
                                
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
        
        self.path_list = QListWidget()
        self.path_list.setMinimumHeight(100)
        
        # 路径操作按钮
        path_buttons = QHBoxLayout()
        add_path_btn = QPushButton("添加目录")
        remove_path_btn = QPushButton("删除选中")
        path_buttons.addWidget(add_path_btn)
        path_buttons.addWidget(remove_path_btn)
        
        path_layout.addWidget(self.path_list)
        path_layout.addLayout(path_buttons)
        
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
        
        self.path_list = QListWidget()
        self.path_list.setMinimumHeight(100)
        
        # 路径操作按钮
        path_buttons = QHBoxLayout()
        add_path_btn = QPushButton("添加目录")
        remove_path_btn = QPushButton("删除选中")
        path_buttons.addWidget(add_path_btn)
        path_buttons.addWidget(remove_path_btn)
        
        path_layout.addWidget(self.path_list)
        path_layout.addLayout(path_buttons)
        
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
        
        # 添加待实现提示
        analysis_info = QLabel("日志分析功能正在开发中，敬请期待...")
        analysis_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        analysis_info.setStyleSheet("font-size: 16pt; color: gray;")
        analysis_layout.addWidget(analysis_info)
        
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
        self.log_display.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {message}")
    
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

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 