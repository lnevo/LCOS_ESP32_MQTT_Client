@echo off

cd /d "C:\Users\lnevo\Documents\LCOS_ESP32_MQTT_Client"

powershell -NoProfile -ExecutionPolicy Bypass -File "serial_to_mqtt.ps1" %*
