/*
 * TokioAI Sentinel v4.0 — FINAL
 * ESP32-2432S028 (CYD - Cheap Yellow Display)
 * Config: 100% community CYD official (build_flags)
 * Touch: XPT2046_Touchscreen (PaulStoffregen) — same as working test
 * 
 * RULE: Display/touch config is FROZEN. Only UI code changes allowed.
 */

#include <Arduino.h>
#include <SPI.h>
#include <XPT2046_Touchscreen.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include "esp_wifi.h"

// ═══════════════════════════════════════════
// TOUCH — EXACTLY like the working CYD test
// ═══════════════════════════════════════════
#define XPT2046_IRQ 36
#define XPT2046_MOSI 32
#define XPT2046_MISO 39
#define XPT2046_CLK 25
#define XPT2046_CS 33

SPIClass mySpi = SPIClass(VSPI);
XPT2046_Touchscreen ts(XPT2046_CS, XPT2046_IRQ);
TFT_eSPI tft = TFT_eSPI();

// ═══════════════════════════════════════════
// HARDWARE PINS
// ═══════════════════════════════════════════
#define SPK_PIN 26
#define LED_R 4
#define LED_G 16
#define LED_B 17

// ═══════════════════════════════════════════
// COLORS — TokioAI Cosmic Identity
// ═══════════════════════════════════════════
#define C_BG       TFT_BLACK                    // Pure black background
#define C_CYAN     tft.color565(0, 220, 180)    // TokioAI primary
#define C_PURPLE   tft.color565(120, 80, 160)   // TokioAI secondary
#define C_PINK     tft.color565(255, 80, 140)   // Accent
#define C_TEAL     tft.color565(0, 180, 220)    // Info
#define C_GREEN    tft.color565(0, 220, 100)    // OK
#define C_RED      tft.color565(255, 50, 50)    // Alert
#define C_ORANGE   tft.color565(255, 160, 0)    // Warning
#define C_WHITE    TFT_WHITE
#define C_GRAY     tft.color565(80, 80, 80)
#define C_DKGRAY   tft.color565(20, 20, 30)
#define C_SELECTOR tft.color565(5, 20, 30)      // Selected item bg

// ═══════════════════════════════════════════
// SCREEN DIMENSIONS (landscape rotation 1)
// ═══════════════════════════════════════════
#define SW 320
#define SH 240

// ═══════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════
enum Screen { BOOT, MENU, WIFI_SCAN, EVIL_TWIN, DEAUTH_MON, BLE_SCAN, BADGE, ABOUT };
Screen currentScreen = BOOT;
int menuSel = 0;
bool needRedraw = true;
unsigned long lastTouch = 0;

// Menu items
#define NUM_ITEMS 6
const char* menuLabels[] = {"WiFi Scanner", "Evil Twin", "Deauth Mon", "BLE Scan", "Badge Mode", "About"};
const char* menuIcons[] =  {"[W]", "[!]", "[D]", "[B]", "[#]", "[?]"};

// WiFi scan results
#define MAX_NETS 20
int numNets = 0;
String ssids[MAX_NETS];
int rssis[MAX_NETS];
int encTypes[MAX_NETS];
int channels[MAX_NETS];
String bssids[MAX_NETS];

// Evil twin results
bool evilFound = false;
String evilSSID = "";
int evilCount = 0;

// Deauth
volatile int deauthCount = 0;
bool deauthActive = false;
unsigned long deauthStart = 0;

// ═══════════════════════════════════════════
// TOUCH HELPERS — map raw to screen coords
// ═══════════════════════════════════════════
bool getTouch(int &x, int &y) {
  if (ts.tirqTouched() && ts.touched()) {
    TS_Point p = ts.getPoint();
    // Map raw touch to screen — same mapping as CYD community
    x = map(p.x, 200, 3700, 0, SW);
    y = map(p.y, 200, 3700, 0, SH);
    // Clamp
    if (x < 0) x = 0; if (x >= SW) x = SW-1;
    if (y < 0) y = 0; if (y >= SH) y = SH-1;
    return true;
  }
  return false;
}

