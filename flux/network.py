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
    if not code or not isinstance(code, str) or len(code) != CODE_LENGTH or not code.isdigit():
        return None
    
    transfer_info = transfer_codes.get(code)
    if not transfer_info:
        return None
        
    # Check if transfer code has expired (10 minutes)
    if time.time() - transfer_info['timestamp'] > 600:
        del transfer_codes[code]
        return None
        
    return transfer_info

def get_local_ip() -> str:
    """Get the local IP address of the machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# Add a function to get active transfer status for GUI display
def get_transfer_status(transfer_id: str = None) -> dict:
    """Get status of all transfers or a specific transfer"""
    if transfer_id:
        return active_transfers.get(transfer_id, {})
    return active_transfers

def cancel_transfer(transfer_id: str) -> bool:
    """Cancel an active transfer"""
    if transfer_id in active_transfers:
        transfer_info = active_transfers[transfer_id]
        transfer_info['status'] = 'cancelled'
        
        # Find and remove the transfer code
        for code, info in list(transfer_codes.items()):
            if info.get('transfer_id') == transfer_id:
                if 'socket' in info and info['socket']:
                    try:
                        info['socket'].close()
                    except:
                        pass
                del transfer_codes[code]
                break
        
        return True
    return False

def send_file(file_path: str, password: str, progress_callback: Optional[Callable] = None) -> str:
    """Send a file using a transfer code, returns transfer_id for tracking in GUI"""
    transfer_id = str(uuid.uuid4())
    transfer_code = generate_transfer_code()
    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File {file_path} not found")
    
    # Compress the file
    compressed_path = compress_file(file_path)
    compressed_size = os.path.getsize(compressed_path)
    
    # Generate salt and derive key
    salt = os.urandom(16)
    key = derive_key(password, salt)
    
    # Prepare metadata
    is_compressed = compressed_path != file_path  # Check if file was actually compressed
    metadata = {
        "transfer_id": transfer_id,
        "file_name": file_name,
        "original_size": file_size,
        "compressed_size": compressed_size,
        "salt": base64.b64encode(salt).decode(),
        "transfer_code": transfer_code,
        "is_compressed": is_compressed
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
    
    # Start the transfer process in a separate thread to avoid blocking GUI
    def transfer_thread():
        try:
            # Wait for receiver to connect with timeout
            wait_start = time.time()
            while transfer_codes.get(transfer_code, {}).get('status') == 'waiting':
                if time.time() - wait_start > 300:  # 5 minutes timeout
                    raise Exception("Receiver connection timeout")
                if transfer_id in active_transfers and active_transfers[transfer_id]['status'] == 'cancelled':
                    raise Exception("Transfer cancelled by user")
                time.sleep(0.5)
                
            if transfer_code not in transfer_codes or transfer_codes[transfer_code]['status'] != 'connected':
                raise Exception("Transfer cancelled or expired")
                
            receiver_info = transfer_codes[transfer_code]
            
            # Create sender socket and connect to receiver with retry
            max_retries = 3
            retry_delay = 2
            for attempt in range(max_retries):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(30)  # Set connection timeout
                    s.connect((get_local_ip(), SERVER_PORT))
                    s.settimeout(None)  # Reset timeout for data transfer
                    break
                except (socket.timeout, ConnectionRefusedError) as e:
                    s.close()
                    if attempt == max_retries - 1:
                        raise Exception(f"Failed to connect after {max_retries} attempts: {str(e)}")
                    if progress_callback:
                        progress_callback(transfer_id, 0, f"Connection attempt {attempt + 1} failed, retrying...")
                    time.sleep(retry_delay)
            
            # Send metadata
            s.sendall(json.dumps(metadata).encode() + b"\n")
            
            active_transfers[transfer_id]["status"] = "sending"
            if progress_callback:
                progress_callback(transfer_id, 0, "Starting transfer...")
            
            # Send encrypted file
            bytes_sent = 0
            with open(compressed_path, 'rb') as f:
                while True:
                    if transfer_id in active_transfers and active_transfers[transfer_id]['status'] == 'cancelled':
                        raise Exception("Transfer cancelled by user")
                        
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
            
            if transfer_code in transfer_codes:
                del transfer_codes[transfer_code]
            
        except Exception as e:
            active_transfers[transfer_id]["status"] = "failed"
            active_transfers[transfer_id]["error_message"] = str(e)
            if progress_callback:
                progress_callback(transfer_id, 0, f"Error: {str(e)}")
            
            if os.path.exists(compressed_path):
                os.remove(compressed_path)
            if transfer_code in transfer_codes:
                del transfer_codes[transfer_code]
    
    # Start the transfer thread
    transfer_thread = threading.Thread(target=transfer_thread)
    transfer_thread.daemon = True
    transfer_thread.start()
    
    # Return the transfer ID for tracking in the GUI
    return transfer_id

class ReceiverServer:
    def __init__(self, save_dir: str, password: str, transfer_code: str, progress_callback: Optional[Callable] = None):
        self.save_dir = save_dir
        self.password = password
        self.transfer_code = transfer_code
        self.progress_callback = progress_callback
        self.transfer_id = None
        
    def close(self):
        if self.transfer_id:
            cancel_transfer(self.transfer_id)

def start_receiver_server(save_dir: str, password: str, transfer_code: str, progress_callback: Optional[Callable] = None) -> ReceiverServer:
    """Start a receiver server that listens for incoming file transfers"""
    server = ReceiverServer(save_dir, password, transfer_code, progress_callback)
    server.transfer_id = receive_file(save_dir, password, transfer_code, progress_callback)
    return server

def receive_file(save_dir: str, password: str, transfer_code: str, 
                progress_callback: Optional[Callable] = None) -> str:
    """Start receiving a file using a transfer code, returns transfer_id for tracking in GUI"""
    try:
        if not os.path.exists(save_dir):
            os.makedirs(save_dir, exist_ok=True)
            
        transfer_info = get_transfer_by_code(transfer_code)
        if not transfer_info:
            raise Exception("Invalid transfer code")
        
        transfer_id = transfer_info['transfer_id']
        
        # Create a new transfer ID for the receiver side if needed
        if transfer_id not in active_transfers:
            active_transfers[transfer_id] = {
                "status": "connecting",
                "progress": 0,
                "start_time": time.time(),
                "transfer_code": transfer_code
            }
        
        # Start the receiver in a separate thread to avoid blocking GUI
        def receiver_thread():
            server_socket = None
            try:
                # Create and configure receiver socket with retry mechanism
                max_bind_retries = 3
                bind_retry_delay = 2
                
                for bind_attempt in range(max_bind_retries):
                    try:
                        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                        server_socket.settimeout(60)  # Set socket timeout
                        local_ip = '0.0.0.0'  # Listen on all network interfaces
                        server_socket.bind((local_ip, SERVER_PORT))
                        server_socket.listen(1)
                        break
                    except socket.error as e:
                        if server_socket:
                            server_socket.close()
                        if bind_attempt < max_bind_retries - 1:
                            if progress_callback:
                                progress_callback(transfer_id, 0, f"Bind attempt {bind_attempt + 1} failed, retrying...")
                            time.sleep(bind_retry_delay)
                            continue
                        raise Exception(f"Failed to bind socket after {max_bind_retries} attempts: {str(e)}")
                
                transfer_info['status'] = 'connected'
                transfer_info['socket'] = server_socket
                
                if progress_callback:
                    progress_callback(transfer_id, 0, "Waiting for sender to connect...")
                
                # Accept connection from sender
                client_socket, client_address = server_socket.accept()
                
                try:
                    client_socket.settimeout(30)  # Set timeout for receiving metadata
                    # Receive metadata
                    metadata_bytes = b""
                    while b"\n" not in metadata_bytes:
                        try:
                            chunk = client_socket.recv(BUFFER_SIZE)
                            if not chunk:
                                raise Exception("Connection closed by sender")
                            metadata_bytes += chunk
                        except socket.timeout:
                            raise Exception("Timeout while receiving metadata")
                    
                    metadata_str, remaining_data = metadata_bytes.split(b"\n", 1)
                    metadata = json.loads(metadata_str.decode())
                    
                    file_name = metadata["file_name"]
                    compressed_size = metadata["compressed_size"]
                    
                    salt = base64.b64decode(metadata["salt"])
                    key = derive_key(password, salt)
                    
                    temp_compressed_path = os.path.join(save_dir, f"{file_name}.zst.temp")
                    final_output_path = os.path.join(save_dir, file_name)
                    
                    active_transfers[transfer_id]["file_name"] = file_name
                    active_transfers[transfer_id]["status"] = "receiving"
                    
                    if progress_callback:
                        progress_callback(transfer_id, 0, "Starting to receive file...")
                    
                    # Handle any data that came with the metadata
                    if remaining_data:
                        decrypted_data = decrypt_data(remaining_data, key)
                        bytes_received = len(decrypted_data)
                        with open(temp_compressed_path, 'wb') as f:
                            f.write(decrypted_data)
                    else:
                        bytes_received = 0
                        with open(temp_compressed_path, 'wb') as f:
                            pass
                    
                    # Receive the file data
                    client_socket.settimeout(60)  # Set longer timeout for file transfer
                    with open(temp_compressed_path, 'ab') as f:
                        while bytes_received < compressed_size:
                            if transfer_id in active_transfers and active_transfers[transfer_id]['status'] == 'cancelled':
                                raise Exception("Transfer cancelled by user")
                                
                            try:
                                chunk = client_socket.recv(BUFFER_SIZE)
                                if not chunk:
                                    raise Exception("Connection closed unexpectedly")
                                
                                decrypted_chunk = decrypt_data(chunk, key)
                                f.write(decrypted_chunk)
                                bytes_received += len(decrypted_chunk)
                                
                                progress = int((bytes_received / compressed_size) * 100)
                                active_transfers[transfer_id]["progress"] = progress
                                if progress_callback:
                                    progress_callback(transfer_id, progress, f"Receiving: {progress}%")
                            except socket.timeout:
                                raise Exception("Timeout while receiving file data")
                    
                    if progress_callback:
                        progress_callback(transfer_id, 100, "Decompressing file...")
                    
                    try:
                        # Check if file was compressed
                        if metadata.get("is_compressed", True):  # Default to True for backward compatibility
                            # Ensure the temporary file exists before attempting decompression
                            if not os.path.exists(temp_compressed_path):
                                raise Exception("Temporary compressed file not found")
                                
                            # Create a temporary output file for decompression
                            temp_output_path = final_output_path + ".tmp"
                            
                            # Decompress to temporary output first
                            decompress_file(temp_compressed_path, temp_output_path)
                            
                            # If decompression succeeded, move the file to final location
                            os.replace(temp_output_path, final_output_path)
                            
                            # Clean up the compressed temporary file
                            if os.path.exists(temp_compressed_path):
                                os.remove(temp_compressed_path)
                        else:
                            # For uncompressed files, just move the temp file to final location
                            os.replace(temp_compressed_path, final_output_path)
                        
                        active_transfers[transfer_id]["status"] = "completed"
                    except Exception as decompress_error:
                        if os.path.exists(temp_compressed_path):
                            os.remove(temp_compressed_path)
                        raise Exception(f"Failed to decompress file: {str(decompress_error)}")

                    active_transfers[transfer_id]["file_path"] = final_output_path
                    if progress_callback:
                        progress_callback(transfer_id, 100, "File received successfully")
                
                except Exception as e:
                    active_transfers[transfer_id]["status"] = "failed"
                    active_transfers[transfer_id]["error_message"] = str(e)
                    if progress_callback:
                        progress_callback(transfer_id, 0, f"Error: {str(e)}")
                
                finally:
                    try:
                        client_socket.close()
                    except:
                        pass
            
            except Exception as e:
                active_transfers[transfer_id]["status"] = "failed"
                active_transfers[transfer_id]["error_message"] = str(e)
                if progress_callback:
                    progress_callback(transfer_id, 0, f"Error: {str(e)}")
            
            finally:
                if server_socket:
                    try:
                        server_socket.close()
                    except:
                        pass
                if transfer_code in transfer_codes:
                    del transfer_codes[transfer_code]
        
        # Start the receiver thread
        receive_thread = threading.Thread(target=receiver_thread)
        receive_thread.daemon = True
        receive_thread.start()
        
        # Return the transfer ID for tracking in the GUI
        return transfer_id
        
    except Exception as e:
        raise Exception(f"Failed to start receiver: {str(e)}")