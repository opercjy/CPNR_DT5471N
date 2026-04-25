import sys
import time
import datetime
import collections
import sqlite3
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QDoubleSpinBox, 
                             QGroupBox, QProgressDialog, QCheckBox, QMessageBox)
from PyQt5.QtCore import QObject, pyqtSignal, QTimer, Qt
import pyqtgraph as pg

from dt5471n_core import DT5471N

class SignalBridge(QObject):
    telemetry_signal = pyqtSignal(dict)
    error_signal = pyqtSignal(str)

class DAQ_MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CPNR NaI(Tl) HV Control")
        self.resize(1100, 800)
        
        self.max_points = 10000
        self.time_data = collections.deque(maxlen=self.max_points)
        self.v_data = collections.deque(maxlen=self.max_points)
        self.i_data = collections.deque(maxlen=self.max_points)
        self.last_log_time = 0.0
        self.last_vmon = 0.0

        self.init_database()

        self.bridge = SignalBridge()
        self.pmt = DT5471N(port="/dev/dt5471n")
        
        self._init_ui()
        
        self.bridge.telemetry_signal.connect(self.update_dashboard)
        self.bridge.error_signal.connect(self.show_error)
        self.pmt.on_telemetry = self.bridge.telemetry_signal.emit
        self.pmt.on_error = self.bridge.error_signal.emit
        
        self.shutdown_in_progress = False
        
        self.pmt.start()
        self.pmt.set_current_limit(50.0)

    def init_database(self):
        self.db_conn = sqlite3.connect("dt5471_datalog.db", check_same_thread=False)
        self.db_cursor = self.db_conn.cursor()
        self.db_cursor.execute("""
            CREATE TABLE IF NOT EXISTS pmt_log (
                timestamp REAL PRIMARY KEY,
                datetime TEXT,
                vmon REAL,
                imon REAL,
                status_str TEXT
            )
        """)
        self.db_conn.commit()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        control_layout = QVBoxLayout()
        
        dash_group = QGroupBox("Real-time Monitor (1 Hz)")
        dash_layout = QVBoxLayout()
        self.lbl_vmon = QLabel("VMON: 0.0 V")
        self.lbl_vmon.setStyleSheet("font-size: 24px; font-weight: bold; color: blue;")
        self.lbl_imon = QLabel("IMON: 0.00 uA")
        self.lbl_imon.setStyleSheet("font-size: 24px; font-weight: bold; color: green;")
        self.lbl_stat = QLabel("Status: OFFLINE")
        self.lbl_stat.setStyleSheet("font-size: 18px; font-weight: bold;")
        dash_layout.addWidget(self.lbl_vmon)
        dash_layout.addWidget(self.lbl_imon)
        dash_layout.addWidget(self.lbl_stat)
        dash_group.setLayout(dash_layout)
        
        cmd_group = QGroupBox("Hardware Control")
        cmd_layout = QVBoxLayout()
        
        self.btn_on = QPushButton("Power ON")
        self.btn_on.setStyleSheet("background-color: #4CAF50; color: white; height: 40px; font-weight: bold;")
        self.btn_off = QPushButton("Power OFF")
        self.btn_off.setStyleSheet("background-color: #f44336; color: white; height: 40px; font-weight: bold;")
        
        self.spin_vset = QDoubleSpinBox()
        self.spin_vset.setRange(0, 3000)
        self.spin_vset.setSuffix(" V")
        self.spin_vset.setValue(900.0)
        self.btn_set_v = QPushButton("Set Target Voltage (30V/s Ramp)")
        self.btn_clear = QPushButton("Clear ALARM (Reset)")
        
        self.chk_logging = QCheckBox("Enable DB Logging (1 min)")
        self.chk_logging.setChecked(False)
        self.chk_logging.setStyleSheet("font-weight: bold;")
        
        self.lbl_current_time = QLabel("Time: YYYY-MM-DD HH:MM:SS")
        self.lbl_current_time.setStyleSheet("font-family: monospace; font-weight: bold; color: #555; margin-top: 5px;")
        self.lbl_current_time.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        cmd_layout.addWidget(self.btn_on)
        cmd_layout.addWidget(self.btn_off)
        cmd_layout.addSpacing(20)
        cmd_layout.addWidget(QLabel("Target Voltage:"))
        cmd_layout.addWidget(self.spin_vset)
        cmd_layout.addWidget(self.btn_set_v)
        cmd_layout.addSpacing(20)
        cmd_layout.addWidget(self.btn_clear)
        cmd_layout.addSpacing(20)
        cmd_layout.addWidget(self.chk_logging)
        cmd_layout.addWidget(self.lbl_current_time)
        cmd_group.setLayout(cmd_layout)
        
        control_layout.addWidget(dash_group)
        control_layout.addWidget(cmd_group)
        control_layout.addStretch()
        
        plot_layout = QVBoxLayout()
        pg.setConfigOption('background', 'w')
        pg.setConfigOption('foreground', 'k')
        
        date_axis_v = pg.DateAxisItem(orientation='bottom')
        self.plot_widget_v = pg.PlotWidget(title="DT5471 - Voltage (V)", axisItems={'bottom': date_axis_v})
        self.plot_widget_v.setLabel('bottom', "Datetime (Local)")
        self.plot_widget_v.showGrid(x=True, y=True)
        self.curve_v = self.plot_widget_v.plot(pen=pg.mkPen('b', width=2))
        
        date_axis_i = pg.DateAxisItem(orientation='bottom')
        self.plot_widget_i = pg.PlotWidget(title="DT5471 - Current (uA)", axisItems={'bottom': date_axis_i})
        self.plot_widget_i.setLabel('bottom', "Datetime (Local)")
        self.plot_widget_i.showGrid(x=True, y=True)
        self.curve_i = self.plot_widget_i.plot(pen=pg.mkPen('g', width=2))
        
        plot_layout.addWidget(self.plot_widget_v)
        plot_layout.addWidget(self.plot_widget_i)
        
        main_layout.addLayout(control_layout, 1)
        main_layout.addLayout(plot_layout, 3)

        self.btn_on.clicked.connect(self.pmt.power_on)
        self.btn_off.clicked.connect(self.pmt.power_off)
        self.btn_set_v.clicked.connect(lambda: self.pmt.set_voltage(self.spin_vset.value(), 30.0))
        self.btn_clear.clicked.connect(self.pmt.clear_alarm)

    def update_dashboard(self, data: dict):
        self.last_vmon = data['VMON']
        imon = data['IMON']
        stat = data['STATUS']
        ts = data['timestamp']
        dt_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
        
        self.lbl_current_time.setText(f"Time: {dt_str}")
        self.lbl_vmon.setText(f"VMON: {self.last_vmon:6.1f} V")
        self.lbl_imon.setText(f"IMON: {imon:6.2f} uA")
        
        if stat["TRIP"] or stat["OVC"]:
            state_str = "ALARM (TRIP/OVC)"
            self.lbl_stat.setStyleSheet("font-size: 18px; font-weight: bold; color: red;")
        elif stat["ILK"]:
            state_str = "INTERLOCK"
            self.lbl_stat.setStyleSheet("font-size: 18px; font-weight: bold; color: orange;")
        else:
            state_str = "ON" if stat["ON"] else "OFF"
            if stat["RUP"]: state_str += " (Ramping UP)"
            if stat["RDW"]: state_str += " (Ramping DOWN)"
            self.lbl_stat.setStyleSheet("font-size: 18px; font-weight: bold; color: black;")
            
        self.lbl_stat.setText(f"Status: {state_str}")

        self.time_data.append(ts)
        self.v_data.append(self.last_vmon)
        self.i_data.append(imon)
        
        self.curve_v.setData(list(self.time_data), list(self.v_data))
        self.curve_i.setData(list(self.time_data), list(self.i_data))

        force_log = stat["TRIP"] or stat["OVC"]
        
        if self.chk_logging.isChecked() or force_log:
            current_time = time.time()
            if (current_time - self.last_log_time >= 60.0) or force_log:
                try:
                    self.db_cursor.execute(
                        "INSERT INTO pmt_log (timestamp, datetime, vmon, imon, status_str) VALUES (?, ?, ?, ?, ?)",
                        (ts, dt_str, self.last_vmon, imon, state_str)
                    )
                    self.db_conn.commit()
                    self.last_log_time = current_time
                except sqlite3.Error as e:
                    print(f"DB Logging Error: {e}")

    def show_error(self, msg: str):
        self.lbl_stat.setText(f"HW ERR: {msg[:30]}")
        self.lbl_stat.setStyleSheet("font-size: 18px; font-weight: bold; color: red;")

    def closeEvent(self, event):
        if self.shutdown_in_progress:
            event.accept()
            return

        reply = QMessageBox.question(
            self, 'System Exit',
            'Choose exit mode:\n\n'
            'Yes: Detach (Keep HV ON, close GUI only)\n'
            'No : Teardown (Safe discharge to 0V & Power OFF)',
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            self.pmt.stop()
            self.db_conn.close()
            event.accept()
        elif reply == QMessageBox.No:
            event.ignore()
            self.start_safe_shutdown()
        else:
            event.ignore()

    def start_safe_shutdown(self):
        self.shutdown_in_progress = True
        self.pmt.set_voltage(0.0, ramp_rate=30.0)
        
        self.progress = QProgressDialog("Safe Discharging...", None, 0, 0, self)
        self.progress.setCancelButton(None) 
        self.progress.setWindowTitle("System Safe Shutdown")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.show()
        
        self.shutdown_timer = QTimer()
        self.shutdown_timer.timeout.connect(self.process_shutdown)
        self.shutdown_timer.start(1000)

    def process_shutdown(self):
        self.progress.setLabelText(f"Discharging PMT...\nCurrent Voltage: {self.last_vmon:.1f} V (Safe: <10.0V)")
        
        if self.last_vmon < 10.0:
            self.shutdown_timer.stop()
            self.pmt.power_off()
            time.sleep(0.5) 
            self.pmt.stop()
            self.db_conn.close()
            self.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = DAQ_MainWindow()
    win.show()
    sys.exit(app.exec_())