// ═══════════════════════════════════════════
// SOUND
// ═══════════════════════════════════════════
void beep(int freq, int dur) { tone(SPK_PIN, freq, dur); }
void clickSound() { beep(4000, 15); }
void alertSound() { 
  for(int i=0; i<3; i++) { beep(2000, 100); delay(150); }
}
void bootMelody() {
  int notes[] = {523, 659, 784, 1047};
  for(int i=0; i<4; i++) { beep(notes[i], 80); delay(100); }
}

// ═══════════════════════════════════════════
// LED
// ═══════════════════════════════════════════
void ledColor(bool r, bool g, bool b) {
  digitalWrite(LED_R, !r); // active LOW
  digitalWrite(LED_G, !g);
  digitalWrite(LED_B, !b);
}

// ═══════════════════════════════════════════
// DRAW HELPERS
// ═══════════════════════════════════════════
void drawBox(int x, int y, int w, int h, uint16_t borderColor) {
  tft.drawRect(x, y, w, h, borderColor);
  tft.drawRect(x+1, y+1, w-2, h-2, C_DKGRAY);
}

void drawStatusBar() {
  tft.fillRect(0, 0, SW, 20, C_DKGRAY);
  tft.setTextColor(C_CYAN, C_DKGRAY);
  tft.setTextSize(1);
  tft.setCursor(4, 6);
  tft.print("[TOKIO] SENTINEL");
  
  // Right side: status
  tft.setTextColor(C_GREEN, C_DKGRAY);
  tft.setCursor(SW - 50, 6);
  tft.print("SECURE");
}

// Navigation bar at bottom: UP | GO | DN
#define NAV_Y (SH - 38)
#define NAV_H 38
#define BTN_W (SW / 3)

void drawNavBar() {
  // Background
  tft.fillRect(0, NAV_Y, SW, NAV_H, C_DKGRAY);
  
  // UP button
  tft.drawRect(1, NAV_Y+1, BTN_W-2, NAV_H-2, C_CYAN);
  tft.setTextColor(C_CYAN, C_DKGRAY);
  tft.setTextSize(2);
  tft.setCursor(BTN_W/2 - 12, NAV_Y + 10);
  tft.print("UP");
  
  // GO button
  tft.drawRect(BTN_W+1, NAV_Y+1, BTN_W-2, NAV_H-2, C_GREEN);
  tft.setTextColor(C_GREEN, C_DKGRAY);
  tft.setCursor(BTN_W + BTN_W/2 - 12, NAV_Y + 10);
  tft.print("GO");
  
  // DN button
  tft.drawRect(BTN_W*2+1, NAV_Y+1, BTN_W-2, NAV_H-2, C_CYAN);
  tft.setTextColor(C_CYAN, C_DKGRAY);
  tft.setCursor(BTN_W*2 + BTN_W/2 - 12, NAV_Y + 10);
  tft.print("DN");
}

void drawBackBar() {
  tft.fillRect(0, NAV_Y, SW, NAV_H, C_DKGRAY);
  tft.drawRect(SW/2-50, NAV_Y+2, 100, NAV_H-4, C_PINK);
  tft.setTextColor(C_PINK, C_DKGRAY);
  tft.setTextSize(2);
  tft.setCursor(SW/2-24, NAV_Y+10);
  tft.print("BACK");
}

