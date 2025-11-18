"""
Script to add white background to favicon images
"""
from PIL import Image
import os

def add_white_background(input_path, output_path=None):
    """Add white background to a PNG image with transparency"""
    if output_path is None:
        output_path = input_path
    
    # Open the image
    img = Image.open(input_path)
    
    # Convert to RGBA if not already
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    # Create white background
    background = Image.new('RGBA', img.size, (255, 255, 255, 255))
    
    # Composite the image over white background
    result = Image.alpha_composite(background, img)
    
    # Convert to RGB (remove alpha channel)
    result = result.convert('RGB')
    
    # Save
    result.save(output_path, 'PNG')
    print(f"✓ Updated: {output_path}")

if __name__ == '__main__':
    icons_dir = os.path.join(os.path.dirname(__file__), 'icons')
    
    # List of favicon files to update
    favicon_files = [
        'favicon-96x96.png',
        'web-app-manifest-192x192.png',
        'web-app-manifest-512x512.png',
        'apple-touch-icon.png'
    ]
    
    print("Adding white background to favicon images...")
    print("-" * 50)
    
    for filename in favicon_files:
        filepath = os.path.join(icons_dir, filename)
        if os.path.exists(filepath):
            try:
                add_white_background(filepath)
            except Exception as e:
                print(f"✗ Error processing {filename}: {e}")
        else:
            print(f"⚠ File not found: {filename}")
    
    print("-" * 50)
    print("Done! Restart your browser to see the changes.")
