import PyInstaller.__main__

PyInstaller.__main__.run([
    'main.py',
    '--onefile',
    '--windowed',
	'--noconfirm',
	'-nFluxUI',
	'-iassets/flux.jpg'
])