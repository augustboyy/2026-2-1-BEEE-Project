"""
아두이노 시리얼(JSON) 데이터를 수신해 API로 전달하는 리스너입니다.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
import serial

from app.config import load_settings

SERIAL_PORT = os.getenv("SERIAL_PORT")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
SERIAL_TIMEOUT = float(os.getenv("SERIAL_TIMEOUT", "1.0"))
RECONNECT_DELAY = float(os.getenv("SERIAL_RECONNECT_DELAY", "5.0"))


def _build_client() -> httpx.Client:
    settings = load_settings()
    return httpx.Client(base_url=settings.api_base_url, timeout=10)


def _dispatch_payload(client: httpx.Client, payload: dict[str, Any]) -> None:
    if "signal" in payload:
        endpoint = "/api/external/watering-signal"
    elif "moisture_value" in payload or "humidity" in payload:
        endpoint = "/api/external/sensor-data"
    else:
        raise ValueError("알 수 없는 JSON 형식입니다. signal 또는 moisture_value 필드가 필요합니다.")

    response = client.post(endpoint, json=payload)
    if response.is_error:
        detail = response.text
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        raise RuntimeError(f"API 오류: {detail}")


def listen() -> None:
    if not SERIAL_PORT:
        raise RuntimeError("SERIAL_PORT 환경 변수를 설정해 주세요. 예: /dev/ttyACM0")

    while True:
        try:
            with serial.Serial(
                SERIAL_PORT,
                SERIAL_BAUD,
                timeout=SERIAL_TIMEOUT,
            ) as ser, _build_client() as client:
                print(f"[Serial] Connected: {SERIAL_PORT} @ {SERIAL_BAUD}bps")
                while True:
                    raw = ser.readline()
                    if not raw:
                        continue
                    try:
                        text = raw.decode("utf-8").strip()
                    except UnicodeDecodeError as error:
                        print(f"[Serial] Decode error: {error}")
                        continue
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError as error:
                        print(f"[Serial] JSON parse error: {error} | raw={text}")
                        continue
                    if not isinstance(payload, dict):
                        print(f"[Serial] JSON is not an object: {payload}")
                        continue
                    try:
                        _dispatch_payload(client, payload)
                    except (ValueError, RuntimeError) as error:
                        print(f"[Serial] Dispatch error: {error}")
        except serial.SerialException as error:
            print(f"[Serial] Connection failed: {error}. Retrying in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)


def main() -> None:
    listen()


if __name__ == "__main__":
    main()
