"""Lit le port série de la carte et affiche chaque ligne avec un horodatage.

Usage :
    py -3.11 tools/uart_monitor.py              # COM3, 115200 par défaut
    py -3.11 tools/uart_monitor.py COM5 115200
Dépendance : pip install pyserial
"""
import sys
import time

import serial  # pyserial

port = sys.argv[1] if len(sys.argv) > 1 else "COM3"
baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

print(f"Ouverture de {port} @ {baud} 8N1 (Ctrl+C pour quitter)")
with serial.Serial(port, baud, timeout=1) as ser:
    t0 = time.time()
    while True:
        line = ser.readline()  # lit jusqu'à '\n' ou timeout
        if line:
            # errors="replace" : un mauvais baudrate donne des caractères bizarres au lieu d'un crash
            text = line.decode("utf-8", errors="replace").rstrip()
            print(f"[{time.time() - t0:8.3f}] {text}")
