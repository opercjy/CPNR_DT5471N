import serial
import time
import queue
import threading
from enum import IntFlag
from typing import Callable, Optional, Dict

class CAEN_Status(IntFlag):
    ON     = 1 << 0
    RUP    = 1 << 1
    RDW    = 1 << 2
    OVC    = 1 << 3
    OVV    = 1 << 4
    UNV    = 1 << 5
    MAXV   = 1 << 6
    TRIP   = 1 << 7
    OVT    = 1 << 8
    DIS    = 1 << 10
    KILL   = 1 << 11
    ILK    = 1 << 12
    NOCAL  = 1 << 13

class DT5471N:
    def __init__(self, port: str = "/dev/dt5471n", baudrate: int = 9600):
        self.port = port
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        
        self._is_running = False
        self._cmd_queue = queue.Queue()
        self._worker_thread = None
        
        self.on_telemetry: Optional[Callable[[Dict], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def _query(self, cmd: str, par: str, val: float = None) -> str:
        if not self.ser or not self.ser.is_open:
            raise serial.SerialException("Serial port is not open.")
            
        cmd_str = f"$CMD:{cmd},PAR:{par},VAL:{val:.2f}\r\n" if val is not None else f"$CMD:{cmd},PAR:{par}\r\n"
        self.ser.reset_input_buffer() 
        self.ser.write(cmd_str.encode('ascii'))
        self.ser.flush() 
        
        raw_res = self.ser.readline()
        if not raw_res:
            raise TimeoutError("Hardware I/O Timeout.")
            
        res = raw_res.decode('ascii').strip()
        if res.startswith("#CMD:ERR"):
            raise ValueError(f"Command rejected by hardware: {res}")
        return res.split("VAL:")[1].strip() if "VAL:" in res else "OK"

    def _hw_loop(self):
        while self._is_running:
            try:
                if self.ser is None or not self.ser.is_open:
                    self.ser = serial.Serial(self.port, self.baudrate, rtscts=True, timeout=1.0)
                    time.sleep(0.1)

                # [수정됨] sleep(1.0) 대신 timeout 기반의 블로킹 큐 사용 (즉각 반응성 확보)
                try:
                    action, param, val = self._cmd_queue.get(timeout=1.0)
                    self._query(action, param, val)
                    self._cmd_queue.task_done()
                    continue # 명령을 처리한 직후에는 상태 폴링을 한 번 건너뛰어 속도 향상
                except queue.Empty:
                    pass # 1초간 큐가 비어있었으므로 아래의 상태 폴링 진행

                vmon = float(self._query("MON", "VMON"))
                imon = float(self._query("MON", "IMON"))
                stat_val = int(self._query("MON", "STAT"))
                
                status = {flag.name: bool(stat_val & flag.value) for flag in CAEN_Status}

                if self.on_telemetry:
                    self.on_telemetry({
                        "timestamp": time.time(),
                        "VMON": vmon,
                        "IMON": imon,
                        "STATUS": status
                    })
                    
            except (serial.SerialException, serial.SerialTimeoutException, OSError) as e:
                if self.ser: self.ser.close()
                if self.on_error: self.on_error(f"Connection Lost: {e}")
                time.sleep(2.0)
            except Exception as e:
                if self.on_error: self.on_error(f"Logic Error: {e}")

    def start(self):
        if self._is_running: return
        self._is_running = True
        self._worker_thread = threading.Thread(target=self._hw_loop, daemon=True)
        self._worker_thread.start()

    def stop(self):
        self._is_running = False
        if self._worker_thread: self._worker_thread.join(timeout=2.0)
        if self.ser: self.ser.close()

    def power_on(self): self._cmd_queue.put(("SET", "ON", None))
    def power_off(self): self._cmd_queue.put(("SET", "OFF", None))
    
    # [수정됨] 매개변수명을 ramp_rate로 변경하여 인터페이스 통일
    def set_voltage(self, v: float, ramp_rate: float = 30.0):
        self._cmd_queue.put(("SET", "RUP", float(ramp_rate)))
        self._cmd_queue.put(("SET", "RDW", float(ramp_rate)))
        self._cmd_queue.put(("SET", "VSET", float(v)))
        
    def set_current_limit(self, i: float): self._cmd_queue.put(("SET", "ISET", float(i)))
    def clear_alarm(self): self._cmd_queue.put(("SET", "BDCLR", None))
