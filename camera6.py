import cv2
import gi
import os
import serial
import threading
import sys
import termios
import tty
import time
import select
import numpy as np
import json
import uuid
import traceback
import paho.mqtt.client as mqtt
import hashlib
import subprocess
import time
import cv2
import gi
import os
import serial
import threading
import sys
import termios
import tty
import time
import select
import numpy as np
import json
import uuid
import traceback
import paho.mqtt.client as mqtt
import hashlib
import subprocess
import time
from rknnlite.api import RKNNLite as RKNN
import psutil
import gc
import psutil
import gc

# pynput은 GUI 환경에서만 사용 가능하므로 조건부 import
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    print("⚠️  pynput을 사용할 수 없습니다 (headless 환경). 키보드 제어는 비활성화됩니다.")
    PYNPUT_AVAILABLE = False

# HTTP 서버를 위한 import 추가
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
from urllib.parse import urlparse

# ByteTrack 트래킹을 위한 간단한 구현
class ByteTracker:
    def __init__(self, track_thresh=0.5, track_buffer=30, match_thresh=0.8):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.tracked_tracks = []
        self.lost_tracks = []
        self.frame_id = 0
        self.next_id = 1
        
    def update(self, detections):
        """ByteTrack 알고리즘으로 트래킹 업데이트"""
        self.frame_id += 1
        
        # 감지된 객체가 없으면 모든 트랙을 lost로 이동
        if len(detections) == 0:
            self.lost_tracks.extend(self.tracked_tracks)
            self.tracked_tracks = []
            return []
        
        # 현재 프레임의 트랙 예측
        for track in self.tracked_tracks:
            track['age'] += 1
            track['time_since_update'] += 1
        
        # 높은 신뢰도와 낮은 신뢰도 감지 분리
        high_conf_dets = [d for d in detections if d['confidence'] > self.track_thresh]
        low_conf_dets = [d for d in detections if d['confidence'] <= self.track_thresh]
        
        # 첫 번째 단계: 높은 신뢰도 감지와 기존 트랙 매칭
        matches, unmatched_tracks, unmatched_detections = self._match_detections_to_tracks(
            high_conf_dets, self.tracked_tracks
        )
        
        # 매칭된 트랙 업데이트
        for track_idx, det_idx in matches:
            self.tracked_tracks[track_idx].update(detections[det_idx])
            self.tracked_tracks[track_idx]['time_since_update'] = 0
        
        # 두 번째 단계: 낮은 신뢰도 감지와 unmatched 트랙 매칭
        if len(low_conf_dets) > 0 and len(unmatched_tracks) > 0:
            low_matches, _, _ = self._match_detections_to_tracks(
                low_conf_dets, [self.tracked_tracks[i] for i in unmatched_tracks]
            )
            for track_idx, det_idx in low_matches:
                actual_track_idx = unmatched_tracks[track_idx]
                self.tracked_tracks[actual_track_idx].update(detections[det_idx])
                self.tracked_tracks[actual_track_idx]['time_since_update'] = 0
        
        # 새로운 트랙 생성 (높은 신뢰도 감지만)
        for det_idx in unmatched_detections:
            if detections[det_idx]['confidence'] > self.track_thresh:
                new_track = {
                    'id': self.next_id,
                    'bbox': detections[det_idx]['bbox'],
                    'confidence': detections[det_idx]['confidence'],
                    'class_id': detections[det_idx]['class_id'],
                    'age': 1,
                    'time_since_update': 0,
                    'update': lambda det: self._update_track(new_track, det)
                }
                self.tracked_tracks.append(new_track)
                self.next_id += 1
        
        # 오래된 트랙 제거
        self.tracked_tracks = [t for t in self.tracked_tracks 
                              if t['time_since_update'] < self.track_buffer]
        
        return self.tracked_tracks
    
    def _match_detections_to_tracks(self, detections, tracks):
        """IOU 기반 매칭"""
        if len(tracks) == 0:
            return [], [], list(range(len(detections)))
        if len(detections) == 0:
            return [], list(range(len(tracks))), []
        
        # IOU 매트릭스 계산
        iou_matrix = np.zeros((len(tracks), len(detections)))
        for i, track in enumerate(tracks):
            for j, det in enumerate(detections):
                iou_matrix[i, j] = self._calculate_iou(track['bbox'], det['bbox'])
        
        # 헝가리안 알고리즘으로 매칭
        from scipy.optimize import linear_sum_assignment
        track_indices, det_indices = linear_sum_assignment(-iou_matrix)
        
        matches = []
        unmatched_tracks = []
        unmatched_detections = []
        
        for i in range(len(tracks)):
            if i in track_indices:
                det_idx = det_indices[track_indices == i][0]
                if iou_matrix[i, det_idx] >= self.match_thresh:
                    matches.append((i, det_idx))
                else:
                    unmatched_tracks.append(i)
            else:
                unmatched_tracks.append(i)
        
        for j in range(len(detections)):
            if j not in det_indices:
                unmatched_detections.append(j)
        
        return matches, unmatched_tracks, unmatched_detections
    
    def _calculate_iou(self, bbox1, bbox2):
        """두 바운딩 박스의 IOU 계산"""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2
        
        # 교집합 영역 계산
        x_left = max(x1, x2)
        y_top = max(y1, y2)
        x_right = min(x1 + w1, x2 + w2)
        y_bottom = min(y1 + h1, y2 + h2)
        
        if x_right < x_left or y_bottom < y_top:
            return 0.0
        
        intersection = (x_right - x_left) * (y_bottom - y_top)
        union = w1 * h1 + w2 * h2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def _update_track(self, track, detection):
        """트랙 정보 업데이트"""
        track['bbox'] = detection['bbox']
        track['confidence'] = detection['confidence']
        track['class_id'] = detection['class_id']

def test_camera_device(device_path):
    """Test if a camera device is working"""
    try:
        cap = cv2.VideoCapture(device_path)
        if not cap.isOpened():
            return False
        ret, frame = cap.read()
        cap.release()
        return ret and frame is not None
    except:
        return False