// ═══════════════════════════════════════════
// BOOT ANIMATION
// ═══════════════════════════════════════════
void bootAnimation() {
  // Matrix rain effect
  tft.fillScreen(TFT_BLACK);
  tft.setTextSize(1);
  for(int frame=0; frame<30; frame++) {
    for(int i=0; i<8; i++) {
      int x = random(0, SW);
      int y = random(0, SH);
      tft.setTextColor(tft.color565(0, random(100,255), random(50,180)));
      char c = random(33, 126);
      tft.setCursor(x, y);
      tft.print(c);
    }
    delay(30);
  }
  
  // Logo
  tft.fillScreen(TFT_BLACK);
  
  // Draw spiral/hex shape
  int cx = SW/2, cy = SH/2 - 20;
  for(int r=5; r<50; r+=3) {
    float angle = r * 0.3;
    int x1 = cx + cos(angle) * r;
    int y1 = cy + sin(angle) * r;
    int x2 = cx + cos(angle + 0.3) * (r+3);
    int y2 = cy + sin(angle + 0.3) * (r+3);
    uint16_t col = tft.color565(0, 180 + r, 160 - r);
    tft.drawLine(x1, y1, x2, y2, col);
  }
  
  // Hex ring
  for(int i=0; i<6; i++) {
    float a = i * PI / 3.0;
    float a2 = (i+1) * PI / 3.0;
    int x1 = cx + cos(a)*55;
    int y1 = cy + sin(a)*55;
    int x2 = cx + cos(a2)*55;
    int y2 = cy + sin(a2)*55;
    tft.drawLine(x1, y1, x2, y2, C_PURPLE);
  }
  
  delay(500);
  
  // Title
  tft.setTextSize(2);
  tft.setTextColor(C_CYAN);
  tft.setCursor(SW/2 - 66, SH/2 + 40);
  tft.print("[TOKIO]");
  
  tft.setTextSize(2);
  tft.setTextColor(C_WHITE);
  tft.setCursor(SW/2 - 54, SH/2 + 62);
  tft.print("SENTINEL");
  
  delay(800);
  bootMelody();
  
  // System init messages
  tft.fillScreen(TFT_BLACK);
  tft.setTextSize(1);
  const char* msgs[] = {
    "> Initializing kernel...",
    "> WiFi module: READY",
    "> Touch sensor: READY", 
    "> Security engine: ARMED",
    "> TokioAI link: STANDBY",
    "> SENTINEL v4.0 ONLINE"
  };
  for(int i=0; i<6; i++) {
    tft.setTextColor(i<5 ? C_CYAN : C_GREEN);
    tft.setCursor(10, 40 + i*22);
    tft.print(msgs[i]);
    delay(300);
  }
  delay(600);
}


// ═══════════════════════════════════════════
// DRAW MENU
// ═══════════════════════════════════════════
void drawMenu() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  
  // Title
  tft.setTextColor(C_WHITE, C_BG);
  tft.setTextSize(1);
  tft.setCursor(4, 24);
  tft.print("MAIN MENU");
  
  // Menu items — area from y=34 to y=NAV_Y
  int itemH = (NAV_Y - 34) / NUM_ITEMS;
  if (itemH > 30) itemH = 30;
  
  for(int i=0; i<NUM_ITEMS; i++) {
    int y = 34 + i * itemH;
    bool selected = (i == menuSel);
    
    if (selected) {
      tft.fillRect(2, y, SW-4, itemH-2, C_SELECTOR);
      tft.drawRect(2, y, SW-4, itemH-2, C_CYAN);
    }
    
    // Icon
    uint16_t iconColors[] = {C_CYAN, C_RED, C_ORANGE, C_TEAL, C_PINK, C_GRAY};
    tft.setTextColor(iconColors[i], selected ? C_SELECTOR : C_BG);
    tft.setTextSize(1);
    tft.setCursor(8, y + (itemH-8)/2);
    tft.print(menuIcons[i]);
    
    // Label
    tft.setTextColor(selected ? C_WHITE : C_GRAY, selected ? C_SELECTOR : C_BG);
    tft.setTextSize(2);
    tft.setCursor(36, y + (itemH-16)/2);
    tft.print(menuLabels[i]);
    
    // Arrow for selected
    if (selected) {
      tft.setTextColor(C_CYAN, C_SELECTOR);
      tft.setCursor(SW - 20, y + (itemH-16)/2);
      tft.print(">");
    }
  }
  
  drawNavBar();
}

// ═══════════════════════════════════════════
// WIFI SCANNER
// ═══════════════════════════════════════════
void doWifiScan() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  tft.setTextColor(C_CYAN, C_BG);
  tft.setTextSize(2);
  tft.setCursor(10, 30);
  tft.print("Scanning WiFi...");
  
  ledColor(0, 0, 1); // blue while scanning
  beep(1000, 50);
  
  numNets = WiFi.scanNetworks();
  if (numNets > MAX_NETS) numNets = MAX_NETS;
  
  for(int i=0; i<numNets; i++) {
    ssids[i] = WiFi.SSID(i);
    rssis[i] = WiFi.RSSI(i);
    encTypes[i] = WiFi.encryptionType(i);
    channels[i] = WiFi.channel(i);
    bssids[i] = WiFi.BSSIDstr(i);
  }
  
  ledColor(0, 1, 0); // green done
  beep(2000, 50);
}

