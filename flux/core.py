import os
import threading
from typing import List, Optional

from .ui import FileTransferUI
from .network import send_file, start_receiver_server, get_local_ip

class FluxApp:
    """Main application class that coordinates UI and file transfer operations"""
    def __init__(self):
        self.selected_files = []
        self.receiver_server = None
        self.local_ip = get_local_ip()
        self.save_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        self.transfer_password = ""
        
        # Ensure save directory exists
        os.makedirs(self.save_directory, exist_ok=True)
    
    def main(self, page):
        """Initialize and run the main application"""
        # Create UI instance
        self.ui = FileTransferUI(page)
        
        # Set up callbacks
        self.ui.set_on_send_files(self.handle_send_files)
        self.ui.set_on_password_change(self.handle_password_change)
        
        # Initialize UI state
        self.ui.save_directory = self.save_directory
    
    def handle_send_files(self, files: List[str], password: str):
        """Handle the send files request from UI"""
        for file_path in files:
            def send_file_thread(file_path=file_path):
                send_file(
                    file_path,
                    password,
                    progress_callback=self.ui.update_transfer_progress
                )
            
            thread = threading.Thread(target=send_file_thread)
            thread.daemon = True
            thread.start()
    
    def handle_password_change(self, password: str):
        """Handle password change for receiver"""
        self.transfer_password = password
        self.update_receiver_server()
    
    def update_receiver_server(self):
        """Update the receiver server with current settings"""
        if self.receiver_server:
            self.receiver_server.close()
        
        code = self.ui.transfer_code_field.value.strip()
        if code and len(code) == 6:  # CODE_LENGTH from network module
            self.receiver_server = start_receiver_server(
                self.save_directory,
                password=self.transfer_password,
                transfer_code=code,
                progress_callback=self.ui.update_transfer_progress
            )