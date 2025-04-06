import flet as ft
import os
import socket
import threading
import zstandard as zstd
import time
import uuid
import json
from pathlib import Path

# Constants for file transfer
BUFFER_SIZE = 4096
COMPRESSION_LEVEL = 3  # Moderate compression level
SERVER_PORT = 5555

# File transfer status tracking
active_transfers = {}

def get_local_ip():
    """Get the local IP address of the machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def compress_file(file_path, output_path=None):
    """Compress a file using zstandard"""
    if output_path is None:
        output_path = f"{file_path}.zst"
    
    cctx = zstd.ZstdCompressor(level=COMPRESSION_LEVEL)
    with open(file_path, 'rb') as f_in:
        with open(output_path, 'wb') as f_out:
            compressor = cctx.stream_writer(f_out)
            while True:
                chunk = f_in.read(BUFFER_SIZE)
                if not chunk:
                    break
                compressor.write(chunk)
            compressor.flush()
    return output_path

def decompress_file(compressed_path, output_path):
    """Decompress a file using zstandard"""
    dctx = zstd.ZstdDecompressor()
    with open(compressed_path, 'rb') as f_in:
        with open(output_path, 'wb') as f_out:
            decompressor = dctx.stream_writer(f_out)
            while True:
                chunk = f_in.read(BUFFER_SIZE)
                if not chunk:
                    break
                decompressor.write(chunk)
            decompressor.flush()
    return output_path

def send_file(file_path, receiver_ip, progress_callback=None):
    """Send a file to the receiver"""
    # Generate a unique transfer ID
    transfer_id = str(uuid.uuid4())
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    # Compress the file
    compressed_path = compress_file(file_path)
    compressed_size = os.path.getsize(compressed_path)
    
    # Prepare metadata
    metadata = {
        "transfer_id": transfer_id,
        "file_name": file_name,
        "original_size": file_size,
        "compressed_size": compressed_size
    }
    
    # Track this transfer
    active_transfers[transfer_id] = {
        "file_name": file_name,
        "status": "connecting",
        "progress": 0,
        "start_time": time.time()
    }
    
    # Update progress if callback provided
    if progress_callback:
        progress_callback(transfer_id, 0, "Connecting to receiver...")
    
    try:
        # Connect to receiver
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((receiver_ip, SERVER_PORT))
        
        # Send metadata first
        s.sendall(json.dumps(metadata).encode() + b"\n")
        
        # Update status
        active_transfers[transfer_id]["status"] = "sending"
        if progress_callback:
            progress_callback(transfer_id, 0, "Starting transfer...")
        
        # Send the compressed file
        bytes_sent = 0
        with open(compressed_path, 'rb') as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                s.sendall(chunk)
                bytes_sent += len(chunk)
                progress = int((bytes_sent / compressed_size) * 100)
                
                # Update progress
                active_transfers[transfer_id]["progress"] = progress
                if progress_callback:
                    progress_callback(transfer_id, progress, f"Sending: {progress}%")
        
        # Cleanup and finalize
        s.close()
        os.remove(compressed_path)  # Remove temporary compressed file
        
        active_transfers[transfer_id]["status"] = "completed"
        active_transfers[transfer_id]["progress"] = 100
        if progress_callback:
            progress_callback(transfer_id, 100, "Transfer completed")
        
        return True
    
    except Exception as e:
        # Handle errors
        active_transfers[transfer_id]["status"] = "failed"
        if progress_callback:
            progress_callback(transfer_id, 0, f"Error: {str(e)}")
        
        # Cleanup
        if os.path.exists(compressed_path):
            os.remove(compressed_path)
        
        return False

def start_receiver_server(save_dir, progress_callback=None):
    """Start a server to receive files"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', SERVER_PORT))
    server.listen(5)
    
    def handle_client(client_socket, client_address):
        try:
            # Receive metadata
            metadata_bytes = b""
            while b"\n" not in metadata_bytes:
                chunk = client_socket.recv(BUFFER_SIZE)
                if not chunk:
                    return
                metadata_bytes += chunk
            
            metadata_str, remaining_data = metadata_bytes.split(b"\n", 1)
            metadata = json.loads(metadata_str.decode())
            
            transfer_id = metadata["transfer_id"]
            file_name = metadata["file_name"]
            compressed_size = metadata["compressed_size"]
            
            # Create temporary file for compressed data
            temp_compressed_path = os.path.join(save_dir, f"{file_name}.zst.temp")
            final_output_path = os.path.join(save_dir, file_name)
            
            # Track this transfer
            active_transfers[transfer_id] = {
                "file_name": file_name,
                "status": "receiving",
                "progress": 0,
                "start_time": time.time()
            }
            
            # Update progress if callback provided
            if progress_callback:
                progress_callback(transfer_id, 0, "Starting to receive file...")
            
            # Write initial data if any
            bytes_received = len(remaining_data)
            with open(temp_compressed_path, 'wb') as f:
                f.write(remaining_data)
                
                # Continue receiving data
                while bytes_received < compressed_size:
                    chunk = client_socket.recv(BUFFER_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    bytes_received += len(chunk)
                    
                    # Update progress
                    progress = int((bytes_received / compressed_size) * 100)
                    active_transfers[transfer_id]["progress"] = progress
                    if progress_callback:
                        progress_callback(transfer_id, progress, f"Receiving: {progress}%")
            
            # Decompress the file
            if progress_callback:
                progress_callback(transfer_id, 100, "Decompressing file...")
            
            decompress_file(temp_compressed_path, final_output_path)
            
            # Cleanup
            os.remove(temp_compressed_path)
            
            active_transfers[transfer_id]["status"] = "completed"
            if progress_callback:
                progress_callback(transfer_id, 100, "File received successfully")
            
        except Exception as e:
            if transfer_id in active_transfers:
                active_transfers[transfer_id]["status"] = "failed"
                if progress_callback:
                    progress_callback(transfer_id, 0, f"Error: {str(e)}")
        
        finally:
            client_socket.close()
    
    def accept_connections():
        while True:
            client, addr = server.accept()
            client_handler = threading.Thread(
                target=handle_client,
                args=(client, addr)
            )
            client_handler.daemon = True
            client_handler.start()
    
    # Start accepting connections in a separate thread
    accept_thread = threading.Thread(target=accept_connections)
    accept_thread.daemon = True
    accept_thread.start()
    
    return server

class FluxApp:
    def __init__(self):
        self.selected_files = []
        self.receiver_server = None
        self.local_ip = get_local_ip()
        self.save_directory = os.path.join(os.path.expanduser("~"), "Downloads")
        
        # Ensure save directory exists
        os.makedirs(self.save_directory, exist_ok=True)
    
    def main(self, page: ft.Page):
        page.title = "FLUX"
        page.theme_mode = ft.ThemeMode.DARK
        page.window_width = 1000
        page.window_height = 800
        page.padding = 0
        page.spacing = 0
        page.window_center()
        page.bgcolor = "#1e1e1e"
        
        # Transfer progress tracking
        self.transfer_cards = {}
        
        def update_transfer_progress(transfer_id, progress, status_text):
            """Update the UI with transfer progress"""
            if transfer_id in self.transfer_cards:
                card = self.transfer_cards[transfer_id]
                card.content.controls[1].value = status_text
                card.content.controls[2].value = progress
                page.update()
            else:
                # Create a new card for this transfer
                file_name = active_transfers[transfer_id]["file_name"] if transfer_id in active_transfers else "Unknown file"
                
                progress_bar = ft.ProgressBar(value=progress/100, width=400)
                status_text = ft.Text(status_text, size=14)
                
                card = ft.Card(
                    content=ft.Container(
                        content=ft.Column([
                            ft.Text(file_name, size=16, weight=ft.FontWeight.BOLD),
                            status_text,
                            progress_bar
                        ]),
                        padding=15
                    ),
                    margin=10
                )
                
                self.transfer_cards[transfer_id] = card
                transfers_column.controls.append(card)
                page.update()
        
        # Start the receiver server
        self.receiver_server = start_receiver_server(
            self.save_directory, 
            progress_callback=update_transfer_progress
        )
        
        def pick_files_result(e: ft.FilePickerResultEvent):
            if e.files:
                self.selected_files = [file.path for file in e.files]
                selected_files_text.value = f"Selected {len(self.selected_files)} files"
                page.update()
        
        def send_files_click(e):
            if not self.selected_files:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("Please select files first"),
                    action="OK",
                )
                page.snack_bar.open = True
                page.update()
                return
            
            receiver_ip = receiver_ip_field.value.strip()
            if not receiver_ip:
                page.snack_bar = ft.SnackBar(
                    content=ft.Text("Please enter receiver's IP address"),
                    action="OK",
                )
                page.snack_bar.open = True
                page.update()
                return
            
            # Send each file in a separate thread
            for file_path in self.selected_files:
                def send_file_thread(file_path=file_path):
                    send_file(file_path, receiver_ip, progress_callback=update_transfer_progress)
                
                thread = threading.Thread(target=send_file_thread)
                thread.daemon = True
                thread.start()
            
            # Clear selection after sending
            self.selected_files = []
            selected_files_text.value = "No files selected"
            page.update()
        
        def change_save_dir_result(e: ft.FilePickerResultEvent):
            if e.path:
                self.save_directory = e.path
                save_dir_text.value = f"Save directory: {self.save_directory}"
                page.update()
        
        # File pickers
        pick_files_dialog = ft.FilePicker(on_result=pick_files_result)
        save_dir_dialog = ft.FilePicker(on_result=change_save_dir_result)
        page.overlay.extend([pick_files_dialog, save_dir_dialog])
        
        # UI Components
        selected_files_text = ft.Text("No files selected", size=14)
        save_dir_text = ft.Text(f"Save directory: {self.save_directory}", size=14)
        receiver_ip_field = ft.TextField(
            label="Receiver's IP Address",
            hint_text="Enter IP address",
            width=300
        )
        
        # Transfers display
        transfers_column = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            expand=True
        )
        
        # Main layout
        page.add(
            ft.Container(
                content=ft.Column([
                    # Header
                    ft.Container(
                        content=ft.Row([
                            ft.Text("FLUX", size=30, weight=ft.FontWeight.BOLD),
                            ft.Text("File Transfer Utility", size=16, italic=True)
                        ], alignment=ft.MainAxisAlignment.CENTER),
                        padding=20,
                        bgcolor="#2d2d2d"
                    ),
                    
                    # IP Display
                    ft.Container(
                        content=ft.Row([
                            ft.Text("Your IP Address: ", size=16),
                            ft.Text(self.local_ip, size=16, weight=ft.FontWeight.BOLD),
                            ft.IconButton(
                                icon=ft.icons.COPY,
                                tooltip="Copy IP",
                                on_click=lambda _: page.set_clipboard(self.local_ip)
                            )
                        ], alignment=ft.MainAxisAlignment.CENTER),
                        padding=10
                    ),
                    
                    # Send Files Section
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Send Files", size=20, weight=ft.FontWeight.BOLD),
                            ft.Row([
                                ft.ElevatedButton(
                                    "Select Files",
                                    icon=ft.icons.UPLOAD_FILE,
                                    on_click=lambda _: pick_files_dialog.pick_files(
                                        allow_multiple=True
                                    )
                                ),
                                selected_files_text
                            ]),
                            receiver_ip_field,
                            ft.ElevatedButton(
                                "Send Files",
                                icon=ft.icons.SEND,
                                on_click=send_files_click
                            )
                        ]),
                        padding=20,
                        margin=10,
                        bgcolor="#2d2d2d",
                        border_radius=10
                    ),
                    
                    # Receive Files Section
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Receive Files", size=20, weight=ft.FontWeight.BOLD),
                            ft.Row([
                                save_dir_text,
                                ft.IconButton(
                                    icon=ft.icons.FOLDER_OPEN,
                                    tooltip="Change save directory",
                                    on_click=lambda _: save_dir_dialog.get_directory_path()
                                )
                            ]),
                            ft.Text("Your computer is ready to receive files", size=14)
                        ]),
                        padding=20,
                        margin=10,
                        bgcolor="#2d2d2d",
                        border_radius=10
                    ),
                    
                    # Transfers Section
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Transfers", size=20, weight=ft.FontWeight.BOLD),
                            transfers_column
                        ]),
                        padding=20,
                        margin=10,
                        bgcolor="#2d2d2d",
                        border_radius=10,
                        expand=True
                    )
                ]),
                expand=True
            )
        )

if __name__ == "__main__":
    app = FluxApp()
    ft.app(target=app.main)