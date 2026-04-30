import os
import sys
import time
import json
import signal
import threading
import subprocess
import socket
import argparse
from multiprocessing.managers import BaseManager
from datetime import datetime

import financial_evaluation.lm_eval.models


class ModelServiceManager:
    def __init__(self, port=50000, auth_key=b'abc', service_file=None):
        self.port = port
        self.auth_key = auth_key
        self.service_file = service_file or f'model_server_{port}.json'

        class _ModelManager(BaseManager):
            pass

        self.ManagerClass = _ModelManager

    def check_service(self, silent=False):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                result = s.connect_ex(('127.0.0.1', self.port))
                if result == 0:
                    if not silent:
                        print(f"Service running on port {self.port}")
                    return True
                else:
                    if not silent:
                        print(f"Port {self.port} not in use")
                    return False
        except Exception as e:
            if not silent:
                print(f"Error checking service: {e}")
            return False

    def terminate_process(self, pid):
        try:
            if sys.platform == 'win32':
                result = subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                time.sleep(2)
                return result.returncode == 0
            else:
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
                try:
                    os.kill(pid, 0)
                    os.kill(pid, signal.SIGKILL)
                    time.sleep(1)
                except OSError:
                    pass
                return True
        except Exception as e:
            print(f"Failed to terminate process: {e}")
            return False

    def stop_service(self):
        if not self.check_service(silent=True):
            print("No running model service found")
            return False

        pid = None
        terminated = False

        try:
            if os.path.exists(self.service_file):
                with open(self.service_file, 'r') as f:
                    server_info = json.load(f)
                    pid = server_info.get("pid")

                if pid:
                    print(f"Found service process ID: {pid}")
                    if self.terminate_process(pid):
                        print("Model service process terminated")
                        terminated = True
        except Exception as e:
            print(f"Failed to terminate via PID: {e}")

        if terminated:
            for attempt in range(5):
                try:
                    if os.path.exists(self.service_file):
                        os.remove(self.service_file)
                    break
                except Exception as e:
                    if attempt < 4:
                        print(f"Could not remove server file (attempt {attempt + 1}): {e}")
                        time.sleep(1)

            if not self.check_service(silent=True):
                return True

        if not terminated:
            print("Attempting to shutdown via manager interface...")
            try:
                self.ManagerClass.register('shutdown')
                manager = self.ManagerClass(address=('127.0.0.1', self.port), authkey=self.auth_key)
                manager.connect()
                print("Sending shutdown command...")
                manager.shutdown()

                for i in range(5):
                    time.sleep(1)
                    if not self.check_service(silent=True):
                        print("Model service successfully shut down")
                        try:
                            if os.path.exists(self.service_file):
                                os.remove(self.service_file)
                        except Exception:
                            pass
                        return True

                print("Model service did not shutdown via manager interface")
            except Exception as e:
                print(f"Error shutting down service: {e}")

        if not self.check_service(silent=True):
            print("Service is no longer running")
            return True
        else:
            print("Warning: Service may still be running")
            return False

    def start_service(self, timeout=3600):
        if self.check_service(silent=True):
            print(f"Model service already running on port {self.port}")
            return True

        this_script = os.path.abspath(sys.argv[0])
        args = [sys.executable, this_script, 'service', '--port', str(self.port)]

        print(f"Starting model service process on port {self.port}...")
        proc = subprocess.Popen(args)

        print(f"Service started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("Waiting for service to be ready...")

        start_time = time.time()
        dots = 0

        while time.time() - start_time < timeout:
            dots = (dots % 3) + 1
            sys.stdout.write(f"\rWaiting for service to start{'.' * dots}{' ' * (3 - dots)}")
            sys.stdout.flush()

            if self.check_service(silent=True):
                if os.path.exists(self.service_file):
                    try:
                        with open(self.service_file, 'r') as f:
                            server_info = json.load(f)
                            if server_info.get("ready", False):
                                print("\nModel service started and ready!")
                                print(f"Service PID: {server_info.get('pid')}")
                                return True
                    except:
                        pass

            time.sleep(1)

        print(f"\nStartup timeout ({timeout}s), service may still be loading")
        return False

    def status_service(self):
        self.check_service()
        if self.check_service(silent=True) and os.path.exists(self.service_file):
            try:
                with open(self.service_file, 'r') as f:
                    server_info = json.load(f)
                    print(f"Service PID: {server_info.get('pid')}")
                    print(f"Status: {'Ready' if server_info.get('ready', False) else 'Loading'}")

                    started_at = server_info.get("started_at")
                    if started_at:
                        started_time = datetime.strptime(started_at, "%Y-%m-%d %H:%M:%S")
                        now = datetime.now()
                        uptime = now - started_time
                        hours, remainder = divmod(uptime.total_seconds(), 3600)
                        minutes, seconds = divmod(remainder, 60)
                        print(f"Uptime: {int(hours)}h {int(minutes)}m {int(seconds)}s")
                return True
            except Exception as e:
                print(f"Error getting service info: {e}")
        return False

    def run_service(self):
        print(f"Starting model service on port {self.port}...")

        server_info = {
            "pid": os.getpid(),
            "ready": False,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(self.service_file, 'w') as f:
            json.dump(server_info, f)

        state = self._create_server_state()

        try:
            print("Setting up service...")
            model, manager_dict = self._setup_service(state)

            self.ManagerClass.register('get_model', callable=lambda: model)
            self.ManagerClass.register('get_state', callable=lambda: state)
            self.ManagerClass.register('shutdown', callable=lambda: state.shutdown_server())
            self.ManagerClass.register('mark_ready', callable=lambda: state.mark_ready())

            manager = self.ManagerClass(address=('127.0.0.1', self.port), authkey=self.auth_key)
            server = manager.get_server()

            def signal_handler(signum, frame):
                print(f"Received signal {signum}, shutting down...")
                if os.path.exists(self.service_file):
                    os.remove(self.service_file)
                sys.exit(0)

            signal.signal(signal.SIGTERM, signal_handler)
            if sys.platform != 'win32':
                signal.signal(signal.SIGINT, signal_handler)

            state.mark_ready()
            print("Service ready to accept connections")
            print(f'Model server running at 127.0.0.1:{self.port}')
            server.serve_forever()

        except Exception as e:
            print(f"Service startup failed: {str(e)}")
            if os.path.exists(self.service_file):
                os.remove(self.service_file)
            return False

    def _create_server_state(self):
        class ServerState:
            def __init__(self_state):
                self_state.running = True
                self_state.last_activity = time.time()
                self_state.clients = 0
                self_state.is_ready = False

            def shutdown_server(self_state):
                self_state.running = False
                threading.Thread(target=lambda: (time.sleep(1), os._exit(0)), daemon=True).start()
                return True

            def mark_ready(self_state):
                self_state.is_ready = True
                server_info = {
                    "pid": os.getpid(),
                    "ready": True,
                    "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(self.service_file, 'w') as f:
                    json.dump(server_info, f)
                return True

        return ServerState()

    def _setup_service(self, state):
        pass

    @classmethod
    def main(cls):
        parser = argparse.ArgumentParser(description='Model Service Management Tool')
        parser.add_argument('action', choices=['start', 'stop', 'status', 'service'],
                            help='Action: start, stop, status, service (internal)')
        parser.add_argument('--port', type=int, default=50000, help='Port number for the service')

        args = parser.parse_args()
        service = cls(port=args.port)

        if args.action == 'start':
            print("Starting model service...")
            service.start_service()
        elif args.action == 'stop':
            print("Stopping model service...")
            service.stop_service()
        elif args.action == 'status':
            service.status_service()
        elif args.action == 'service':
            service.run_service()

def get_model_service(max_retries=3, retry_interval=2):
    """
    Connect to model server and return the model object.

    Args:
        max_retries: Number of connection attempts
        retry_interval: Seconds between retries

    Returns:
        Model object with chat method
    """
    # Define manager class
    class ModelManager(BaseManager):
        pass

    # Register model and state
    ModelManager.register('get_model')
    ModelManager.register('get_state')

    # Initialize connection manager
    manager = ModelManager(address=('127.0.0.1', 50000), authkey=b'abc')

    # Try to connect with retries
    for attempt in range(max_retries):
        try:
            manager.connect()
            return manager.get_model()
        except ConnectionRefusedError:
            if attempt < max_retries - 1:
                print(f"Connection attempt {attempt+1} failed, retrying in {retry_interval} seconds...")
                time.sleep(retry_interval)
            else:
                print("Failed to connect to model server. Make sure it's running with 'python model_server.py start'")
                sys.exit(1)
        except Exception as e:
            print(f"Error connecting to model server: {e}")
            sys.exit(1)

# Example usage:
# class MyService(ModelServiceManager):
#     def _setup_service(self, state):        
#         lm = lm_eval.models.get_model("hf-causal-vllm").create_from_arg_string("use_accelerate=True,pretrained=/gemini/pretrain3/DeepSeek-R1-Distill-Qwen-7B,tokenizer=/gemini/pretrain3/DeepSeek-R1-Distill-Qwen-7B,use_fast=False,max_gen_toks=150,dtype=float16,trust_remote_code=True", {"batch_size": 2, "max_batch_size": None})
#         return lm, {}


class MyService(ModelServiceManager):
    def _setup_service(self, state):
        model_name = "/gemini/pretrain3/Atom-7B"
        lm = lm_eval.models.get_model("hf-causal-vllm").create_from_arg_string(f"use_accelerate=True,pretrained={model_name},tokenizer={model_name},use_fast=False,max_gen_toks=150,dtype=float16,trust_remote_code=True",
            {"batch_size": 2, "max_batch_size": None, "device": None})

        # Create a wrapper that only exposes the methods you need
        class ModelWrapper:
            def __init__(self, model):
                self._model = model

            def greedy_until(self, requests):
                return self._model.greedy_until(requests)

        return ModelWrapper(lm), {}


if __name__ == "__main__":
    print(f"Model Service Tool v1.0.0")
    print(f"User: {os.environ.get('USER', os.environ.get('USERNAME', 'Unknown'))}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"OS: {sys.platform}")
    print("-" * 50)

    MyService.main()