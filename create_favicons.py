"""
Create proper favicons from logo with white background
"""
from PIL import Image
import os

def create_favicon_from_logo(logo_path, output_path, size):
    """Create a favicon from logo with white background and padding"""
    # Open the logo
    logo = Image.open(logo_path)
    
    # Convert to RGBA if needed
    if logo.mode != 'RGBA':
        logo = logo.convert('RGBA')
    
    # Calculate padding (10% of target size)
    padding = int(size * 0.1)
    inner_size = size - (2 * padding)
    
    # Resize logo to fit with padding
    logo.thumbnail((inner_size, inner_size), Image.Resampling.LANCZOS)
    
    # Create white background
    favicon = Image.new('RGB', (size, size), (255, 255, 255))
    
    # Calculate position to center the logo
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    
    # Paste logo onto white background
    if logo.mode == 'RGBA':
        favicon.paste(logo, (x, y), logo)
    else:
        favicon.paste(logo, (x, y))
    
    # Save
    favicon.save(output_path, 'PNG', optimize=True)
    print(f"✓ Created: {output_path} ({size}x{size})")

if __name__ == '__main__':
    icons_dir = os.path.join(os.path.dirname(__file__), 'icons')
    logo_path = os.path.join(icons_dir, 'scanmydata_logo_3000w.png')
    
    if not os.path.exists(logo_path):
        print(f"✗ Logo not found: {logo_path}")
        exit(1)
    
    print("Creating favicons from logo with white background...")
    print("-" * 50)
    
    # Create favicons in different sizes
    favicons_to_create = [
        ('favicon-96x96.png', 96),
        ('web-app-manifest-192x192.png', 192),
        ('web-app-manifest-512x512.png', 512),
        ('apple-touch-icon.png', 180),
    ]
    
    for filename, size in favicons_to_create:
        output_path = os.path.join(icons_dir, filename)
        try:
            create_favicon_from_logo(logo_path, output_path, size)
        except Exception as e:
            print(f"✗ Error creating {filename}: {e}")
    
    # Also create a 32x32 for favicon.ico fallback
    try:
        output_32 = os.path.join(icons_dir, 'favicon-32x32.png')
        create_favicon_from_logo(logo_path, output_32, 32)
    except Exception as e:
        print(f"✗ Error creating favicon-32x32.png: {e}")
    
    print("-" * 50)
    print("✓ Done! Clear browser cache and restart to see changes.")
    print("  Tip: Press Ctrl+Shift+R for hard refresh")
