import flet as ft
import os
from typing import List, Optional, Callable
from pathlib import Path

class TransferCard:
    """A card widget that displays transfer progress"""
    def __init__(self, file_name: str, status_text: str, progress: float = 0):
        self.card = ft.Card(
            content=ft.Container(
                content=ft.Column([
                    ft.Text(file_name, size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(status_text, size=14),
                    ft.ProgressBar(value=progress, width=400)
                ]),
                padding=15
            ),
            margin=10
        )

    def update(self, status_text: str, progress: float):
        """Update the card's status and progress"""
        column = self.card.content.content
        column.controls[1].value = status_text
        column.controls[2].value = progress

class FileTransferUI:
    """Main UI component for file transfer"""
    def __init__(self, page: ft.Page):
        self.page = page
        self.setup_page()
        self.transfer_cards = {}
        self.selected_files: List[str] = []
        self.save_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        
        # Ensure save directory exists
        os.makedirs(self.save_directory, exist_ok=True)
        
        # File pickers
        self.pick_files_dialog = ft.FilePicker(on_result=self.pick_files_result)
        self.save_dir_dialog = ft.FilePicker(on_result=self.change_save_dir_result)
        self.page.overlay.extend([self.pick_files_dialog, self.save_dir_dialog])
        
        # UI Components
        self.selected_files_text = ft.Text("No files selected", size=14)
        self.save_dir_text = ft.Text(f"Save directory: {self.save_directory}", size=14)
        self.transfer_code_field = ft.TextField(
            label="Transfer Code",
            hint_text="Enter 6-digit code",
            width=300
        )
        
        self.sender_password_field = ft.TextField(
            label="Transfer Password",
            hint_text="Enter password for encryption",
            password=True,
            width=300
        )
        
        self.receiver_password_field = ft.TextField(
            label="Transfer Password",
            hint_text="Enter password for decryption",
            password=True,
            width=300
        )
        
        self.transfers_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True
        )
        
        self.build_ui()
    
    def setup_page(self):
        """Configure the page settings"""
        self.page.title = "FLUX"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.window_width = 1000
        self.page.window_height = 800
        self.page.padding = 0
        self.page.spacing = 0
        self.page.window_center_x = True
        self.page.window_center_y = True
        self.page.bgcolor = "#1e1e1e"
    
    def build_ui(self):
        """Build the main UI layout"""
        self.page.add(
            ft.Container(
                content=ft.Column([
                    # Header
                    self.build_header(),
                    
                    # Instructions
                    self.build_instructions(),
                    
                    # Send Files Section
                    self.build_send_section(),
                    
                    # Receive Files Section
                    self.build_receive_section(),
                    
                    # Transfers Section
                    self.build_transfers_section()
                ]),
                expand=True
            )
        )
    
    def build_header(self) -> ft.Container:
        """Build the header section"""
        return ft.Container(
            content=ft.Row([
                ft.Text("FLUX", size=30, weight=ft.FontWeight.BOLD),
                ft.Text("File Transfer Utility", size=16, italic=True)
            ], alignment=ft.MainAxisAlignment.CENTER),
            padding=20,
            bgcolor="#2d2d2d"
        )
    
    def build_instructions(self) -> ft.Container:
        """Build the instructions section"""
        return ft.Container(
            content=ft.Column([
                ft.Text(
                    "Share the transfer code with the receiver to start the transfer",
                    size=16,
                    text_align=ft.TextAlign.CENTER
                )
            ], alignment=ft.MainAxisAlignment.CENTER),
            padding=10
        )
    
    def build_send_section(self) -> ft.Container:
        """Build the send files section"""
        return ft.Container(
            content=ft.Column([
                ft.Text("Send Files", size=20, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.ElevatedButton(
                        "Select Files",
                        icon=ft.icons.UPLOAD_FILE,
                        on_click=lambda _: self.pick_files_dialog.pick_files(
                            allow_multiple=True
                        )
                    ),
                    self.selected_files_text
                ]),
                self.sender_password_field,
                ft.ElevatedButton(
                    "Send Files",
                    icon=ft.icons.SEND,
                    on_click=self.send_files_click
                )
            ]),
            padding=20,
            margin=10,
            bgcolor="#2d2d2d",
            border_radius=10
        )
    
    def build_receive_section(self) -> ft.Container:
        """Build the receive files section"""
        return ft.Container(
            content=ft.Column([
                ft.Text("Receive Files", size=20, weight=ft.FontWeight.BOLD),
                ft.Row([
                    self.save_dir_text,
                    ft.IconButton(
                        icon=ft.icons.FOLDER_OPEN,
                        tooltip="Change save directory",
                        on_click=lambda _: self.save_dir_dialog.get_directory_path()
                    )
                ]),
                self.transfer_code_field,
                self.receiver_password_field,
                ft.Text("Enter the transfer code and password to receive files", size=14)
            ]),
            padding=20,
            margin=10,
            bgcolor="#2d2d2d",
            border_radius=10
        )
    
    def build_transfers_section(self) -> ft.Container:
        """Build the transfers section"""
        return ft.Container(
            content=ft.Column([
                ft.Text("Transfers", size=20, weight=ft.FontWeight.BOLD),
                self.transfers_column
            ]),
            padding=20,
            margin=10,
            bgcolor="#2d2d2d",
            border_radius=10,
            expand=True
        )
    
    def pick_files_result(self, e: ft.FilePickerResultEvent):
        """Handle file selection result"""
        if e.files:
            self.selected_files = [file.path for file in e.files]
            self.selected_files_text.value = f"Selected {len(self.selected_files)} files"
            self.page.update()
    
    def change_save_dir_result(self, e: ft.FilePickerResultEvent):
        """Handle save directory selection result"""
        if e.path:
            self.save_directory = e.path
            self.save_dir_text.value = f"Save directory: {self.save_directory}"
            self.page.update()
    
    def send_files_click(self, e):
        """Handle send files button click"""
        if not self.selected_files:
            self.show_error("Please select files first")
            return
        
        password = self.sender_password_field.value.strip()
        if not password:
            self.show_error("Please enter a transfer password")
            return
        
        # Notify callback about the send request
        if hasattr(self, 'on_send_files'):
            self.on_send_files(self.selected_files, password)
        
        # Clear selection after sending
        self.selected_files = []
        self.selected_files_text.value = "No files selected"
        self.page.update()
    
    def show_error(self, message: str):
        """Show an error message"""
        self.page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            action="OK"
        )
        self.page.snack_bar.open = True
        self.page.update()
    
    def update_transfer_progress(self, transfer_id: str, progress: float, status_text: str):
        """Update the progress of a transfer"""
        if transfer_id in self.transfer_cards:
            self.transfer_cards[transfer_id].update(status_text, progress/100)
        else:
            card = TransferCard("Unknown file", status_text, progress/100)
            self.transfer_cards[transfer_id] = card
            self.transfers_column.controls.append(card.card)
        self.page.update()
    
    def set_on_send_files(self, callback: Callable[[List[str], str], None]):
        """Set the callback for when files are sent"""
        self.on_send_files = callback
    
    def set_on_password_change(self, callback: Callable[[str], None]):
        """Set the callback for when the receiver password changes"""
        self.receiver_password_field.on_change = lambda e: callback(e.control.value)