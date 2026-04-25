#!/bin/bash

echo "====================================================="
echo "  Negative HV Control System - Auto Setup Script "
echo "====================================================="
echo ""

# 1. udev 규칙 생성 및 적용 (루트 권한 필요)
echo "[1/3] Configuring OS Device Binding (udev rules)..."
RULE_CONTENT='SUBSYSTEM=="tty", ATTRS{idVendor}=="21e1", ATTRS{idProduct}=="0006", SYMLINK+="dt5471n", MODE="0666"'

# sudo 권한으로 파일 생성
echo "$RULE_CONTENT" | sudo tee /etc/udev/rules.d/99-dt5471n.rules > /dev/null

# udev 데몬 리로드 및 장치 재탐색
sudo udevadm control --reload-rules
sudo udevadm trigger
echo " -> Success: /dev/dt5471n persistent symlink created."
echo ""

# 2. 직렬 통신 포트 권한 부여
echo "[2/3] Assigning serial port permissions..."
sudo usermod -aG dialout $USER
echo " -> Success: User '$USER' added to 'dialout' group."
echo " -> (Note: If this is the first time, you may need to logout and log back in for group changes to take effect.)"
echo ""

# 3. 파이썬 가상환경(PEP 668 대응) 구축 및 라이브러리 설치
echo "[3/3] Setting up Python Virtual Environment (venv)..."

# venv 폴더가 없으면 생성
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo " -> Created new virtual environment 'venv'."
else
    echo " -> Virtual environment 'venv' already exists."
fi

# 가상환경 활성화
source venv/bin/activate

# 의존성 설치
echo " -> Installing dependencies via pip..."
pip install --upgrade pip > /dev/null 2>&1
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    # requirements.txt가 없을 경우를 대비한 직접 설치
    pip install pyserial PyQt5 pyqtgraph
fi

echo ""
echo "====================================================="
echo " Setup Completed Successfully!"
echo "====================================================="
echo ""
echo "To start the system, please run the following commands:"
echo ""
echo "  source venv/bin/activate"
echo "  python dt5471n_cli.py    # For Terminal (Field)"
echo "  python dt5471n_gui.py    # For GUI (Lab)"
echo ""
