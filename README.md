# CPNR HV Control System (CAEN DT5471N)

고에너지 물리 실험(Gamma-ray & Neutrino Spectroscopy)을 위한 **CAEN DT5471N (1ch USB HV Power Supply)** 통합 제어 솔루션입니다. 

본 프로젝트는 현장(동굴)의 **Raspberry Pi 5 (Debian)**와 연구실의 **Alma/Rocky Linux 9 (RHEL)** 환경 모두에서 코드 한 줄의 수정 없이 100% 호환되는 **OS 독립적/이기종 통합 아키텍처**를 제공합니다.

---

## 1. 설계 동기 및 제1원리 (Design Philosophy)

### 왜 LabVIEW와 텔넷(가상 시리얼)을 버리고 '직접 직렬 제어(Direct Serial)'를 채택했는가?
기존의 제어 방식(제조사 제공 LabVIEW 드라이버 또는 Tera Term을 이용한 TUI 제어)은 사용자가 보기에 직관적일 수 있으나, 시스템 공학적 관점에서는 치명적인 한계를 가집니다.
1. **의존성 및 무거움**: LabVIEW 런타임은 무겁고 폐쇄적이며, RPi 5와 같은 ARM 아키텍처나 Headless Linux 환경(CLI)에서 구동이 불가능합니다.
2. **UI와 통신의 결합 (Coupling)**: 터미널 에뮬레이터(텔넷 스타일)는 사람을 위해 화면을 그리는 오버헤드가 발생합니다.
3. **해결책**: 장비의 본질적인 통신 규격인 **USB CDC ACM (가상 직렬 포트)**을 파이썬의 `pyserial`로 직접 타겟팅했습니다. 이는 중간의 무거운 프레임워크(GUI/TUI)를 걷어내고 기계어 수준의 API에 직접 바이트 스트림을 쏘아 보내는 가장 가볍고 빠르며 완벽하게 이식 가능한 방식입니다.

### 사용자 편의성과 하드웨어 보호의 양립
실험 현장에서의 돌발 상황(정전, 통신 단절, 사용자 실수)을 방어하기 위해 다음과 같은 제어 철학을 구현했습니다.
* **상태 분리 (Detach)**: 하드웨어 MCU의 독립적인 상태 머신을 신뢰하여, 소프트웨어가 종료되어도 HV 전압이 끊기지 않고 유지되도록 분리할 수 있습니다.
* **동적 안전 셧다운 (Dynamic Teardown)**: 하드코딩된 대기 시간이 아닌, 실시간 `VMON < 10.0V` 피드백을 확인한 후 물리적 릴레이를 차단하여 PMT 다이노드를 전기적 스파이크로부터 완벽히 보호합니다.

---

## 2. 디렉토리 구조 및 소스 코드 명세 (Architecture)

```text
caen-dt5471n-control/
├── .gitignore
├── README.md
├── requirements.txt           # pyserial, PyQt5, pyqtgraph
├── udev/
│   └── 99-dt5471n.rules       # Linux 커널 장치 영구 바인딩 규칙
└── src/
    ├── dt5471n_core.py        # [핵심] 하드웨어 통신 엔진 (OS/GUI 독립형)
    ├── dt5471n_cli.py         # 현장용 통합 CLI (Headless RPi5 용)
    └── dt5471n_gui.py         # 연구실용 통합 GUI (Rocky/Alma Linux 용)
```

* **`dt5471n_core.py`**: 물리적 I/O와 상태 비트마스크 디코딩을 전담합니다. `threading.Lock`과 `queue.Queue`를 사용한 단일 생산자-소비자 패턴으로 명령어 패킷 충돌(Race Condition)을 원천 차단합니다.
* **`dt5471n_cli.py`**: ANSI 이스케이프 코드를 활용하여 터미널 상단에 상태바를 고정하고, 하단에서 제어 명령을 동시에 입력받는 Thread-safe TUI를 제공합니다.
* **`dt5471n_gui.py`**: `pyqtgraph` 가속 엔진을 이용해 1주일 이상의 장기 시계열 모니터링 시에도 메모리 누수가 없는 실시간 대시보드 및 SQLite3 트랜잭션 로깅을 제공합니다.

---

## 3. CAEN DT5471N 통신 프로토콜 구조

이 시스템은 CAEN의 ASCII 기반 직렬 프로토콜을 파이썬 내부에서 동적으로 포맷팅하여 통신합니다.

* **명령어 전송 포맷 (Request)**
  `$CMD:[명령],PAR:[파라미터],VAL:[값]<CR,LF>`
  * 예시 (목표 전압 900V 설정): `$CMD:SET,PAR:VSET,VAL:900.00\r\n`
  * 예시 (상태 모니터링 요구): `$CMD:MON,PAR:STAT\r\n`
* **응답 포맷 (Response)**
  `#CMD:OK,VAL:[값]<CR,LF>` 또는 `#CMD:ERR`
* **상태 레지스터 디코딩 (Bitmasking)**
  장비가 반환하는 정수값을 비트 연산(`1 << N`)하여 상태를 추출합니다.
  (Bit 0: ON, Bit 1: RUP, Bit 2: RDW, Bit 3: OVC, Bit 7: TRIP, Bit 12: INTERLOCK 등)

---

## 4. 설치 및 실행 (Installation & Usage)

### Step 1. OS 장치 바인딩 (RPi5 / Alma / Rocky 공통)
USB 포트 연결 순서에 상관없이 디바이스 노드를 `/dev/dt5471n`으로 영구 고정합니다.
```bash
echo 'SUBSYSTEM=="tty", ATTRS{idVendor}=="21e1", ATTRS{idProduct}=="0006", SYMLINK+="dt5471n", MODE="0666"' | sudo tee /etc/udev/rules.d/99-dt5471n.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
sudo usermod -aG dialout $USER
# (적용을 위해 재부팅 또는 로그아웃 권장)
```

### Step 2. 파이썬 가상환경 설정 (PEP 668 대응)
최신 Linux 환경의 시스템 보호 정책을 준수하기 위해 가상환경(venv)을 사용합니다.
```bash
git clone [https://github.com/your-repo/caen-dt5471n-control.git](https://github.com/your-repo/caen-dt5471n-control.git)
cd caen-dt5471n-control

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 3. 프로그램 실행
**[A] 현장 제어용 (CLI Mode)**
```bash
python src/dt5471n_cli.py
```
> `v 900` 입력 시 900V로 자동 램핑(30V/s)되며, `csv` 파일에 1초 단위 데이터가 기록됩니다.

**[B] 연구실 분석용 (GUI Mode)**
```bash
python src/dt5471n_gui.py
```
> 시계열 그래프 모니터링 및 1분 단위 SQLite3 데이터베이스 로깅이 지원됩니다.

---

## 5. 하드웨어 안전 지침 (Safety Warnings)
* **PMT 다이노드 보호**: 프로그램 내에서 전압을 변경할 때마다 하드웨어에 `RUP` 및 `RDW` (30V/s) 제한 명령이 자동으로 선행 투입됩니다. 이 로직을 임의로 제거하지 마십시오.
* **안전 셧다운(Teardown)**: 프로그램을 완전히 종료할 때 0V 방전 절차를 건너뛰고 강제로 전원을 차단하면, 내부 커패시터에 남은 에너지가 스파이크를 일으켜 검출기를 파손시킬 수 있습니다.

---
**Developed by Center for Precision Neutrino Research (CPNR), Chonnam National University**
