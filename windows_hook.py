import os
import sys

# 确保在Windows上正确处理高DPI显示
if sys.platform.startswith('win'):
    import ctypes
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

# 确保能够找到打包的数据文件
def get_data_path(relative_path):
    if getattr(sys, 'frozen', False):
        # 如果是打包后的exe
        base_path = sys._MEIPASS
    else:
        # 如果是开发环境
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)

# 设置工作目录
if getattr(sys, 'frozen', False):
    # 使用exe所在目录作为工作目录
    os.chdir(os.path.dirname(sys.executable)) 