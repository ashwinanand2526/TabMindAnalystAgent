import os
from PIL import Image, ImageDraw

def generate_icons():
    os.makedirs('icons', exist_ok=True)
    sizes = [16, 48, 128]
    
    for size in sizes:
        # Create an image with a nice neon gradient look (blue/purple)
        img = Image.new('RGBA', (size, size), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Draw a rounded circle representing tab/mind comparison
        margin = max(1, size // 10)
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=(41, 128, 185, 255),  # Deep blue
            outline=(155, 89, 182, 255),  # Amethyst purple
            width=max(1, size // 16)
        )
        
        # Draw inner magnifying glass or "T" graphic
        inner_margin = size // 3
        draw.line(
            [inner_margin, size // 2, size - inner_margin, size // 2],
            fill=(236, 240, 241, 255),
            width=max(1, size // 12)
        )
        draw.line(
            [size // 2, inner_margin, size // 2, size - inner_margin],
            fill=(236, 240, 241, 255),
            width=max(1, size // 12)
        )
        
        img.save(f'icons/icon{size}.png')
        print(f"Generated icons/icon{size}.png")

if __name__ == '__main__':
    generate_icons()
