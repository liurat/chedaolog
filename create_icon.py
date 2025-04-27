from PIL import Image, ImageDraw, ImageFont
import os

def create_icon():
    # 创建一个正方形图像
    size = 256
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 绘制圆形背景
    margin = 10
    draw.ellipse([margin, margin, size-margin, size-margin], 
                 fill='#2196F3')  # 使用Material Design蓝色
    
    # 绘制文字
    text = "LOG"
    try:
        # 尝试使用Arial字体，如果不存在则使用默认字体
        font = ImageFont.truetype("arial.ttf", size=100)
    except:
        font = ImageFont.load_default()
    
    # 获取文字大小并居中绘制
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = (size - text_width) // 2
    text_y = (size - text_height) // 2
    draw.text((text_x, text_y), text, fill='white', font=font)
    
    # 保存为ICO文件
    image.save('app.ico', format='ICO')
    print("图标文件已创建：app.ico")

if __name__ == '__main__':
    create_icon() 