void drawWifiResults() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  
  tft.setTextColor(C_CYAN, C_BG);
  tft.setTextSize(1);
  tft.setCursor(4, 24);
  tft.printf("WiFi Networks: %d found", numNets);
  
  // Show up to 8 networks
  int maxShow = min(numNets, 8);
  for(int i=0; i<maxShow; i++) {
    int y = 36 + i * 20;
    
    // Signal strength indicator
    uint16_t sigColor = C_GREEN;
    if (rssis[i] < -70) sigColor = C_ORANGE;
    if (rssis[i] < -80) sigColor = C_RED;
    
    // Security
    const char* sec = "OPEN";
    uint16_t secColor = C_RED;
    if (encTypes[i] == WIFI_AUTH_WPA2_PSK || encTypes[i] == WIFI_AUTH_WPA_WPA2_PSK) {
      sec = "WPA2"; secColor = C_GREEN;
    } else if (encTypes[i] == WIFI_AUTH_WPA3_PSK || encTypes[i] == WIFI_AUTH_WPA2_WPA3_PSK) {
      sec = "WPA3"; secColor = C_GREEN;
    } else if (encTypes[i] == WIFI_AUTH_WPA_PSK) {
      sec = "WPA"; secColor = C_ORANGE;
    } else if (encTypes[i] == WIFI_AUTH_WEP) {
      sec = "WEP"; secColor = C_RED;
    }
    
    // SSID (truncated)
    String name = ssids[i].substring(0, 16);
    tft.setTextColor(C_WHITE, C_BG);
    tft.setCursor(4, y);
    tft.print(name);
    
    // Channel
    tft.setTextColor(C_GRAY, C_BG);
    tft.setCursor(200, y);
    tft.printf("Ch%d", channels[i]);
    
    // Signal
    tft.setTextColor(sigColor, C_BG);
    tft.setCursor(240, y);
    tft.printf("%ddBm", rssis[i]);
    
    // Security
    tft.setTextColor(secColor, C_BG);
    tft.setCursor(290, y);
    tft.print(sec);
  }
  
  drawBackBar();
}

// ═══════════════════════════════════════════
// EVIL TWIN DETECTOR
// ═══════════════════════════════════════════
void doEvilTwinScan() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  tft.setTextColor(C_ORANGE, C_BG);
  tft.setTextSize(2);
  tft.setCursor(10, 30);
  tft.print("Evil Twin Scan...");
  
  ledColor(1, 1, 0); // yellow
  
  // Scan 3 times for reliability
  evilFound = false;
  evilCount = 0;
  
  for(int pass=0; pass<3; pass++) {
    int n = WiFi.scanNetworks();
    tft.setTextColor(C_GRAY, C_BG);
    tft.setTextSize(1);
    tft.setCursor(10, 60 + pass*12);
    tft.printf("Pass %d: %d networks", pass+1, n);
    
    for(int i=0; i<n; i++) {
      for(int j=i+1; j<n; j++) {
        if (WiFi.SSID(i) == WiFi.SSID(j) && WiFi.BSSIDstr(i) != WiFi.BSSIDstr(j)) {
          evilFound = true;
          evilSSID = WiFi.SSID(i);
          evilCount++;
        }
      }
    }
  }
  
  if (evilFound) {
    ledColor(1, 0, 0); // RED alert
    alertSound();
  } else {
    ledColor(0, 1, 0); // green OK
    beep(2000, 100);
  }
}

