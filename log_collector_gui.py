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
                           QCheckBox, QDateEdit, QDialog)
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
            collector = LogCollector(config_file=None)
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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("车道系统日志收集工具")
        self.setMinimumSize(800, 600)
        
        # 创建主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
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
        date_info = QLabel("注意：将自动匹配文件名中包含选定日期范围的日志文件\n支持的文件名格式：CenterDevCtrl_YYYY-MM-DD.log 或 CenterDevCtrl_YYYY-MM-DD.zip")
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
        
        # 添加所有组件到主布局
        layout.addWidget(ssh_group)
        layout.addWidget(date_group)
        layout.addWidget(path_group)
        layout.addWidget(self.progress_bar)
        layout.addWidget(log_group)
        layout.addLayout(button_layout)
        
        # 加载配置
        self.load_config()
    
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
        
        # 创建工作线程
        self.worker = LogCollectorWorker(config)
        self.worker.finished.connect(self.collection_finished)
        self.worker.error.connect(self.collection_error)
        self.worker.start()
    
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