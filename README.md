# Camera MJPEG Streaming with MQTT

This project provides real-time camera streaming using MJPEG over HTTP with MQTT remote control capabilities.

## Features

- **MJPEG HTTP Streaming**: Real-time camera feed via HTTP on port 7200
- **MQTT Integration**: Remote camera control and status monitoring
- **Headless Operation**: Optimized for server environments without display
- **Web Interface**: Built-in HTML viewer for easy access

## Configuration

- **HTTP Server**: `http://0.0.0.0:7200`
- **Stream Endpoint**: `/stream`
- **Web Viewer**: `/`
- **MQTT Broker**: `spcwtech.mooo.com:1883`

## Usage

```bash
python3 camera6.py
```

## Requirements

- OpenCV (cv2)
- paho-mqtt
- Python 3.x

## MQTT Topics

- `camera/stream_url`: Published stream URL
- `camera/control`: Remote control commands
- `camera/status`: Camera status updates

## Author

Created by spcwtech (spcw1234@hanmail.net)

---

## 개발 기록 (Development Log)

### 2025년 6월 5일 - 모바일 페이지 지원 및 MQTT 기능 개선

#### ✅ 완료된 작업들:

**1. 모바일 페이지 지원 추가**
- `/mobile` 엔드포인트 구현
- 전체화면 지원 및 터치 제스처 최적화
- 화면 깨우기 방지 (Wake Lock) 기능
- 모바일 전용 UI 인터페이스

**2. CORS 보안 정책 우회 헤더 구현**
- `Access-Control-Allow-Origin: *`
- `Cross-Origin-Embedder-Policy: unsafe-none`
- `Cross-Origin-Opener-Policy: unsafe-none` 
- `Cross-Origin-Resource-Policy: cross-origin`
- `X-Frame-Options: ALLOWALL`
- 포괄적인 `Content-Security-Policy` 설정

**3. MQTT 기능 개선**
- MQTT 토픽을 `{unique_id}/CV/com`으로 변경 (기존: `/move`)
- JSON 명령 파싱 지원: `{"move":"up"}`, `{"move":"down"}`, `{"move":"left"}`, `{"move":"right"}`
- 모바일 URL 게시로 변경 (`/stream` → `/mobile`)
- 시리얼 포트 통신을 통한 카메라 움직임 제어

**4. 모바일 페이지 최적화**
- 온스크린 화살표 제어 버튼 완전 제거
- MQTT 전용 제어로 단순화
- 관련 CSS 및 JavaScript 코드 정리
- 전체화면 버튼만 유지

#### 🔧 주요 기술적 변경사항:

**MQTT 토픽 구조:**
```
{unique_id}/CV/com    - 카메라 제어 명령 수신
{unique_id}/CV/gst    - 스트림 URL 정보 게시  
{unique_id}/CV/sta    - 상태 및 하트비트 전송
{unique_id}/CV/obj    - 객체 감지 정보 전송
```

**JSON 명령 형식:**
```json
{"move":"up"}      - 위로 이동
{"move":"down"}    - 아래로 이동  
{"move":"left"}    - 왼쪽으로 이동
{"move":"right"}   - 오른쪽으로 이동
```

**새로운 URL 구조:**
- 스트림: `http://spcwtech.mooo.com:7200/stream`
- 모바일: `http://spcwtech.mooo.com:7200/mobile` 
- 기본 뷰어: `http://spcwtech.mooo.com:7200/`

#### 📱 모바일 페이지 기능:

- **전체화면 지원**: 터치로 자동 전체화면 진입
- **Wake Lock**: 화면 꺼짐 방지
- **터치 최적화**: 불필요한 터치 이벤트 차단
- **연결 상태 표시**: 실시간 스트림 연결 상태 모니터링
- **자동 재연결**: 연결 실패 시 3초 후 자동 재시도

#### 🔒 보안 개선사항:

- 모든 HTTP 응답에 CORS 우회 헤더 적용
- 임베딩 및 크로스 오리진 정책 완화
- 콘텐츠 보안 정책 설정으로 모든 리소스 허용

#### 🎯 다음 단계:
- [ ] 실제 하드웨어에서 MQTT 기능 테스트
- [ ] 추가적인 모바일 최적화
- [ ] 성능 모니터링 및 최적화

---