void drawEvilResults() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  
  if (evilFound) {
    tft.setTextColor(C_RED, C_BG);
    tft.setTextSize(2);
    tft.setCursor(SW/2 - 72, 40);
    tft.print("!! ALERT !!");
    
    tft.setTextColor(C_ORANGE, C_BG);
    tft.setTextSize(1);
    tft.setCursor(10, 70);
    tft.printf("Evil Twin detected: %d", evilCount);
    
    tft.setTextColor(C_WHITE, C_BG);
    tft.setCursor(10, 90);
    tft.printf("SSID: %s", evilSSID.c_str());
    
    tft.setTextColor(C_RED, C_BG);
    tft.setCursor(10, 120);
    tft.print("WARNING: Possible rogue AP!");
    tft.setCursor(10, 135);
    tft.print("Do NOT connect to this network.");
  } else {
    tft.setTextColor(C_GREEN, C_BG);
    tft.setTextSize(2);
    tft.setCursor(SW/2 - 24, 60);
    tft.print("SAFE");
    
    tft.setTextColor(C_CYAN, C_BG);
    tft.setTextSize(1);
    tft.setCursor(10, 100);
    tft.print("No Evil Twin networks detected.");
    tft.setCursor(10, 120);
    tft.print("All SSIDs have unique BSSIDs.");
  }
  
  drawBackBar();
}


// ═══════════════════════════════════════════
// DEAUTH MONITOR
// ═══════════════════════════════════════════
void IRAM_ATTR promiscCallback(void* buf, wifi_promiscuous_pkt_type_t type) {
  if (type != WIFI_PKT_MGMT) return;
  const wifi_promiscuous_pkt_t* pkt = (wifi_promiscuous_pkt_t*)buf;
  const uint8_t* frame = pkt->payload;
  uint8_t frameType = frame[0];
  // Deauth = 0xC0, Disassoc = 0xA0
  if (frameType == 0xC0 || frameType == 0xA0) {
    deauthCount++;
  }
}

void startDeauth() {
  deauthCount = 0;
  deauthActive = true;
  deauthStart = millis();
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  delay(100);
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_rx_cb(promiscCallback);
  esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);
  ledColor(1, 0, 1); // purple = monitoring
}

void stopDeauth() {
  esp_wifi_set_promiscuous(false);
  deauthActive = false;
  ledColor(0, 1, 0);
}

void drawDeauth() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  
  tft.setTextColor(C_ORANGE, C_BG);
  tft.setTextSize(2);
  tft.setCursor(10, 30);
  tft.print("Deauth Monitor");
  
  unsigned long elapsed = (millis() - deauthStart) / 1000;
  
  // Big counter
  tft.setTextColor(deauthCount > 0 ? C_RED : C_GREEN, C_BG);
  tft.setTextSize(4);
  tft.setCursor(SW/2 - 40, 70);
  tft.printf("%d", deauthCount);
  
  tft.setTextColor(C_GRAY, C_BG);
  tft.setTextSize(1);
  tft.setCursor(SW/2 - 30, 110);
  tft.print("packets");
  
  // Elapsed time
  tft.setTextColor(C_CYAN, C_BG);
  tft.setCursor(10, 140);
  tft.printf("Time: %lus", elapsed);
  
  // PPS
  float pps = elapsed > 0 ? (float)deauthCount / elapsed : 0;
  tft.setCursor(10, 155);
  tft.printf("Rate: %.1f pkt/s", pps);
  
  // Status
  if (deauthCount > 10) {
    tft.setTextColor(C_RED, C_BG);
    tft.setCursor(10, 180);
    tft.print("!! DEAUTH ATTACK DETECTED !!");
    ledColor(1, 0, 0);
  } else if (deauthCount > 0) {
    tft.setTextColor(C_ORANGE, C_BG);
    tft.setCursor(10, 180);
    tft.print("Suspicious activity...");
  } else {
    tft.setTextColor(C_GREEN, C_BG);
    tft.setCursor(10, 180);
    tft.print("Channel clean — no threats");
  }
  
  drawBackBar();
}

// ═══════════════════════════════════════════
// BLE SCANNER
// ═══════════════════════════════════════════
void drawBLE() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  
  tft.setTextColor(C_TEAL, C_BG);
  tft.setTextSize(2);
  tft.setCursor(10, 30);
  tft.print("BLE Scanner");
  
  tft.setTextColor(C_GRAY, C_BG);
  tft.setTextSize(1);
  tft.setCursor(10, 60);
  tft.print("BLE scan requires BLE library.");
  tft.setCursor(10, 75);
  tft.print("Use Serial: BLE command.");
  
  drawBackBar();
}

