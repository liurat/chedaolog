# 使用Windows Server Core基础镜像
FROM mcr.microsoft.com/windows/servercore:ltsc2019

# 设置工作目录
WORKDIR /app

# 下载并安装Python
ADD https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe /app/python-installer.exe
RUN start /wait python-installer.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0 && \
    del python-installer.exe

# 复制项目文件
COPY . /app/

# 安装依赖
RUN pip install -r requirements.txt

# 运行打包命令
CMD ["python", "build.py"] 