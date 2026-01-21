#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>
#include <WiFiClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

const char* ssid = "CMCC-dNqR";           // WiFi名称 
const char* password = "cf25f9cy";      // WiFi密码 
  
// 服务器配置 - 请替换为您电脑的实际局域网IP 
const char* serverURL = "http://192.168.1.5:8000"; 
const char* deviceID = "ESP8266_001";

// 硬件引脚定义 (NodeMCU)
#define DHT_PIN D4          // DHT11 数据引脚 (GPIO2)
#define DHT_TYPE DHT11      // DHT11 传感器类型
#define SOIL_PIN A0         // 土壤湿度传感器模拟引脚
#define RELAY_PIN D1        // 继电器控制引脚 (GPIO5)
#define LED_PIN D0          // 状态指示LED (GPIO16)

DHT dht(DHT_PIN, DHT_TYPE);

void setup() {
  Serial.begin(115200);
  
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  // pinMode(BUTTON_PIN, INPUT_PULLUP); // 暂时未定义 BUTTON_PIN，如果需要请取消注释并定义引脚

  digitalWrite(RELAY_PIN, LOW); // 初始状态：继电器关闭 (根据您的描述 LOW 是关闭)
  digitalWrite(LED_PIN, LOW);   // 初始状态：LED 关闭

  dht.begin();

  WiFi.begin(ssid, password);
  Serial.println("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("");
  Serial.print("Connected to WiFi network with IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {
  // 1. 读取传感器数据
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  int soilValue = analogRead(SOIL_PIN);
  // 将模拟值映射到 0-100% (假设干燥是1024，湿润是0，需根据实际校准)
  int soilMoisture = map(soilValue, 1024, 0, 0, 100); 
  soilMoisture = constrain(soilMoisture, 0, 100);

  if (isnan(h) || isnan(t)) {
    Serial.println("Failed to read from DHT sensor!");
    return;
  }

  // 打印传感器数据到串口
  Serial.println("--- Sensor Data ---");
  Serial.print("Temperature: "); Serial.print(t); Serial.println(" °C");
  Serial.print("Humidity: "); Serial.print(h); Serial.println(" %");
  Serial.print("Soil Moisture (Raw): "); Serial.println(soilValue);
  Serial.print("Soil Moisture (%): "); Serial.print(soilMoisture); Serial.println(" %");
  Serial.println("-------------------");

  // 2. 上报数据到 MCP Server
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClient client;
    HTTPClient http;

    // --- 上报数据 ---
    http.begin(client, String(serverURL) + "/upload_data");
    http.addHeader("Content-Type", "application/json");
    
    // 构建 JSON 数据
    StaticJsonDocument<200> doc;
    doc["temperature"] = t;
    doc["humidity"] = h;
    doc["soil_moisture"] = soilMoisture;
    
    String requestBody;
    serializeJson(doc, requestBody);
    
    int httpResponseCode = http.POST(requestBody);
    if (httpResponseCode > 0) {
      Serial.print("Data Uploaded. Response code: ");
      Serial.println(httpResponseCode);
    } else {
      Serial.print("Error on sending POST: ");
      Serial.println(httpResponseCode);
    }
    http.end();

    // --- 获取控制指令 ---
    // 为了防止连接被过早关闭，重新创建一个 WiFiClient
    WiFiClient clientCmd;
    HTTPClient httpCmd;
    
    httpCmd.begin(clientCmd, String(serverURL) + "/get_command");
    int httpCode = httpCmd.GET();
    
    if (httpCode > 0) {
      String payload = httpCmd.getString();
      Serial.println("Command Received: " + payload);
      
      // 解析指令
      StaticJsonDocument<200> cmdDoc;
      deserializeJson(cmdDoc, payload);
      bool pumpOn = cmdDoc["pump_on"];
      
      // 执行继电器动作
      if (pumpOn) {
        Serial.println("Action: Relay ON");
        digitalWrite(RELAY_PIN, HIGH); // 开启 (根据您的逻辑 HIGH 是开启)
        digitalWrite(LED_PIN, HIGH);   // 亮灯 (根据您的逻辑 HIGH 是亮灯)
      } else {
        Serial.println("Action: Relay OFF");
        digitalWrite(RELAY_PIN, LOW);  // 关闭
        digitalWrite(LED_PIN, LOW);    // 灭灯
      }
    } else {
      Serial.print("Error on getting command: ");
      Serial.println(httpCode);
    }
    httpCmd.end();
  }

  delay(5000); // 每5秒循环一次
}