// ═══════════════════════════════════════════
// BADGE MODE
// ═══════════════════════════════════════════
void drawBadge() {
  tft.fillScreen(TFT_BLACK);
  
  // Outer frame
  tft.drawRect(2, 2, SW-4, SH-4, C_CYAN);
  tft.drawRect(4, 4, SW-8, SH-8, C_PURPLE);
  
  // Draw spiral in corner
  int cx = 50, cy = SH/2;
  for(int r=3; r<35; r+=2) {
    float angle = r * 0.35;
    int x1 = cx + cos(angle) * r;
    int y1 = cy + sin(angle) * r;
    int x2 = cx + cos(angle+0.35) * (r+2);
    int y2 = cy + sin(angle+0.35) * (r+2);
    uint16_t col = tft.color565(0, 150+r*2, 130+r);
    tft.drawLine(x1, y1, x2, y2, col);
  }
  
  // Name
  tft.setTextColor(C_WHITE);
  tft.setTextSize(3);
  tft.setCursor(90, 50);
  tft.print("TokioAI");
  
  // Role
  tft.setTextColor(C_CYAN);
  tft.setTextSize(2);
  tft.setCursor(90, 90);
  tft.print("Security Agent");
  
  // Separator
  tft.drawFastHLine(90, 120, 200, C_PURPLE);
  
  // Info
  tft.setTextColor(C_PINK);
  tft.setTextSize(1);
  tft.setCursor(90, 135);
  tft.print("Autonomous AI Defense System");
  
  tft.setTextColor(C_GRAY);
  tft.setCursor(90, 155);
  tft.print("WAF | WiFi Defense | IoT");
  
  tft.setCursor(90, 175);
  tft.print("github.com/tokioai");
  
  // Version
  tft.setTextColor(C_DKGRAY);
  tft.setCursor(SW/2-30, SH-20);
  tft.print("SENTINEL v4.0");
  
  drawBackBar();
}

// ═══════════════════════════════════════════
// ABOUT
// ═══════════════════════════════════════════
void drawAbout() {
  tft.fillScreen(C_BG);
  drawStatusBar();
  
  tft.setTextColor(C_CYAN, C_BG);
  tft.setTextSize(2);
  tft.setCursor(10, 30);
  tft.print("About Sentinel");
  
  tft.setTextColor(C_WHITE, C_BG);
  tft.setTextSize(1);
  int y = 60;
  const char* info[] = {
    "TokioAI Sentinel v4.0",
    "ESP32-2432S028 (CYD)",
    "",
    "WiFi Security Scanner",
    "Evil Twin Detector",
    "Deauth Attack Monitor",
    "BLE Device Scanner",
    "",
    "by TokioAI Team",
    "tokioai.github.io"
  };
  for(int i=0; i<10; i++) {
    tft.setTextColor(i==0 ? C_CYAN : (i==8||i==9 ? C_PINK : C_GRAY), C_BG);
    tft.setCursor(10, y + i*14);
    tft.print(info[i]);
  }
  
  drawBackBar();
}

// ═══════════════════════════════════════════
// HANDLE TOUCH
// ═══════════════════════════════════════════
void handleTouch() {
  int tx, ty;
  if (!getTouch(tx, ty)) return;
  
  // Debounce
  if (millis() - lastTouch < 350) return;
  lastTouch = millis();
  clickSound();
  
  if (currentScreen == MENU) {
    // Check navbar: UP | GO | DN
    if (ty >= NAV_Y) {
      if (tx < BTN_W) {
        // UP
        menuSel--;
        if (menuSel < 0) menuSel = NUM_ITEMS - 1;
        needRedraw = true;
      } else if (tx < BTN_W * 2) {
        // GO — enter selected item
        switch(menuSel) {
          case 0: currentScreen = WIFI_SCAN; doWifiScan(); drawWifiResults(); break;
          case 1: currentScreen = EVIL_TWIN; doEvilTwinScan(); drawEvilResults(); break;
          case 2: currentScreen = DEAUTH_MON; startDeauth(); drawDeauth(); break;
          case 3: currentScreen = BLE_SCAN; drawBLE(); break;
          case 4: currentScreen = BADGE; drawBadge(); break;
          case 5: currentScreen = ABOUT; drawAbout(); break;
        }
      } else {
        // DOWN
        menuSel++;
        if (menuSel >= NUM_ITEMS) menuSel = 0;
        needRedraw = true;
      }
    }
  } else {
    // In any sub-screen, check BACK button
    if (ty >= NAV_Y) {
      if (currentScreen == DEAUTH_MON) stopDeauth();
      currentScreen = MENU;
      needRedraw = true;
    }
  }
}

