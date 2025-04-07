import socket
import threading
import json
import time
import uuid
import os
import base64
from typing import Dict, Callable, Optional

from .crypto import encrypt_data, decrypt_data, derive_key
from .compression import compress_file, decompress_file

# Constants
BUFFER_SIZE = 4096
SERVER_PORT = 5555
CODE_LENGTH = 6

# Global state
active_transfers: Dict[str, dict] = {}
transfer_codes: Dict[str, dict] = {}

def generate_transfer_code() -> str:
    """Generate a random 6-digit transfer code"""
    import secrets
    return ''.join(secrets.choice('0123456789') for _ in range(CODE_LENGTH))

def register_transfer(transfer_id: str, code: str) -> str:
    """Register a new file transfer with its code"""
    transfer_codes[code] = {
        'transfer_id': transfer_id,
        'timestamp': time.time(),
        'status': 'waiting'
    }
    return code

def get_transfer_by_code(code: str) -> Optional[dict]:
    """Get transfer information by code"""
    return transfer_codes.get(code)

def get_local_ip() -> str:
    """Get the local IP address of the machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def send_file(file_path: str, password: str, progress_callback: Optional[Callable] = None) -> bool:
    """Send a file using a transfer code"""
    transfer_id = str(uuid.uuid4())
    transfer_code = generate_transfer_code()
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    # Compress the file
    compressed_path = compress_file(file_path)
    compressed_size = os.path.getsize(compressed_path)
    
    # Generate salt and derive key
    salt = os.urandom(16)
    key = derive_key(password, salt)
    
    # Prepare metadata
    metadata = {
        "transfer_id": transfer_id,
        "file_name": file_name,
        "original_size": file_size,
        "compressed_size": compressed_size,
        "salt": base64.b64encode(salt).decode(),
        "transfer_code": transfer_code
    }
    
    # Track this transfer
    active_transfers[transfer_id] = {
        "file_name": file_name,
        "status": "waiting",
        "progress": 0,
        "start_time": time.time(),
        "transfer_code": transfer_code
    }
    
    register_transfer(transfer_id, transfer_code)
    
    if progress_callback:
        progress_callback(transfer_id, 0, f"Waiting for receiver... Transfer Code: {transfer_code}")
    
    try:
        # Wait for receiver to connect
        while transfer_codes[transfer_code]['status'] == 'waiting':
            time.sleep(0.5)
            
        if transfer_codes[transfer_code]['status'] != 'connected':
            raise Exception("Transfer cancelled or expired")
            
        receiver_info = transfer_codes[transfer_code]
        s = receiver_info.get('socket')
        
        if not s:
            raise Exception("Connection lost")
        
        # Send metadata
        s.sendall(json.dumps(metadata).encode() + b"\n")
        
        active_transfers[transfer_id]["status"] = "sending"
        if progress_callback:
            progress_callback(transfer_id, 0, "Starting transfer...")
        
        # Send encrypted file
        bytes_sent = 0
        with open(compressed_path, 'rb') as f:
            while True:
                chunk = f.read(BUFFER_SIZE)
                if not chunk:
                    break
                encrypted_chunk = encrypt_data(chunk, key)
                s.sendall(encrypted_chunk)
                bytes_sent += len(chunk)
                progress = int((bytes_sent / compressed_size) * 100)
                
                active_transfers[transfer_id]["progress"] = progress
                if progress_callback:
                    progress_callback(transfer_id, progress, f"Sending: {progress}%")
        
        s.close()
        os.remove(compressed_path)
        
        active_transfers[transfer_id]["status"] = "completed"
        active_transfers[transfer_id]["progress"] = 100
        if progress_callback:
            progress_callback(transfer_id, 100, "Transfer completed")
        
        del transfer_codes[transfer_code]
        return True
        
    except Exception as e:
        active_transfers[transfer_id]["status"] = "failed"
        if progress_callback:
            progress_callback(transfer_id, 0, f"Error: {str(e)}")
        
        if os.path.exists(compressed_path):
            os.remove(compressed_path)
        if transfer_code in transfer_codes:
            del transfer_codes[transfer_code]
        
        return False

def start_receiver_server(save_dir: str, password: str, transfer_code: str, 
                         progress_callback: Optional[Callable] = None) -> socket.socket:
    """Start receiving files using a transfer code"""
    try:
        transfer_info = get_transfer_by_code(transfer_code)
        if not transfer_info:
            raise Exception("Invalid transfer code")
            
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', SERVER_PORT))
        s.listen(1)
        
        transfer_info['status'] = 'connected'
        transfer_info['socket'] = s
        
        def handle_client(client_socket: socket.socket, client_address: tuple):
            transfer_id = None
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
                
                salt = base64.b64decode(metadata["salt"])
                key = derive_key(password, salt)
                
                temp_compressed_path = os.path.join(save_dir, f"{file_name}.zst.temp")
                final_output_path = os.path.join(save_dir, file_name)
                
                active_transfers[transfer_id] = {
                    "file_name": file_name,
                    "status": "receiving",
                    "progress": 0,
                    "start_time": time.time()
                }
                
                if progress_callback:
                    progress_callback(transfer_id, 0, "Starting to receive file...")
                
                if remaining_data:
                    decrypted_data = decrypt_data(remaining_data, key)
                    bytes_received = len(decrypted_data)
                    with open(temp_compressed_path, 'wb') as f:
                        f.write(decrypted_data)
                else:
                    bytes_received = 0
                    with open(temp_compressed_path, 'wb') as f:
                        pass
                
                with open(temp_compressed_path, 'ab') as f:
                    while bytes_received < compressed_size:
                        chunk = client_socket.recv(BUFFER_SIZE)
                        if not chunk:
                            break
                        
                        decrypted_chunk = decrypt_data(chunk, key)
                        f.write(decrypted_chunk)
                        bytes_received += len(decrypted_chunk)
                        
                        progress = int((bytes_received / compressed_size) * 100)
                        active_transfers[transfer_id]["progress"] = progress
                        if progress_callback:
                            progress_callback(transfer_id, progress, f"Receiving: {progress}%")
                
                if progress_callback:
                    progress_callback(transfer_id, 100, "Decompressing file...")
                
                decompress_file(temp_compressed_path, final_output_path)
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
                client, addr = s.accept()
                client_handler = threading.Thread(
                    target=handle_client,
                    args=(client, addr)
                )
                client_handler.daemon = True
                client_handler.start()
        
        accept_thread = threading.Thread(target=accept_connections)
        accept_thread.daemon = True
        accept_thread.start()
        
        return s
        
    except Exception as e:
        print(f"Connection failed: {str(e)}")
        return None