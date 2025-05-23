import zstandard as zstd
import os
from typing import Optional

# Constants
BUFFER_SIZE = 4096
COMPRESSION_LEVEL = 3  # Moderate compression level

def compress_file(file_path: str, output_path: Optional[str] = None) -> str:
    """Compress a file using zstandard if it's larger than 10MB
    
    Args:
        file_path: Path to the file to compress
        output_path: Optional path for the compressed file
        
    Returns:
        Path to the compressed file if size > 10MB, otherwise original file path
    """
    # Check if file size is greater than 10MB (10 * 1024 * 1024 bytes)
    if os.path.getsize(file_path) <= 10 * 1024 * 1024:
        return file_path
        
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

def decompress_file(compressed_path: str, output_path: str) -> str:
    """Decompress a file using zstandard
    
    Args:
        compressed_path: Path to the compressed file
        output_path: Path where the decompressed file should be saved
        
    Returns:
        Path to the decompressed file
    """
    dctx = zstd.ZstdDecompressor()
    with open(compressed_path, 'rb') as f_in:
        with open(output_path, 'wb') as f_out:
            decompressor = dctx.stream_reader(f_in)
            while True:
                chunk = decompressor.read(BUFFER_SIZE)
                if not chunk:
                    break
                f_out.write(chunk)
    return output_path