// ═══════════════════════════════════════════
// SERIAL CLI
// ═══════════════════════════════════════════
void handleSerial() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  cmd.toUpperCase();
  
  if (cmd == "SCAN") {
    Serial.println("[SENTINEL] Starting WiFi scan...");
    currentScreen = WIFI_SCAN;
    doWifiScan();
    drawWifiResults();
    for(int i=0; i<numNets; i++) {
      Serial.printf("  %s | Ch%d | %ddBm | %s\n", 
        ssids[i].c_str(), channels[i], rssis[i],
        encTypes[i] == WIFI_AUTH_OPEN ? "OPEN" : "SECURED");
    }
  } else if (cmd == "EVIL") {
    Serial.println("[SENTINEL] Evil Twin scan...");
    currentScreen = EVIL_TWIN;
    doEvilTwinScan();
    drawEvilResults();
    Serial.printf("  Result: %s\n", evilFound ? "EVIL TWIN FOUND!" : "Clean");
  } else if (cmd == "DEAUTH") {
    Serial.println("[SENTINEL] Starting deauth monitor...");
    currentScreen = DEAUTH_MON;
    startDeauth();
  } else if (cmd == "STOP") {
    stopDeauth();
    Serial.println("[SENTINEL] Deauth monitor stopped");
  } else if (cmd == "STATUS") {
    Serial.println("[SENTINEL] Status Report");
    Serial.printf("  Screen: %d\n", currentScreen);
    Serial.printf("  WiFi nets: %d\n", numNets);
    Serial.printf("  Deauth pkts: %d\n", deauthCount);
    Serial.printf("  Free heap: %d\n", ESP.getFreeHeap());
  } else if (cmd == "MENU") {
    currentScreen = MENU;
    needRedraw = true;
  } else {
    Serial.println("[SENTINEL] Commands: SCAN, EVIL, DEAUTH, STOP, STATUS, MENU");
  }
}

// ═══════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  Serial.println("\n[TOKIO] Sentinel v4.0 booting...");
  
  // LED pins
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  ledColor(0, 0, 1); // blue = booting
  
  // Speaker
  pinMode(SPK_PIN, OUTPUT);
  
  // Touch — EXACTLY like the working CYD test
  mySpi.begin(XPT2046_CLK, XPT2046_MISO, XPT2046_MOSI, XPT2046_CS);
  ts.begin(mySpi);
  ts.setRotation(1);
  
  // Display
  tft.init();
  
  // Clean GRAM — fill all 4 rotations to eliminate white fringe
  for(int r=0; r<4; r++) {
    tft.setRotation(r);
    tft.fillScreen(TFT_BLACK);
  }
  tft.setRotation(1); // landscape final
  tft.invertDisplay(true); // Fix: invert colors so black=dark
  
  // WiFi init (station mode for scanning)
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  
  // Boot animation
  bootAnimation();
  
  // Show menu
  currentScreen = MENU;
  needRedraw = true;
  ledColor(0, 1, 0); // green = ready
  
  Serial.println("[TOKIO] Sentinel ONLINE. Type HELP for commands.");
}

// ═══════════════════════════════════════════
// LOOP
// ═══════════════════════════════════════════
void loop() {
  handleTouch();
  handleSerial();
  
  if (needRedraw) {
    needRedraw = false;
    if (currentScreen == MENU) drawMenu();
  }
  
  // Deauth monitor auto-refresh
  if (currentScreen == DEAUTH_MON && deauthActive) {
    static unsigned long lastRefresh = 0;
    if (millis() - lastRefresh > 1000) {
      lastRefresh = millis();
      // Channel cycling
      static int ch = 1;
      ch = (ch % 13) + 1;
      esp_wifi_set_channel(ch, WIFI_SECOND_CHAN_NONE);
      drawDeauth();
    }
  }
  
  delay(20);
}

