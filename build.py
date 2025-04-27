import os
import sys
import shutil
from PyInstaller.__main__ import run

def build():
    # 清理之前的构建文件
    if os.path.exists('dist'):
        shutil.rmtree('dist')
    if os.path.exists('build'):
        shutil.rmtree('build')
    
    # 确定系统分隔符
    separator = ';' if sys.platform.startswith('win') else ':'
    
    # PyInstaller参数
    opts = [
        'log_collector_gui.py',  # 主程序文件
        '--name=车道系统日志收集工具',  # 输出文件名
        '--windowed',  # 不显示控制台窗口
        '--onefile',  # 打包成单个文件
        '--icon=app.ico',  # 应用图标
        f'--add-data=config.yaml{separator}.',  # 添加配置文件
        '--hidden-import=PyQt6.sip',  # 添加隐含依赖
        '--hidden-import=PyQt6.QtCore',
        '--hidden-import=PyQt6.QtGui',
        '--hidden-import=PyQt6.QtWidgets',
        '--noconfirm',  # 覆盖输出目录
        '--clean',  # 清理临时文件
    ]

    # 如果是Windows系统，添加一些特定的选项
    if sys.platform.startswith('win'):
        opts.extend([
            '--runtime-hook=windows_hook.py',  # Windows特定的运行时钩子
        ])

    # 运行PyInstaller
    run(opts)

    # 复制必要文件到dist目录
    if not os.path.exists('dist/config.yaml'):
        shutil.copy2('config.yaml', 'dist/')

    print("打包完成！")
    print("可执行文件位于 dist 目录中")

if __name__ == '__main__':
    build() 