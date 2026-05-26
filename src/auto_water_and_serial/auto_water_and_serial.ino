#include <DHT.h>
#include <math.h>

// 핀 및 센서 설정
#define DHTPIN 2          
#define DHTTYPE DHT11     
#define SOIL_MOISTURE_PIN A0 
#define RELAY_PIN 8       // 릴레이 모듈 제어 핀 (펌프 연결)

DHT dht(DHTPIN, DHTTYPE);

// 설정값
const int MOISTURE_THRESHOLD = 800; // 급수 시작 기준값 (실험 후 조정 필요)
const unsigned long SEND_INTERVAL = 60000; // 1분 (ms 단위)
const int PLANT_ID = 1; // FastAPI에 등록된 식물 ID로 맞춰주세요.
const char* SENSOR_SOURCE = "arduino-serial";
const char* WATER_SIGNAL = "WATER!";
const unsigned long ACK_TIMEOUT_MS = 500;
const int MAX_RETRIES = 3;
unsigned long seqCounter = 0;
String ackBuffer = "";
float pendingTemp = NAN;
int pendingMoisture = 0;
unsigned long lastSendTime = 0;

void setup() {
  Serial.begin(115200); // 라즈베리파이와 시리얼 통신 속도 일치
  dht.begin();
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW); // 초기 상태: 펌프 꺼짐
  Serial.setTimeout(200);
}

void loop() {
  unsigned long currentTime = millis();
  
  // 1. 센서 데이터 읽기
  float temperature = dht.readTemperature(); // DHT11은 온도만 사용
  int soilMoistureRaw = analogRead(SOIL_MOISTURE_PIN);

  // 2. 자동 급수 로직 (토양 습도가 기준치 이하일 때)
  // % 기준일 경우 예: soilMoisturePercent < 30
  if (soilMoistureRaw > MOISTURE_THRESHOLD) { 
    digitalWrite(RELAY_PIN, HIGH); // 펌프 가동
    
    // 즉시 보고 (JSON 프로토콜, 급수 신호 전송)
    sendWateringSignal();
    sendSensorPacket(temperature, soilMoistureRaw);
    
    delay(2000); // 2초간 급수 (시스템 규모에 맞게 조절)
    digitalWrite(RELAY_PIN, LOW);  // 펌프 중지
  }

  // 3. 1분 주기 정기 보고
  if (currentTime - lastSendTime >= SEND_INTERVAL) {
    lastSendTime = currentTime;
    sendSensorPacket(temperature, soilMoistureRaw);
  }
}

/**
 * 라즈베리파이 시리얼 리스너용 JSON 패킷 전송
 */
uint8_t computeChecksum(int plantId, int moisture, float temp, unsigned long seq, int typeCode) {
  int tempX10 = 0;
  if (!isnan(temp)) {
    tempX10 = (int)lroundf(temp * 10.0f);
  }
  unsigned long sum = (unsigned long)plantId + (unsigned long)moisture + (unsigned long)tempX10 + seq + (unsigned long)typeCode;
  return (uint8_t)(sum & 0xFF);
}

bool waitForAck(unsigned long seq) {
  unsigned long start = millis();
  while (millis() - start < ACK_TIMEOUT_MS) {
    while (Serial.available() > 0) {
      char ch = Serial.read();
      if (ch == '\n') {
        String line = ackBuffer;
        ackBuffer = "";
        line.trim();
        if (line.startsWith("ACK:")) {
          if ((unsigned long)line.substring(4).toInt() == seq) {
            return true;
          }
        } else if (line.startsWith("NACK:")) {
          if ((unsigned long)line.substring(5).toInt() == seq) {
            return false;
          }
        }
      } else if (ch != '\r') {
        ackBuffer += ch;
        if (ackBuffer.length() > 80) {
          ackBuffer = "";
        }
      }
    }
  }
  return false;
}

bool sendWithRetry(void (*emitPacket)(unsigned long), unsigned long seq) {
  for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
    emitPacket(seq);
    if (waitForAck(seq)) {
      return true;
    }
    delay(50);
  }
  return false;
}

void emitSensorPacket(unsigned long seq) {
  float temp = pendingTemp;
  int soilMoisturePercent = pendingMoisture;
  uint8_t checksum = computeChecksum(PLANT_ID, soilMoisturePercent, temp, seq, 1);

  Serial.print("{\"plant_id\":");
  Serial.print(PLANT_ID);
  Serial.print(",\"moisture_value\":");
  Serial.print(soilMoisturePercent);
  Serial.print(",\"temperature\":");
  if (isnan(temp)) {
    Serial.print("null");
  } else {
    Serial.print(temp, 1);
  }
  Serial.print(",\"source\":\"");
  Serial.print(SENSOR_SOURCE);
  Serial.print("\",\"seq\":");
  Serial.print(seq);
  Serial.print(",\"ts\":");
  Serial.print(millis());
  Serial.print(",\"checksum\":");
  Serial.print(checksum);
  Serial.println("}");
}

void emitWateringSignal(unsigned long seq) {
  uint8_t checksum = computeChecksum(PLANT_ID, 0, NAN, seq, 2);
  Serial.print("{\"plant_id\":");
  Serial.print(PLANT_ID);
  Serial.print(",\"signal\":\"");
  Serial.print(WATER_SIGNAL);
  Serial.print("\",\"source\":\"");
  Serial.print(SENSOR_SOURCE);
  Serial.print("\",\"seq\":");
  Serial.print(seq);
  Serial.print(",\"ts\":");
  Serial.print(millis());
  Serial.print(",\"checksum\":");
  Serial.print(checksum);
  Serial.println("}");
}

void sendSensorPacket(float temp, int moisture) {
  pendingTemp = temp;
  pendingMoisture = moisture;
  unsigned long seq = ++seqCounter;
  sendWithRetry(emitSensorPacket, seq);
}

void sendWateringSignal() {
  unsigned long seq = ++seqCounter;
  sendWithRetry(emitWateringSignal, seq);
}
