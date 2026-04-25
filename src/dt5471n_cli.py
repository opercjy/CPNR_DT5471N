import time
import csv
import os
import sys
import threading
from dt5471n_core import DT5471N

CSV_FILENAME = "dt5471n_datalog.csv"
term_lock = threading.Lock()
latest_vmon = 0.0

def print_error(msg: str):
    with term_lock:
        sys.stdout.write(f"\n\033[91m[HW ERROR] {msg}\033[0m\nPMT> ")
        sys.stdout.flush()

def handle_telemetry(data: dict):
    global latest_vmon
    latest_vmon = data['VMON']
    stat = data['STATUS']
    
    if stat["TRIP"]:
        state_str = "!!! ALARM: TRIPPED !!!"
        bg_color = "\033[41;97m" 
    elif stat["OVC"]:
        state_str = "!!! ALARM: OVERCURRENT !!!"
        bg_color = "\033[41;97m"
    elif stat["ILK"]:
        state_str = "!!! INTERLOCK ACTIVE !!!"
        bg_color = "\033[43;30m"
    else:
        state_str = "ON" if stat["ON"] else "OFF"
        if stat["RUP"]: state_str += " (Ramping UP)"
        if stat["RDW"]: state_str += " (Ramping DOWN)"
        bg_color = "\033[44;97m" if stat["ON"] else "\033[40;97m"

    status_line = f" [{time.strftime('%H:%M:%S')}] VMON: {latest_vmon:6.1f} V | IMON: {data['IMON']:6.2f} uA | {state_str} "
    
    with term_lock:
        sys.stdout.write(f"\033[s\033[1;1H\033[K{bg_color}{status_line.ljust(80)}\033[0m\033[u")
        sys.stdout.flush()
    
    with open(CSV_FILENAME, "a", newline="") as f:
        csv.writer(f).writerow([data['timestamp'], latest_vmon, data['IMON'], state_str.strip()])
        if int(data['timestamp']) % 10 == 0:
            f.flush()
            os.fsync(f.fileno())

if __name__ == "__main__":
    sys.stdout.write("\033[2J\033[3;1H")
    
    if not os.path.exists(CSV_FILENAME):
        with open(CSV_FILENAME, "w", newline="") as f:
            csv.writer(f).writerow(["Timestamp", "VMON(V)", "IMON(uA)", "State"])

    pmt = DT5471N(port="/dev/dt5471n")
    pmt.on_telemetry = handle_telemetry
    pmt.on_error = print_error
    pmt.start()
    time.sleep(1)
    pmt.set_current_limit(50.0) 

    with term_lock:
        print("\n=== CPNR NaI(Tl) Field Control & Logging CLI ===")
        print("  [on]      : Power ON")
        print("  [off]     : Power OFF")
        print("  [v num]   : Set Target Voltage (e.g., v 900) - 30V/s Ramp")
        print("  [c]       : Clear Hardware Alarm (TRIP/OVC)")
        print("  [q]       : Exit Menu (Detach or Teardown)")
        print("====================================================\n")

    shutdown_mode = None

    while True:
        try:
            cmd_input = input("PMT> ").strip().lower()
            if not cmd_input: continue

            if cmd_input == 'q' or cmd_input == 'quit':
                with term_lock:
                    print("\n[Exit Menu]")
                    print("  1. Detach   - Keep HV ON, close software only")
                    print("  2. Teardown - Safe discharge to 0V, then turn OFF")
                    print("  0. Cancel")
                    choice = input("Select> ").strip()
                
                if choice == '1':
                    shutdown_mode = 'detach'
                    break
                elif choice == '2':
                    shutdown_mode = 'teardown'
                    break
                else:
                    with term_lock: print(" -> Canceled.")
            
            elif cmd_input == 'on':
                pmt.power_on()
                with term_lock: print(" -> [Command] Power ON")
                
            elif cmd_input == 'off':
                pmt.power_off()
                with term_lock: print(" -> [Command] Power OFF")
                
            elif cmd_input == 'c' or cmd_input == 'clear':
                pmt.clear_alarm()
                with term_lock: print(" -> [Command] Alarm cleared (BDCLR)")
                
            elif cmd_input.startswith('v '):
                try:
                    target_v = float(cmd_input.split()[1])
                    if 0 <= target_v <= 3000:
                        pmt.set_voltage(target_v, ramp_rate=30.0)
                        with term_lock: print(f" -> [Command] Target voltage set to {target_v}V")
                    else:
                        with term_lock: print(" -> [Error] Voltage range is 0 ~ 3000V.")
                except (IndexError, ValueError):
                    with term_lock: print(" -> [Error] Invalid format. (e.g., v 900)")
            else:
                with term_lock: print(" -> [Error] Unknown command.")
                
        except KeyboardInterrupt:
            with term_lock:
                choice = input("\n\nInterrupt detected. Keep HV ON? (Y/n): ").strip().lower()
            shutdown_mode = 'teardown' if choice == 'n' else 'detach'
            break

    if shutdown_mode == 'detach':
        with term_lock:
            print("\n[SYSTEM] Detaching. Serial port will be closed while keeping HV ON.")
        pmt.stop()
        
    elif shutdown_mode == 'teardown':
        with term_lock:
            print("\n[SYSTEM] Starting safe teardown. Ramping down to 0V...")
        pmt.set_voltage(0.0, ramp_rate=30.0)
        
        while latest_vmon > 10.0:
            with term_lock:
                sys.stdout.write(f"\r[SYSTEM] Discharging... Current: {latest_vmon:.1f}V (Safe: <10.0V)   ")
                sys.stdout.flush()
            time.sleep(1)
            
        pmt.power_off()
        time.sleep(0.5)
        pmt.stop()
        with term_lock:
            print("\n[SYSTEM] Hardware safely shut down. Port closed.")
