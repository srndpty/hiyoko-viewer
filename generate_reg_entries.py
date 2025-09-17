SUPPORTED_EXTENSIONS = [
    '.bmp', '.cur', '.gif', '.icns', '.ico', '.jfif', '.jpeg', '.jpg', 
    '.pbm', '.pdf', '.pgm', '.png', '.ppm', '.svg', '.svgz', '.tga', 
    '.tif', '.tiff', '.wbmp', '.webp', '.xbm', '.xpm'
]

# --- セクション2: FileAssociations の生成 ---
print("="*20)
print("以下の内容を [Capabilities\\FileAssociations] セクションに貼り付けてください:")
print("="*20)
for ext in sorted(SUPPORTED_EXTENSIONS):
    ext_upper = ext.replace('.', '').upper()
    print(f'"{ext}"="HiyokoViewer.AssocFile.{ext_upper}"')

print("\n\n")

# --- セクション3: AssocFile 定義の生成 ---
print("="*20)
print("以下の内容をセクション3 (AssocFile 定義) として貼り付けてください:")
print("="*20)
for ext in sorted(SUPPORTED_EXTENSIONS):
    ext_upper = ext.replace('.', '').upper()
    print(f'[HKEY_CURRENT_USER\\Software\\Classes\\HiyokoViewer.AssocFile.{ext_upper}]')
    print(f'@="{ext_upper} Image File"')
    print("") # 空行