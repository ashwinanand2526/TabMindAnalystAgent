import sys
import json
import struct
import socket
import subprocess
import os

# Port where extension bridge runs
PORT = 7861

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect(('127.0.0.1', port))
            return True
        except socket.error:
            return False

def read_message():
    text_length_bytes = sys.stdin.buffer.read(4)
    if not text_length_bytes:
        return None
    text_length = struct.unpack('i', text_length_bytes)[0]
    text = sys.stdin.buffer.read(text_length).decode('utf-8')
    return json.loads(text)

def send_message(message):
    encoded_message = json.dumps(message).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('i', len(encoded_message)))
    sys.stdout.buffer.write(encoded_message)
    sys.stdout.buffer.flush()

def main():
    try:
        msg = read_message()
        if not msg:
            return

        # Check if bridge is already running
        running = is_port_open(PORT)
        
        if not running:
            # Determine path to extension_bridge.py
            # The structure is:
            # TabResearcher-GraphBased/
            # ├── extension/
            # │   └── bridge_launcher.py
            # └── code/
            #     └── extension_bridge.py
            current_dir = os.path.dirname(os.path.abspath(__file__))
            bridge_path = os.path.join(current_dir, '..', 'code', 'extension_bridge.py')
            code_dir = os.path.join(current_dir, '..', 'code')
            
            # Start extension_bridge.py as a detached process (cross-platform, focuses on Windows here)
            env = os.environ.copy()
            env["PYTHONUTF8"] = "1"
            
            if os.name == 'nt':
                # Windows detached process creation flags
                DETACHED_PROCESS = 0x00000008
                subprocess.Popen(
                    ['uv', 'run', 'python', 'extension_bridge.py'],
                    cwd=code_dir,
                    env=env,
                    creationflags=DETACHED_PROCESS,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                # Unix detached process
                subprocess.Popen(
                    ['uv', 'run', 'python', 'extension_bridge.py'],
                    cwd=code_dir,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
            
            send_message({"status": "starting", "message": "FastAPI Bridge started in detached process"})
        else:
            send_message({"status": "running", "message": "FastAPI Bridge is already running"})

    except Exception as e:
        send_message({"status": "error", "message": str(e)})

if __name__ == '__main__':
    main()
