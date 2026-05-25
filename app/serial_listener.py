"""
아두이노 시리얼(JSON) 데이터를 수신해 API로 전달하는 리스너입니다.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Tuple

import httpx
import serial

from app.config import load_settings

SERIAL_PORT = os.getenv("SERIAL_PORT")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
SERIAL_TIMEOUT = float(os.getenv("SERIAL_TIMEOUT", "1.0"))
RECONNECT_DELAY = float(os.getenv("SERIAL_RECONNECT_DELAY", "5.0"))
ACK_PREFIX = "ACK:"
NACK_PREFIX = "NACK:"
SEQ_TRACK_LIMIT = 2000


def _build_client() -> httpx.Client:
    settings = load_settings()
    return httpx.Client(base_url=settings.api_base_url, timeout=10)


def _dispatch_payload(client: httpx.Client, payload: dict[str, Any]) -> None:
    if "signal" in payload:
        endpoint = "/api/external/watering-signal"
    elif "moisture_value" in payload or "temperature" in payload:
        endpoint = "/api/external/sensor-data"
    else:
        raise ValueError("알 수 없는 JSON 형식입니다. signal 또는 moisture_value 필드가 필요합니다.")

    try:
        response = client.post(endpoint, json=payload)
        if response.is_error:
            detail = response.text
            try:
                detail = response.json().get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(detail)
    except httpx.RequestError as e:
        raise RuntimeError(f"API 연결 실패 (서버가 응답하지 않음): {e}")


def _calc_checksum(payload: dict[str, Any]) -> int:
    plant_id = int(payload.get("plant_id") or 0)
    seq = int(payload.get("seq") or 0)
    type_code = 2 if "signal" in payload else 1
    moisture_value = payload.get("moisture_value")
    try:
        moisture = int(round(float(moisture_value))) if moisture_value is not None else 0
    except (TypeError, ValueError):
        moisture = 0
    temp_value = payload.get("temperature")
    try:
        temp_x10 = int(round(float(temp_value) * 10)) if temp_value is not None else 0
    except (TypeError, ValueError):
        temp_x10 = 0
    return (plant_id + moisture + temp_x10 + seq + type_code) & 0xFF


def _write_ack(ser: serial.Serial, seq: int) -> None:
    ser.write(f"{ACK_PREFIX}{seq}\n".encode("utf-8"))


def _write_nack(ser: serial.Serial, seq: int | None) -> None:
    if seq is None:
        ser.write(f"{NACK_PREFIX}\n".encode("utf-8"))
    else:
        ser.write(f"{NACK_PREFIX}{seq}\n".encode("utf-8"))


def listen() -> None:
    if not SERIAL_PORT:
        raise RuntimeError("SERIAL_PORT 환경 변수를 설정해 주세요. 예: /dev/ttyACM0")

    last_seq_by_key: dict[Tuple[str, int, str], int] = {}
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
                        _write_nack(ser, None)
                        continue
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                    except json.JSONDecodeError as error:
                        print(f"[Serial] JSON parse error: {error} | raw={text}")
                        _write_nack(ser, None)
                        continue
                    if not isinstance(payload, dict):
                        print(f"[Serial] JSON is not an object: {payload}")
                        _write_nack(ser, None)
                        continue
                    seq_raw = payload.get("seq")
                    checksum_raw = payload.get("checksum")
                    try:
                        seq = int(seq_raw)
                    except (TypeError, ValueError):
                        seq = None
                    try:
                        checksum = int(checksum_raw)
                    except (TypeError, ValueError):
                        checksum = None
                    if seq is None or checksum is None:
                        print(f"[Serial] Missing seq/checksum: {payload}")
                        _write_nack(ser, seq)
                        continue
                    expected = _calc_checksum(payload)
                    if checksum != expected:
                        print(f"[Serial] Checksum mismatch: got={checksum} expected={expected} payload={payload}")
                        _write_nack(ser, seq)
                        continue

                    source = str(payload.get("source") or "unknown")
                    plant_id = int(payload.get("plant_id") or 0)
                    kind = "signal" if "signal" in payload else "sensor"
                    key = (source, plant_id, kind)
                    last_seq = last_seq_by_key.get(key)
                    if last_seq is not None and seq <= last_seq:
                        _write_ack(ser, seq)
                        continue
                    try:
                        _dispatch_payload(client, payload)
                        last_seq_by_key[key] = seq
                        if len(last_seq_by_key) > SEQ_TRACK_LIMIT:
                            last_seq_by_key.clear()
                        _write_ack(ser, seq)
                    except (ValueError, RuntimeError) as error:
                        print(f"[Serial] Dispatch error: {error}")
                        _write_nack(ser, seq)
        except serial.SerialException as error:
            print(f"[Serial] Connection failed: {error}. Retrying in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)


def main() -> None:
    listen()


if __name__ == "__main__":
    main()