class MQTTClient:
    def __init__(self, broker_host='127.0.0.1', broker_port=1883, topic_prefix='camera', gst_server=None):
        """MQTT 클라이언트 초기화"""
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic_prefix = topic_prefix
        self.unique_id = self._generate_fixed_device_id()  # 고정된 디바이스 ID 생성
        self.client = mqtt.Client()
        self.gst_server = gst_server  # GStreamer 서버 참조
        
        # MQTT 이벤트 핸들러 설정
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_publish = self.on_publish
        self.client.on_message = self.on_message
        
        self.connected = False
        
        # 카메라 이동 콜백 함수 (외부에서 설정)
        self.move_callback = None
        
        print(f"MQTT 클라이언트 초기화 - Unique ID: {self.unique_id}")
    
    def on_connect(self, client, userdata, flags, rc):
        """MQTT 브로커 연결 콜백"""
        print(f"MQTT 연결 콜백 호출됨 - 코드: {rc}")
        if rc == 0:
            self.connected = True
            print(f"✓ MQTT 브로커에 연결됨 ({self.broker_host}:{self.broker_port})")
            print(f"✓ 고정 디바이스 ID: {self.unique_id}")
            
            # 카메라 이동 명령 구독
            move_topic = f"{self.unique_id}/CV/com"
            result = self.client.subscribe(move_topic)
            print(f"✓ 카메라 이동 명령 구독: {move_topic} (결과: {result})")
            
            # 연결 시 GStreamer 정보 전송
            print("초기 메시지 전송 중...")
            self.send_gst_info()
            # 상태 전송
            self.send_status("start")  # 시작 시에는 "start" 상태
        else:
            print(f"✗ MQTT 연결 실패 - 코드: {rc}")
            if rc == 1:
                print("  - 잘못된 프로토콜 버전")
            elif rc == 2:
                print("  - 클라이언트 ID 거부됨")
            elif rc == 3:
                print("  - 서버 사용 불가")
            elif rc == 4:
                print("  - 잘못된 사용자명 또는 비밀번호")
            elif rc == 5:
                print("  - 인증되지 않음")
            else:
                print(f"  - 알 수 없는 오류: {rc}")
    
    def on_disconnect(self, client, userdata, rc):
        """MQTT 브로커 연결 해제 콜백"""
        self.connected = False
        print("MQTT 브로커 연결 해제됨")
    
    def on_publish(self, client, userdata, mid):
        """메시지 발행 완료 콜백"""
        print(f"MQTT 메시지 발행 완료 - MID: {mid}")
    
    def on_message(self, client, userdata, msg):
        """MQTT 메시지 수신 콜백"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            
            print(f"MQTT 메시지 수신 - Topic: {topic}, Payload: {payload}")
            
            # 카메라 이동 명령 처리
            if topic.endswith('/CV/com') and self.move_callback:
                # JSON 형태의 명령 파싱 시도
                try:
                    import json
                    command_data = json.loads(payload)
                    if isinstance(command_data, dict) and 'move' in command_data:
                        move_command = command_data['move']
                        print(f"JSON 명령 파싱: {move_command}")
                        self.move_callback(move_command)
                    else:
                        # 일반 문자열 명령 처리
                        self.move_callback(payload)
                except json.JSONDecodeError:
                    # JSON이 아닌 경우 일반 문자열로 처리
                    print(f"일반 문자열 명령: {payload}")
                    self.move_callback(payload)
                
        except Exception as e:
            print(f"메시지 처리 오류: {e}")
            traceback.print_exc()
    
    def set_move_callback(self, callback):
        """카메라 이동 콜백 함수 설정"""
        self.move_callback = callback
    
    def connect(self):
        """MQTT 브로커에 연결"""
        try:
            print(f"MQTT 브로커 연결 시도: {self.broker_host}:{self.broker_port}")
            self.client.connect(self.broker_host, self.broker_port, 60)
            self.client.loop_start()
            
            # 연결이 완료될 때까지 대기 (최대 10초)
            connect_timeout = 10
            for i in range(connect_timeout):
                if self.connected:
                    print("MQTT 연결 성공!")
                    # 하트비트 스레드 시작
                    self.start_heartbeat()
                    return True
                time.sleep(1)
                print(f"MQTT 연결 대기 중... ({i+1}/{connect_timeout})")
            
            print("MQTT 연결 타임아웃")
            return False
        except Exception as e:
            print(f"MQTT 연결 실패: {e}")
            return False
    
    def start_heartbeat(self):
        """하트비트, 상태, GStreamer 정보 전송 스레드 시작"""
        def heartbeat_thread():
            sta_counter = 0  # 상태 전송 카운터
            gst_counter = 0  # GStreamer 정보 전송 카운터
            print("하트비트 스레드 시작 - 첫 번째 전송 대기 중...")
            
            while True:  # self.connected 대신 무한 루프 사용
                try:
                    # 연결 상태 확인
                    if not self.connected:
                        print("MQTT 연결이 끊어짐 - 하트비트 대기 중...")
                        time.sleep(5)
                        continue
                    
                    # 하트비트 "a" 전송 (5초마다)
                    print(f"하트비트 전송 시도... (연결상태: {self.connected})")
                    self.send_heartbeat()
                    
                    # 상태 "on" 전송 (5분마다 = 60번의 하트비트마다)
                    if sta_counter >= 60:
                        print("상태 전송 시도...")
                        self.send_status("on")
                        sta_counter = 0
                    else:
                        sta_counter += 1
                    
                    # GStreamer 정보 전송 (10초마다 = 2번의 하트비트마다)
                    if gst_counter >= 2:
                        print("GStreamer 정보 전송 시도...")
                        self.send_gst_info()
                        gst_counter = 0
                    else:
                        gst_counter += 1
                    
                    print(f"다음 하트비트까지 5초 대기... (상태: {sta_counter}/60, GST: {gst_counter}/2)")
                    time.sleep(5)  # 5초마다 하트비트 전송
                    
                except Exception as e:
                    print(f"하트비트/상태/GStreamer 전송 실패: {e}")
                    traceback.print_exc()
                    time.sleep(5)
            
        heartbeat_t = threading.Thread(target=heartbeat_thread, daemon=True)
        heartbeat_t.start()
        print("하트비트 및 상태 전송 스레드 시작됨")
    
    def disconnect(self):
        """MQTT 브로커 연결 해제"""
        if self.connected:
            self.client.loop_stop()
            self.client.disconnect()
    
    def send_gst_info(self):
        """HTTP 스트리밍 정보를 간단하게 전송 - URL만"""
        http_url = "http://spcwtech.mooo.com:7200/mobile"
        if self.gst_server:
            http_url = self.gst_server.get_mobile_url()
        
        # URL만 전송 (uniqueID는 토픽에 이미 포함되어 있음)
        message = http_url
        
        topic = f"{self.unique_id}/CV/gst"
        
        if self.connected:
            result = self.client.publish(topic, message)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"GStreamer 정보 전송 - Topic: {topic}")
            else:
                print(f"메시지 전송 실패 - 코드: {result.rc}")
    
    def send_heartbeat(self):
        """하트비트 전송 - uniqueID/CV/sta"""
        topic = f"{self.unique_id}/CV/sta"
        message = "a"  # 하트비트 상태
        
        if self.connected:
            result = self.client.publish(topic, message)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"하트비트 전송 - Topic: {topic}, Message: {message}")
            else:
                print(f"하트비트 전송 실패 - 코드: {result.rc}")
        else:
            print("MQTT 연결되지 않음 - 하트비트 전송 실패")
    
    def send_status(self, status):
        """상태 전송 - uniqueID/CV/sta"""
        topic = f"{self.unique_id}/CV/sta"
        
        if self.connected:
            result = self.client.publish(topic, status)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"상태 전송 - Topic: {topic}, Status: {status}")
            else:
                print(f"상태 전송 실패 - 코드: {result.rc}")
        else:
            print("MQTT 연결되지 않음 - 상태 전송 실패")
    
    def send_detection_data(self, detections_info):
        """감지된 객체 정보 전송 - uniqueID/CV/obj"""
        topic = f"{self.unique_id}/CV/obj"
        
        if self.connected and detections_info:
            message = json.dumps(detections_info)
            result = self.client.publish(topic, message)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"객체 감지 정보 전송 - Topic: {topic}, Objects: {len(detections_info)}")
            else:
                print(f"객체 감지 정보 전송 실패 - 코드: {result.rc}")
        else:
            if not self.connected:
                print("MQTT 연결되지 않음 - 객체 감지 정보 전송 실패")

    def _generate_fixed_device_id(self):
        """MAC 주소와 시스템 정보를 기반으로 고정된 디바이스 ID 생성"""
        try:
            # MAC 주소 가져오기
            import subprocess
            result = subprocess.run(['cat', '/sys/class/net/eth0/address'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                mac_address = result.stdout.strip()
            else:
                # eth0가 없으면 다른 인터페이스 시도
                result = subprocess.run(['ls', '/sys/class/net/'], 
                                      capture_output=True, text=True)
                interfaces = result.stdout.strip().split('\n')
                mac_address = "unknown"
                for interface in interfaces:
                    if interface not in ['lo']:  # loopback 제외
                        try:
                            result = subprocess.run(['cat', f'/sys/class/net/{interface}/address'], 
                                                  capture_output=True, text=True)
                            if result.returncode == 0:
                                mac_address = result.stdout.strip()
                                break
                        except:
                            continue
            
            # 시스템 정보 추가 (더 고유하게 만들기 위해)
            hostname_result = subprocess.run(['hostname'], capture_output=True, text=True)
            hostname = hostname_result.stdout.strip() if hostname_result.returncode == 0 else "unknown"
            
            # MAC 주소와 호스트명을 조합하여 해시 생성
            unique_string = f"{mac_address}-{hostname}-camera5"
            device_id = hashlib.md5(unique_string.encode()).hexdigest()[:8]
            
            return f"CAM_{device_id}"
            
        except Exception as e:
            print(f"고정 ID 생성 실패, 기본값 사용: {e}")
            # 실패 시 기본값 반환
            return "CAM_DEFAULT"

class MJPEGHTTPServer:
    def __init__(self, port=7200, host='0.0.0.0'):
        """MJPEG HTTP 서버 초기화"""
        self.port = port
        self.host = host
        self.server = None
        self.running = False
        self.frame_queue = []
        self.max_queue_size = 2
        self.lock = threading.Lock()
        
        print(f"MJPEG HTTP 서버 초기화 - Host: {host}, Port: {port}")
    
    class MJPEGHandler(BaseHTTPRequestHandler):
        def __init__(self, mjpeg_server, *args, **kwargs):
            self.mjpeg_server = mjpeg_server
            super().__init__(*args, **kwargs)
        
        def do_GET(self):
            if self.path == '/stream':
                self.send_mjpeg_stream()
            elif self.path == '/mobile':
                self.send_mobile_page()
            elif self.path == '/':
                self.send_index_page()
            else:
                self.send_error(404)
        
        def send_index_page(self):
            """간단한 뷰어 페이지"""
            html = f'''
            <!DOCTYPE html>
            <html>
            <head>
                <title>MJPEG Stream</title>
                <style>
                    body {{ margin: 0; padding: 20px; text-align: center; background: #000; }}
                    img {{ max-width: 100%; height: auto; border: 2px solid #fff; }}
                    h1 {{ color: white; }}
                </style>
            </head>
            <body>
                <h1>🚀 Camera Stream</h1>
                <img src="/stream" alt="Live Stream" />
                <p style="color: white;">실시간 MJPEG 스트리밍</p>
            </body>
            </html>
            '''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.send_header('Cross-Origin-Embedder-Policy', 'unsafe-none')
            self.send_header('Cross-Origin-Opener-Policy', 'unsafe-none')
            self.send_header('Cross-Origin-Resource-Policy', 'cross-origin')
            self.end_headers()
            self.wfile.write(html.encode())
        
        def send_mobile_page(self):
            """모바일 전용 뷰어 페이지 (전체화면, 터치 제스처 지원)"""
            html = '''
            <!DOCTYPE html>
            <html lang="ko">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
                <title>모바일 카메라 스트림</title>
                <style>
                    * {
                        margin: 0;
                        padding: 0;
                        box-sizing: border-box;
                    }
                    
                    body {
                        background: #000;
                        overflow: hidden;
                        touch-action: manipulation;
                        -webkit-user-select: none;
                        -moz-user-select: none;
                        -ms-user-select: none;
                        user-select: none;
                    }
                    
                    .container {
                        width: 100vw;
                        height: 100vh;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        position: relative;
                    }
                    
                    .video-container {
                        width: 100%;
                        height: 100%;
                        position: relative;
                        overflow: hidden;
                    }
                    
                    #stream {
                        width: 100%;
                        height: 100%;
                        object-fit: cover;
                        display: block;
                    }
                    

                    .status {
                        position: absolute;
                        top: 10px;
                        left: 10px;
                        color: white;
                        background: rgba(0, 0, 0, 0.5);
                        padding: 5px 10px;
                        border-radius: 5px;
                        font-size: 12px;
                        z-index: 100;
                    }
                    
                    .fullscreen-btn {
                        position: absolute;
                        top: 10px;
                        right: 10px;
                        width: 40px;
                        height: 40px;
                        background: rgba(255, 255, 255, 0.2);
                        border: 1px solid rgba(255, 255, 255, 0.5);
                        border-radius: 5px;
                        color: white;
                        font-size: 16px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        cursor: pointer;
                        backdrop-filter: blur(10px);
                        -webkit-backdrop-filter: blur(10px);
                        z-index: 100;
                    }
                    
                    @media (orientation: landscape) {
                        .fullscreen-btn {
                            top: 10px;
                            right: 10px;
                        }
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="video-container">
                        <img id="stream" src="/stream" alt="Live Stream" />
                        
                        <div class="status" id="status">
                            연결 중...
                        </div>
                        
                        <button class="fullscreen-btn" onclick="toggleFullscreen()">
                            ⛶
                        </button>
                        

                    </div>
                </div>
                
                <script>
                    // 화면 깨우기 방지
                    let wakeLock = null;
                    
                    // 전체화면 관련
                    function toggleFullscreen() {
                        if (!document.fullscreenElement) {
                            document.documentElement.requestFullscreen().catch(e => {
                                console.log('전체화면 요청 실패:', e);
                            });
                        } else {
                            document.exitFullscreen();
                        }
                    }
                    
                    // 스트림 상태 확인
                    const streamImg = document.getElementById('stream');
                    const status = document.getElementById('status');
                    
                    streamImg.onload = function() {
                        status.textContent = '스트림 연결됨';
                        status.style.background = 'rgba(0, 128, 0, 0.7)';
                    };
                    
                    streamImg.onerror = function() {
                        status.textContent = '스트림 연결 실패';
                        status.style.background = 'rgba(128, 0, 0, 0.7)';
                        
                        // 3초 후 재시도
                        setTimeout(() => {
                            streamImg.src = '/stream?' + Date.now();
                        }, 3000);
                    };
                    
                    // MQTT 명령은 서버 측에서 처리됨
                    
                    // 화면 깨우기 방지 시도
                    async function requestWakeLock() {
                        try {
                            if ('wakeLock' in navigator) {
                                wakeLock = await navigator.wakeLock.request('screen');
                                console.log('화면 깨우기 방지 활성화');
                            }
                        } catch (e) {
                            console.log('화면 깨우기 방지 실패:', e);
                        }
                    }
                    
                    // 페이지 로드 시 실행
                    window.addEventListener('load', () => {
                        requestWakeLock();
                        
                        // 터치 이벤트 방지 (기본 동작 차단)
                        document.addEventListener('touchstart', (e) => {
                            if (!e.target.classList.contains('fullscreen-btn')) {
                                e.preventDefault();
                            }
                        }, { passive: false });
                        
                        document.addEventListener('touchmove', (e) => {
                            e.preventDefault();
                        }, { passive: false });
                        
                        // 자동 전체화면 (사용자 제스처 후)
                        document.addEventListener('touchstart', function autoFullscreen() {
                            document.documentElement.requestFullscreen().catch(() => {});
                            document.removeEventListener('touchstart', autoFullscreen);
                        }, { once: true });
                    });
                    
                    // 페이지 가시성 변경 시 wake lock 재요청
                    document.addEventListener('visibilitychange', () => {
                        if (!document.hidden) {
                            requestWakeLock();
                        }
                    });
                </script>
            </body>
            </html>
            '''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.send_header('Cross-Origin-Embedder-Policy', 'unsafe-none')
            self.send_header('Cross-Origin-Opener-Policy', 'unsafe-none')
            self.send_header('Cross-Origin-Resource-Policy', 'cross-origin')
            self.send_header('X-Frame-Options', 'ALLOWALL')
            self.send_header('Content-Security-Policy', 'default-src * data: blob: filesystem: about: ws: wss: \'unsafe-inline\' \'unsafe-eval\'; script-src * data: blob: \'unsafe-inline\' \'unsafe-eval\'; connect-src * data: blob: \'unsafe-inline\'; img-src * data: blob: \'unsafe-inline\'; frame-src * data: blob:; style-src * data: blob: \'unsafe-inline\'; font-src * data: blob: \'unsafe-inline\';')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        
        def send_mjpeg_stream(self):
            """MJPEG 스트림 전송"""
            boundary = 'frame'
            self.send_response(200)
            self.send_header('Content-Type', f'multipart/x-mixed-replace; boundary={boundary}')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.send_header('Cross-Origin-Embedder-Policy', 'unsafe-none')
            self.send_header('Cross-Origin-Opener-Policy', 'unsafe-none')
            self.send_header('Cross-Origin-Resource-Policy', 'cross-origin')
            self.end_headers()
            
            try:
                while self.mjpeg_server.running:
                    frame = self.mjpeg_server.get_latest_frame()
                    if frame is not None:
                        # JPEG 인코딩
                        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                        _, jpeg = cv2.imencode('.jpg', frame, encode_param)
                        
                        # MJPEG 헤더 전송
                        self.wfile.write(f'--{boundary}\r\n'.encode())
                        self.wfile.write('Content-Type: image/jpeg\r\n'.encode())
                        self.wfile.write(f'Content-Length: {len(jpeg)}\r\n\r\n'.encode())
                        self.wfile.write(jpeg.tobytes())
                        self.wfile.write('\r\n'.encode())
                        self.wfile.flush()
                    
                    time.sleep(0.033)  # ~30fps
            except Exception as e:
                print(f"MJPEG 스트림 전송 오류: {e}")
        
        def log_message(self, format, *args):
            # 로그 메시지 억제
            pass
    
    def handler_factory(self):
        """핸들러 팩토리"""
        mjpeg_server = self
        class Handler(self.MJPEGHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(mjpeg_server, *args, **kwargs)
        return Handler
    
    def start_server(self):
        """HTTP 서버 시작"""
        try:
            self.server = HTTPServer((self.host, self.port), self.handler_factory())
            self.running = True
            
            # 서버를 별도 스레드에서 실행
            def serve_forever():
                try:
                    self.server.serve_forever()
                except Exception as e:
                    print(f"HTTP 서버 오류: {e}")
            
            self.server_thread = threading.Thread(target=serve_forever, daemon=True)
            self.server_thread.start()
            
            print(f"✓ MJPEG HTTP 서버 시작됨 - http://spcwtech.mooo.com:{self.port}")
            print(f"  스트림 URL: http://spcwtech.mooo.com:{self.port}/stream")
            print(f"  모바일 URL: http://spcwtech.mooo.com:{self.port}/mobile")
            print(f"  뷰어 URL: http://spcwtech.mooo.com:{self.port}/")
            return True
            
        except Exception as e:
            print(f"HTTP 서버 시작 실패: {e}")
            traceback.print_exc()
            return False
    
    def push_frame(self, frame):
        """프레임을 큐에 추가"""
        try:
            if not self.running or frame is None:
                return False
            
            with self.lock:
                # 큐 크기 제한
                if len(self.frame_queue) >= self.max_queue_size:
                    self.frame_queue.pop(0)  # 오래된 프레임 제거
                
                self.frame_queue.append(frame.copy())
            
            return True
                
        except Exception as e:
            print(f"프레임 푸시 오류: {e}")
            return False
    
    def get_latest_frame(self):
        """최신 프레임 가져오기"""
        try:
            with self.lock:
                if self.frame_queue:
                    return self.frame_queue[-1]  # 최신 프레임
                return None
        except Exception as e:
            print(f"프레임 가져오기 오류: {e}")
            return None
    
    def stop_server(self):
        """HTTP 서버 중지"""
        if self.running:
            self.running = False
            print("MJPEG HTTP 서버 중지 시작...")
            
            if self.server:
                try:
                    self.server.shutdown()
                    self.server.server_close()
                    print("✓ HTTP 서버 종료 완료")
                except Exception as e:
                    print(f"HTTP 서버 종료 오류: {e}")
            
            # 큐 정리
            with self.lock:
                self.frame_queue.clear()
                    
            print("✓ MJPEG HTTP 서버 중지 완료")
    
    def get_rtsp_url(self):
        """호환성을 위한 URL 반환 (실제로는 HTTP URL)"""
        return f"http://spcwtech.mooo.com:{self.port}/stream"
    
    def get_mobile_url(self):
        """모바일 페이지 URL 반환"""
        return f"http://spcwtech.mooo.com:{self.port}/mobile"

class KeyboardController:
    def __init__(self, serial_port=None, baudrate=115200):
        try:
            if isinstance(serial_port, str):
                # 시리얼 포트 경로가 문자열로 주어진 경우
                self.ser = serial.Serial(serial_port, baudrate, timeout=1)
            elif hasattr(serial_port, 'write'):
                # 이미 초기화된 시리얼 포트 객체가 주어진 경우
                self.ser = serial_port
            else:
                # 기본 포트 시도
                self.ser = serial.Serial('/dev/ttyS3', baudrate, timeout=1)
            self.running = True
        except Exception as e:
            print(f"키보드 컨트롤러 시리얼 포트 초기화 실패: {e}")
            self.ser = None
            self.running = False
        
        self.interrupt_flag = False

    def on_press(self, key):
        if not PYNPUT_AVAILABLE:
            return True
            
        try:
            command = None
            
            if hasattr(key, 'char'):
                if key.char == 'w':
                    command = 'up'
                elif key.char == 's':
                    command = 'down'
                elif key.char == 'a':
                    command = 'left'
                elif key.char == 'd':
                    command = 'right'
                elif key.char == 'q':
                    self.running = False
                    self.interrupt_flag = True
                    return False
            elif PYNPUT_AVAILABLE and hasattr(keyboard, 'Key') and key == keyboard.Key.esc:
                self.running = False
                self.interrupt_flag = True
                return False
                
            if command and self.ser and self.ser.is_open:
                try:
                    self.ser.write(f"{command}\n".encode())
                except Exception as e:
                    pass
                
        except Exception as e:
            traceback.print_exc()
            
        return True

    def start(self):
        if not PYNPUT_AVAILABLE:
            print("\n⚠️  키보드 컨트롤 비활성화 (headless 환경)")
            print("MQTT를 통한 원격 제어만 사용 가능합니다.")
            return
            
        print("\n키보드 컨트롤 시작")
        print("WASD 키를 사용하여 제어하세요:")
        print("W - 위로 이동")
        print("A - 왼쪽으로 이동")
        print("S - 아래로 이동")
        print("D - 오른쪽으로 이동")
        print("종료: Q 또는 ESC")
        
        self.keyboard_thread = threading.Thread(target=self._keyboard_listener)
        self.keyboard_thread.daemon = True
        self.keyboard_thread.start()

    def _keyboard_listener(self):
        try:
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            
            try:
                tty.setraw(fd)
                
                while self.running and not self.interrupt_flag:
                    r, w, e = select.select([sys.stdin], [], [], 0.1)
                    if r:
                        key = sys.stdin.read(1)
                        
                        if not self._process_key(key):
                            break
                            
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                
        except Exception as e:
            traceback.print_exc()
            self.interrupt_flag = True

    def _process_key(self, key):
        try:
            command = None
            
            if key == '\x1b':  # ESC 키
                next1 = sys.stdin.read(1)
                if next1 == '[':
                    next2 = sys.stdin.read(1)
                    
                    if next2 == 'A':  # 위쪽 화살표
                        command = 'up'
                    elif next2 == 'B':  # 아래쪽 화살표
                        command = 'down'
                    elif next2 == 'D':  # 왼쪽 화살표
                        command = 'left'
                    elif next2 == 'C':  # 오른쪽 화살표
                        command = 'right'
                else:
                    self.running = False
                    self.interrupt_flag = True
                    return False
            
            elif key == 'q':
                self.running = False
                self.interrupt_flag = True
                return False
            
            if command and self.ser and self.ser.is_open:
                try:
                    self.ser.write(f"{command}\n".encode())
                except Exception as e:
                    pass
            
            return True
        
        except Exception as e:
            traceback.print_exc()
            return True

    def stop(self):
        print("키보드 컨트롤러 종료 중...")
        self.running = False
        # 시리얼 포트는 다른 컴포넌트와 공유할 수 있으므로 닫지 않음
        # 주 프로그램에서 정리됨

class ByteTracker:
    def __init__(self, track_thresh=0.5, track_buffer=30, match_thresh=0.8):
        self.track_thresh = track_thresh
        self.track_buffer = track_buffer
        self.match_thresh = match_thresh
        self.tracked_tracks = []
        self.lost_tracks = []
        self.frame_id = 0
        self.next_id = 1
        self.color_map = {}  # 트랙 ID -> 색상 딕셔너리
        
    def update(self, detections):
        """ByteTrack 알고리즘으로 트래킹 업데이트"""
        self.frame_id += 1
        
        # 감지된 객체가 없으면 모든 트랙을 lost로 이동
        if len(detections) == 0:
            self.lost_tracks.extend(self.tracked_tracks)
            self.tracked_tracks = []
            return []
        
        # 현재 프레임의 트랙 예측
        for track in self.tracked_tracks:
            track['age'] += 1
            track['time_since_update'] += 1
        
        # 높은 신뢰도와 낮은 신뢰도 감지 분리
        high_conf_dets = [d for d in detections if d['confidence'] > self.track_thresh]
        low_conf_dets = [d for d in detections if d['confidence'] <= self.track_thresh]
        
        # 첫 번째 단계: 높은 신뢰도 감지와 기존 트랙 매칭
        matches, unmatched_tracks, unmatched_detections = self._match_detections_to_tracks(
            high_conf_dets, self.tracked_tracks
        )
        
        # 매칭된 트랙 업데이트
        for track_idx, det_idx in matches:
            self.tracked_tracks[track_idx].update(detections[det_idx])
            self.tracked_tracks[track_idx]['time_since_update'] = 0
        
        # 두 번째 단계: 낮은 신뢰도 감지와 unmatched 트랙 매칭
        if len(low_conf_dets) > 0 and len(unmatched_tracks) > 0:
            low_matches, _, _ = self._match_detections_to_tracks(
                low_conf_dets, [self.tracked_tracks[i] for i in unmatched_tracks]
            )
            for track_idx, det_idx in low_matches:
                actual_track_idx = unmatched_tracks[track_idx]
                self.tracked_tracks[actual_track_idx].update(detections[det_idx])
                self.tracked_tracks[actual_track_idx]['time_since_update'] = 0
        
        # 새로운 트랙 생성 (높은 신뢰도 감지만)
        for det_idx in unmatched_detections:
            if detections[det_idx]['confidence'] > self.track_thresh:
                new_track = {
                    'id': self.next_id,
                    'bbox': detections[det_idx]['bbox'],
                    'confidence': detections[det_idx]['confidence'],
                    'class_id': detections[det_idx]['class_id'],
                    'age': 1,
                    'time_since_update': 0,
                    'update': lambda det: self._update_track(new_track, det)
                }
                self.tracked_tracks.append(new_track)
                self.next_id += 1
        
        # 오래된 트랙 제거
        self.tracked_tracks = [t for t in self.tracked_tracks 
                              if t['time_since_update'] < self.track_buffer]
        
        return self.tracked_tracks
    
    def _match_detections_to_tracks(self, detections, tracks):
        """IOU 기반 매칭"""
        if len(tracks) == 0:
            return [], [], list(range(len(detections)))
        if len(detections) == 0:
            return [], list(range(len(tracks))), []
        
        # IOU 매트릭스 계산
        iou_matrix = np.zeros((len(tracks), len(detections)))
        for i, track in enumerate(tracks):
            for j, det in enumerate(detections):
                iou_matrix[i, j] = self._calculate_iou(track['bbox'], det['bbox'])
        
        # 헝가리안 알고리즘으로 매칭
        from scipy.optimize import linear_sum_assignment
        track_indices, det_indices = linear_sum_assignment(-iou_matrix)
        
        matches = []
        unmatched_tracks = []
        unmatched_detections = []
        
        for i in range(len(tracks)):
            if i in track_indices:
                det_idx = det_indices[track_indices == i][0]
                if iou_matrix[i, det_idx] >= self.match_thresh:
                    matches.append((i, det_idx))
                else:
                    unmatched_tracks.append(i)
            else:
                unmatched_tracks.append(i)
        
        for j in range(len(detections)):
            if j not in det_indices:
                unmatched_detections.append(j)
        
        return matches, unmatched_tracks, unmatched_detections
    
    def _calculate_iou(self, bbox1, bbox2):
        """두 바운딩 박스의 IOU 계산"""
        x1, y1, w1, h1 = bbox1
        x2, y2, w2, h2 = bbox2
        
        # 교집합 영역 계산
        x_left = max(x1, x2)
        y_top = max(y1, y2)
        x_right = min(x1 + w1, x2 + w2)
        y_bottom = min(y1 + h1, y2 + h2)
        
        if x_right < x_left or y_bottom < y_top:
            return 0.0
        
        intersection = (x_right - x_left) * (y_bottom - y_top)
        union = w1 * h1 + w2 * h2 - intersection
        
        return intersection / union if union > 0 else 0.0
    
    def _update_track(self, track, detection):
        """트랙 정보 업데이트"""
        track['bbox'] = detection['bbox']
        track['confidence'] = detection['confidence']
        track['class_id'] = detection['class_id']
    
    def draw_tracks(self, frame, tracks, class_names=None):
        """Draw tracking results on frame"""
        for track in tracks:
            bbox = track['bbox']
            track_id = track['id']
            class_id = track['class_id']
            confidence = track['confidence']
            
            # Get color for this track
            color = self.color_map.get(track_id, (0, 255, 0))
            
            # Draw bounding box
            x, y, w, h = bbox
            cv2.rectangle(frame, (int(x), int(y)), (int(x + w), int(y + h)), color, 2)
            
            # Draw track ID and class
            label = f"ID:{track_id}"
            if class_names and class_id < len(class_names):
                label += f" {class_names[class_id]}"
            label += f" {confidence:.2f}"
            
            # Draw label background
            (label_width, label_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(frame, (int(x), int(y) - label_height - 10), 
                         (int(x) + label_width, int(y)), color, -1)
            
            # Draw label text
            cv2.putText(frame, label, (int(x), int(y) - 5), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

class RKNNDetector:
    def __init__(self, model_path='/home/spcwtech/yolo5n_fish-rk3566.rknn', 
                 mqtt_broker='127.0.0.1', mqtt_port=1883):
        self.rknn = RKNN()
        try:
            ret = self.rknn.load_rknn(model_path)
            if ret != 0:
                print('Load RKNN model failed')
                exit(ret)
                
            ret = self.rknn.init_runtime()
            if ret != 0:
                print('Init runtime environment failed')
                exit(ret)
        except Exception as e:
            traceback.print_exc()
            
        self.input_size = 640
        
        # 🚀 성능 최적화: DeepSORT 비활성화
        self.enable_deepsort = False  # DeepSORT 완전 비활성화
        if self.enable_deepsort:
            # Initialize DeepSORT tracker
            self.deep_sort = DeepSORTTracker()
            print("DeepSORT 트래커 초기화 완료")
        else:
            self.deep_sort = None
            print("🚀 성능 최적화: DeepSORT 비활성화됨")
        
        # 🚀 성능 최적화: 프레임 스킵 설정
        self.frame_skip = 3  # 매 3번째 프레임만 처리
        self.frame_counter = 0
        
        # Initialize GStreamer RTSP server
        self.gst_server = MJPEGHTTPServer(port=7200, host='0.0.0.0')
        self.gst_server.start_server()
        
        # Initialize MQTT client with GStreamer server reference
        self.mqtt_client = MQTTClient(
            broker_host=mqtt_broker, 
            broker_port=mqtt_port,
            gst_server=self.gst_server
        )
        
        # 카메라 이동 콜백 설정
        self.mqtt_client.set_move_callback(self.handle_move_command)
        self.mqtt_client.connect()
        
        # 시리얼 포트 (카메라 이동용)
        self.serial_port = None
        self.init_serial_port()
        
        try:
            with open("coco.names", "r") as f:
                self.classes = [line.strip() for line in f.readlines()]
        except FileNotFoundError:
            self.classes = [f"class_{i}" for i in range(80)]

        # Detection data tracking for MQTT
        self.detection_send_interval = 5.0  # 5초마다 전송
        self.last_mqtt_send = time.time()
        self.last_detections = []  # 최근 감지된 객체들

    def init_serial_port(self):
        """시리얼 포트 초기화 (카메라 이동용)"""
        serial_ports = ['/dev/ttyS3', '/dev/ttyS0', '/dev/ttyAMA0', '/dev/ttyUSB0']
        
        for port in serial_ports:
            try:
                self.serial_port = serial.Serial(port, 115200, timeout=1)
                if self.serial_port.is_open:
                    print(f"시리얼 포트 {port} 연결 성공!")
                    break
                else:
                    self.serial_port = None
            except Exception as e:
                self.serial_port = None
                continue
        
        if self.serial_port is None:
            print("사용 가능한 시리얼 포트를 찾을 수 없습니다.")

    def handle_move_command(self, command):
        """MQTT로 받은 카메라 이동 명령 처리"""
        try:
            print(f"카메라 이동 명령 수신: {command}")
            
            if self.serial_port and self.serial_port.is_open:
                # 명령어 매핑
                move_commands = {
                    "up": "up",
                    "down": "down", 
                    "left": "left",
                    "right": "right",
                    "stop": "stop"
                }
                
                if command in move_commands:
                    serial_command = f"{move_commands[command]}\n"
                    self.serial_port.write(serial_command.encode())
                    print(f"시리얼 명령 전송: {serial_command.strip()}")
                else:
                    print(f"알 수 없는 이동 명령: {command}")
            else:
                print("시리얼 포트가 연결되지 않음")
                
        except Exception as e:
            print(f"이동 명령 처리 오류: {e}")

    def decode_predictions(self, output, conf_thres=0.20, max_score=0.95):
        try:
            pred = output[0].squeeze().transpose(1, 0)
            boxes_raw = pred[:, :4]
            objectness = pred[:, 4] * 10
            class_probs = pred[:, 5:] * 2
            class_conf = np.max(class_probs, axis=1)
            class_ids = np.argmax(class_probs, axis=1)
            scores = objectness + class_conf 
            mask = (scores > conf_thres) & (scores <= max_score)
            boxes_xywh = boxes_raw[mask]
            scores_filtered = scores[mask]
            class_ids_filtered = class_ids[mask]
            
            if len(boxes_xywh) == 0:
                return np.array([])
            
            detections = np.column_stack([
                boxes_xywh,
                scores_filtered,
                class_ids_filtered
            ])
            
            return detections
        except Exception as e:
            return np.array([])

    def apply_nms(self, detections, iou_thres=0.35):
        try:
            if len(detections) == 0:
                return []
            
            boxes = detections[:, :4]
            scores = detections[:, 4]
            
            indices = cv2.dnn.NMSBoxes(
                boxes.tolist(), 
                scores.tolist(), 
                score_threshold=0.60,
                nms_threshold=iou_thres
            )
            
            if len(indices) == 0:
                return []
            
            if isinstance(indices, tuple):
                indices = indices[0]
            else:
                indices = indices.flatten()
                
            return detections[indices]
        except Exception as e:
            return []

    def letterbox(self, img, new_shape=(640, 640), color=(114, 114, 114)):
        """Resize and pad image while meeting stride-multiple constraints."""
        shape = img.shape[:2]  # current shape [height, width]
        
        # Scale ratio (new / old)
        r = min(new_shape[0] / shape[0], new_shape[1] / shape[1])
        
        # Compute new unpadded dimensions
        new_unpad = int(round(shape[1] * r)), int(round(shape[0] * r))
        
        # Compute padding
        dw, dh = new_shape[1] - new_unpad[0], new_shape[0] - new_unpad[1]
        
        # Divide padding into 2 sides
        dw /= 2
        dh /= 2
        
        # Resize
        if shape[::-1] != new_unpad:
            img = cv2.resize(img, new_unpad, interpolation=cv2.INTER_LINEAR)
            
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        
        # Add padding
        img = cv2.copyMakeBorder(img, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
        
        return img, r, (dw, dh)

    def detect(self, frame):
        try:
            if frame is None:
                return None

            # 🚀 성능 최적화: 프레임 스킵
            self.frame_counter += 1
            if self.frame_counter % self.frame_skip != 0:
                # 스킵되는 프레임은 원본 그대로 반환
                return frame

            # 성능 측정 시작
            total_detect_start = time.time()
            
            draw_frame = frame.copy()

            # 1. Letterbox 변환 시간 측정
            letterbox_start = time.time()
            img, ratio, pad = self.letterbox(frame, new_shape=(self.input_size, self.input_size))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = np.expand_dims(img, axis=0)
            letterbox_time = time.time() - letterbox_start

            # 2. RKNN 추론 시간 측정
            inference_start = time.time()
            try:
                outputs = self.rknn.inference(inputs=[img])
            except KeyboardInterrupt:
                return draw_frame
            except Exception as e:
                print(f"RKNN 추론 오류: {e}")
                return draw_frame
            inference_time = time.time() - inference_start

            # 3. 후처리 (디코딩 + NMS) 시간 측정 - 🚀 더 높은 임계값으로 최적화
            postprocess_start = time.time()
            detections = self.decode_predictions(outputs, conf_thres=0.4, max_score=0.95)  # 신뢰도 높임
            detections = self.apply_nms(detections, iou_thres=0.5)  # NMS 임계값 높임
            postprocess_time = time.time() - postprocess_start
            
            # 4. 좌표 변환 시간 측정
            coord_transform_start = time.time()
            processed_detections = []
            for det in detections:
                x, y, w, h, score, class_id = det
                # 패딩 제거 후 원본 크기로 복원
                x = (x - pad[0]) / ratio
                y = (y - pad[1]) / ratio
                w = w / ratio
                h = h / ratio
                processed_detections.append([x, y, w, h, score, class_id])
            coord_transform_time = time.time() - coord_transform_start
            
            # 5. 🚀 ByteTrack 트래킹 적용
            tracking_start = time.time()
            if not hasattr(self, 'byte_tracker'):
                self.byte_tracker = ByteTracker()
            # ByteTrack 입력 포맷: [{bbox, confidence, class_id} ...]
            byte_detections = []
            for det in processed_detections:
                x, y, w, h, score, class_id = det
                bbox = [x - w/2, y - h/2, w, h]  # 좌상단 x, y, w, h
                byte_detections.append({
                    'bbox': bbox,
                    'confidence': score,
                    'class_id': int(class_id)
                })
            tracks = self.byte_tracker.update(byte_detections)
            draw_frame = self.byte_tracker.draw_tracks(draw_frame, tracks, self.classes)
            tracking_time = time.time() - tracking_start
            
            # 6. 그리기 시간 측정 (이미 위에서 처리됨)
            drawing_time = 0
            
            # 7. MQTT 전송 (필요시) - 🚀 전송 간격 늘림
            mqtt_start = time.time()
            current_time = time.time()
            if current_time - self.last_mqtt_send >= self.detection_send_interval * 2:  # 전송 간격 2배로
                if self.enable_deepsort and tracks:
                    self.send_tracked_objects_to_mqtt(tracks)
                self.last_mqtt_send = current_time
            mqtt_time = time.time() - mqtt_start
            
            total_detect_time = time.time() - total_detect_start
            
            # 성능 정보 저장 (클래스 변수로)
            if not hasattr(self, 'performance_stats'):
                self.performance_stats = {
                    'letterbox': [],
                    'inference': [],
                    'postprocess': [],
                    'tracking': [],
                    'drawing': [],
                    'total': []
                }
            
            self.performance_stats['letterbox'].append(letterbox_time * 1000)
            self.performance_stats['inference'].append(inference_time * 1000)
            self.performance_stats['postprocess'].append(postprocess_time * 1000)
            self.performance_stats['tracking'].append(tracking_time * 1000)
            self.performance_stats['drawing'].append(drawing_time * 1000)
            self.performance_stats['total'].append(total_detect_time * 1000)
            
            # 최대 100개 기록 유지
            for key in self.performance_stats:
                if len(self.performance_stats[key]) > 100:
                    self.performance_stats[key] = self.performance_stats[key][-100:]
            
            # 🚀 성능 로그 간격 늘림 (20프레임마다)
            if hasattr(self, 'frame_counter_log'):
                self.frame_counter_log += 1
            else:
                self.frame_counter_log = 1
                
            if self.frame_counter_log % 20 == 0:
                print(f"\n=== 🚀 최적화된 RKNN 성능 분석 ===")
                print(f"감지된 객체: {len(processed_detections)}, 프레임 스킵: 매 {self.frame_skip}번째")
                print(f"DeepSORT: {'활성화' if self.enable_deepsort else '비활성화 (성능 최적화)'}")
                for key, values in self.performance_stats.items():
                    if values:
                        avg_time = sum(values[-10:]) / min(10, len(values))
                        print(f"{key:12}: {avg_time:6.1f}ms")
                        
                        # 성능 경고
                        if key == 'inference' and avg_time > 300:
                            print(f"  ⚠️  RKNN 추론이 여전히 느림: {avg_time:.1f}ms")
                        elif key == 'total' and avg_time > 500:
                            print(f"  ⚠️  전체 처리가 여전히 느림: {avg_time:.1f}ms")
                        elif key == 'total' and avg_time < 100:
                            print(f"  ✅ 성능 개선됨: {avg_time:.1f}ms")
            
            return draw_frame

        except KeyboardInterrupt:
            return frame
        except Exception as e:
            print(f"detect 메소드 오류: {e}")
            traceback.print_exc()
            return frame 

    def send_tracked_objects_to_mqtt(self, tracks):
        """트래킹된 객체 정보를 MQTT로 전송"""
        try:
            if not tracks:
                print("전송할 트래킹 객체가 없음")
                return
            
            # 트래킹 데이터 준비
            detection_data = []
            for bbox, track_id, class_id in tracks:
                x1, y1, x2, y2 = bbox.astype(int)
                
                # 클래스 이름 가져오기
                class_name = self.classes[class_id] if class_id < len(self.classes) else f"class_{class_id}"
                
                obj_info = {
                    "track_id": int(track_id),
                    "class_id": int(class_id),
                    "class_name": class_name,
                    "bbox": {
                        "x1": int(x1),
                        "y1": int(y1), 
                        "x2": int(x2),
                        "y2": int(y2)
                    },
                    "center": {
                        "x": int((x1 + x2) / 2),
                        "y": int((y1 + y2) / 2)
                    }
                }
                detection_data.append(obj_info)
            
            # MQTT로 전송
            if detection_data:
                self.mqtt_client.send_detection_data(detection_data)
                print(f"MQTT 객체 정보 전송 완료: {len(detection_data)}개 객체")
            
        except Exception as e:
            print(f"MQTT 객체 정보 전송 실패: {e}")
            traceback.print_exc()

    def __del__(self):
        if hasattr(self, 'mqtt_client'):
            try:
                self.mqtt_client.send_status("off")
                self.mqtt_client.disconnect()
            except Exception as e:
                pass
        
        if hasattr(self, 'serial_port') and self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.close()
            except Exception as e:
                pass
        
        if hasattr(self, 'gst_server'):
            try:
                self.gst_server.stop_server()
            except Exception as e:
                pass
        
        if hasattr(self, 'rknn'):
            try:
                self.rknn.release()
            except Exception as e:
                pass

def find_working_camera():
    """Find the first working video device"""
    # Try mainpath devices first
    for i in range(12):
        device = f'/dev/video{i}'
        print(f"Testing {device}...")
        if test_camera_device(device):
            return device
    
    raise Exception("No working camera found")

# 안전한 종료를 위한 글로벌 플래그
program_running = True

def main():
    global program_running
    cap = None
    detector = None
    
    # 프로그램 시작 시 HTTP 서버 초기화
    print("MJPEG HTTP 서버 초기화 중...")
    # GStreamer 초기화는 더 이상 필요하지 않음
    
    # 설정 파일 로드
    config = {
        "mqtt": {
            "broker_host": os.getenv("MQTT_BROKER_HOST", "127.0.0.1"),
            "broker_port": int(os.getenv("MQTT_BROKER_PORT", "1883")),
            "topic_prefix": "camera"
        },
        "http": {
            "port": 7500,
            "host": "0.0.0.0"
        },
        "detection": {
            "model_path": "/home/spcwtech/yolo5n_fish-rk3566.rknn",
            "send_interval": 5.0
        }
    }
    
    try:
        with open("/home/spcwtech/config.json", "r") as f:
            config.update(json.load(f))
        print("설정 파일 로드 완료")
    except FileNotFoundError:
        print("설정 파일이 없습니다. 기본 설정을 사용합니다.")
    except Exception as e:
        print(f"설정 파일 로드 실패: {e}. 기본 설정을 사용합니다.")
    
    try:
        video_device = find_working_camera()
        print(f"Found working camera: {video_device}")

        # RKNN 디텍터 초기화
        try:
            detector = RKNNDetector(
                model_path=config["detection"]["model_path"],
                mqtt_broker=config["mqtt"]["broker_host"],
                mqtt_port=config["mqtt"]["broker_port"]
            )
            # MQTT로 시작 상태 전송
            detector.mqtt_client.send_status("start")
        except Exception as e:
            print(f"RKNN 디텍터 초기화 실패: {e}")
            raise
        
        # 마지막으로 카메라 초기화
        cap = cv2.VideoCapture(video_device)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 640)
        
        if not cap.isOpened():
            print(f"카메라 {video_device} 열기 실패")
            raise Exception("카메라를 열 수 없습니다")
        
        # Headless 모드 - OpenCV 창 생성하지 않음
        print("Headless 모드로 실행 중... (OpenCV 창 없음)")
        # GUI 없이 실행 (MJPEG HTTP 스트리밍만 사용)
        
        print("메인 루프 시작")
        program_running = True
        
        # 키보드 컨트롤러 초기화 및 시작 (MQTT와 공존)
        # 시리얼 포트를 detector와 공유
        keyboard_controller = None
        try:
            keyboard_controller = KeyboardController(serial_port=detector.serial_port)
            keyboard_controller.start()
            if PYNPUT_AVAILABLE:
                print("키보드 컨트롤과 MQTT 제어가 활성화되었습니다")
            else:
                print("MQTT 제어만 활성화되었습니다 (키보드 컨트롤 비활성화)")
        except Exception as e:
            print(f"키보드 컨트롤러 초기화 실패: {e}")
            print("MQTT 제어만 사용됩니다")
        
        # FPS 계산을 위한 변수들
        frame_count = 0
        loop_start_time = time.time()
        display_fps = 0

        while program_running:
            try:
                # 전체 프레임 처리 시작 시간
                total_frame_start = time.time()
                
                # 1. 프레임 캡처 시간 측정
                capture_start = time.time()
                ret, frame = cap.read()
                capture_time = time.time() - capture_start
                
                if not ret:
                    time.sleep(0.1)
                    continue

                # 2. 프레임 처리 (RKNN + DeepSORT)
                detect_start = time.time()
                processed_frame = detector.detect(frame)
                detect_time = time.time() - detect_start
                
                if processed_frame is None:
                    continue

                # 3. 프레임 카운트 증가
                frame_count += 1
                
                # 4. FPS 계산 (실제 경과 시간 기반)
                elapsed_time = time.time() - loop_start_time
                if elapsed_time > 0:
                    display_fps = frame_count / elapsed_time
                
                # 5. 프레임에 정확한 FPS 표시
                cv2.putText(processed_frame, f"FPS: {display_fps:.1f}", (10, 30), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                
                # 30프레임마다 간단한 성능 정보만 출력
                if frame_count % 30 == 0:
                    print(f"FPS: {display_fps:.1f}")
                    
                    # FPS 계산 리셋
                    loop_start_time = time.time()
                    frame_count = 0

                # 6. RTSP 스트리밍을 위해 프레임을 GStreamer로 전송
                if detector.gst_server.running:
                    try:
                        # 640x640으로 리사이즈 (필요시)
                        if processed_frame.shape[:2] != (640, 640):
                            stream_frame = cv2.resize(processed_frame, (640, 640))
                        else:
                            stream_frame = processed_frame.copy()
                        
                        # GStreamer 프레임 푸시
                        push_success = detector.gst_server.push_frame(stream_frame)
                        if not push_success and frame_count % 30 == 0:
                            print("GStreamer 프레임 푸시 실패")
                    except Exception as e:
                        print(f"RTSP 스트림 프레임 전송 실패: {e}")

            except KeyboardInterrupt:
                program_running = False
                break
            except Exception as e:
                traceback.print_exc()
                time.sleep(0.5)
                continue

    except KeyboardInterrupt:
        program_running = False
    except Exception as e:
        traceback.print_exc()
    finally:
        print("프로그램 종료 중...")
        program_running = False
        
        # 키보드 컨트롤러 종료
        if 'keyboard_controller' in locals() and keyboard_controller is not None:
            try:
                keyboard_controller.stop()
            except Exception as e:
                pass
        
        # 리소스 정리
        if cap and cap.isOpened():
            try:
                cap.release()
                print("카메라 리소스 해제 완료")
            except Exception as e:
                print(f"카메라 리소스 해제 오류: {e}")
        
        # Headless 모드 - OpenCV 창 정리 생략
        
        if detector:
            try:
                # MQTT로 종료 상태 전송
                detector.mqtt_client.send_status("stop")
                del detector
                print("디텍터 리소스 정리 완료")
            except Exception as e:
                print(f"디텍터 리소스 정리 오류: {e}")
        
        print("프로그램이 안전하게 종료되었습니다")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        traceback.print_exc()
    finally:
        print("프로그램 종료")