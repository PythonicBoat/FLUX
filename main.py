import flet as ft
from flux import FluxApp

def main():
    app = FluxApp()
    ft.app(target=app.main)

if __name__ == "__main__":
    main()