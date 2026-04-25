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
        if stat["RUP"]: state_str += " (Ramping UP \u2191)"
        if stat["RDW"]: state_str += " (Ramping DOWN \u2193)"
        bg_color = "\033[44;97m" if stat["ON"] else "\033[40;97m"

    status_line = f" [{time.strftime('%H:%M:%S')}] VMON: {latest_vmon:6.1f} V | IMON: {data['IMON']:6.2f} uA | {state_str} "
    
    with term_lock:
        sys.stdout.write(f"\033[s\033[1;1H\033[K{bg_color}{status_line.ljust(80)}\033[0m\033[u")
        sys.stdout.flush()
    
    # 10초 주기로 디스크 플러시 최적화 (SD카드 수명 보호)
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
        print("  [on]      : 고전압 출력 켜기")
        print("  [off]     : 고전압 출력 끄기")
        print("  [v 숫자]  : 목표 전압 설정 (예: v 900) - 30V/s 램핑")
        print("  [c]       : 하드웨어 알람(TRIP/OVC) 초기화")
        print("  [q]       : 종료 메뉴 (상태 유지 분리 또는 0V 셧다운)")
        print("================================================\n")

    shutdown_mode = None

    while True:
        try:
            cmd_input = input("PMT> ").strip().lower()
            if not cmd_input: continue

            if cmd_input == 'q' or cmd_input == 'quit':
                with term_lock:
                    print("\n[시스템 종료 메뉴]")
                    print("  1. 상태 유지 (Detach) - HV 출력 유지, 모니터링만 종료")
                    print("  2. 안전 셧다운 (Teardown) - 0V 방전 확인 후 장비 OFF")
                    print("  0. 취소")
                    choice = input("선택> ").strip()
                
                if choice == '1':
                    shutdown_mode = 'detach'
                    break
                elif choice == '2':
                    shutdown_mode = 'teardown'
                    break
                else:
                    with term_lock: print(" -> 종료가 취소되었습니다.")
            
            elif cmd_input == 'on':
                pmt.power_on()
            elif cmd_input == 'off':
                pmt.power_off()
            elif cmd_input == 'c' or cmd_input == 'clear':
                pmt.clear_alarm()
            elif cmd_input.startswith('v '):
                try:
                    target_v = float(cmd_input.split()[1])
                    if 0 <= target_v <= 3000:
                        pmt.set_voltage(target_v, ramp_rate=30.0)
                        with term_lock: print(f" -> [명령 전송] 목표 전압 {target_v}V 설정 완료")
                    else:
                        with term_lock: print(" -> [오류] 설정 가능 전압 범위는 0 ~ 3000V 입니다.")
                except (IndexError, ValueError):
                    with term_lock: print(" -> [오류] 명령어 형식이 잘못되었습니다. (예: v 900)")
            else:
                with term_lock: print(" -> [오류] 알 수 없는 명령어입니다.")
                
        except KeyboardInterrupt:
            with term_lock:
                choice = input("\n\n인터럽트 감지. HV 출력을 유지하시겠습니까? (Y/n): ").strip().lower()
            shutdown_mode = 'teardown' if choice == 'n' else 'detach'
            break

    if shutdown_mode == 'detach':
        with term_lock:
            print("\n[SYSTEM] 장비 출력 상태를 유지한 채 포트를 닫고 통신을 해제(Detach)합니다.")
        pmt.stop()
        
    elif shutdown_mode == 'teardown':
        with term_lock:
            print("\n[SYSTEM] 시스템 안전 셧다운을 시작합니다. 0V로 램프 다운 하달...")
        pmt.set_voltage(0.0, ramp_rate=30.0)
        
        # 동적 전압 감시: 완전히 방전될 때까지 무한 대기
        while latest_vmon > 10.0:
            with term_lock:
                sys.stdout.write(f"\r[SYSTEM] 물리적 방전 대기 중... 현재 전압: {latest_vmon:.1f}V (Safe: <10V)   ")
                sys.stdout.flush()
            time.sleep(1)
            
        pmt.power_off()
        time.sleep(0.5)
        pmt.stop()
        with term_lock:
            print("\n[SYSTEM] 하드웨어 안전 셧다운 및 포트 닫기 완료.")
