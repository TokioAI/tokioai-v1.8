# TokioAI Sentinel 🛡️

## Hardware
- ESP32-S3 (dual-core 240MHz, 520KB SRAM, 4MB Flash)
- 2.8" LCD 240x320 (ILI9341, touch resistivo XPT2046)
- Speaker, RGB LED, SD Card, Battery connector
- USB-C (flash + power)

## Features
- WiFi Security Scanner (Evil Twin, Deauth, Probe Sniffing)
- BLE Scanner
- Network Monitor (ARP scan)
- AI Assistant (via TokioAI API)
- Badge Mode (conferencias)
- OTA Updates

## Build
```
# Instalar PlatformIO
pip install platformio

# Compilar
cd sentinel
pio run

# Flashear
pio run -t upload
```

## License
MIT — TokioAI Project
