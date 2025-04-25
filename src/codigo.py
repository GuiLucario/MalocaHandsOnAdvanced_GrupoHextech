from flask import Flask, render_template, request, jsonify, Response
import os
import time
import threading
import cv2
import RPi.GPIO as GPIO
from datetime import datetime
from picamera2 import Picamera2
import libcamera
import socket

app = Flask(_name_)
app.config['UPLOAD_FOLDER'] = 'static/photos'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Configuração GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Pinos
SERVO_PIN = 13
TRIGGER_PIN = 24
ECHO_PIN = 23
PIR_PIN = 4

# Configuração dos pinos
GPIO.setup(SERVO_PIN, GPIO.OUT)
GPIO.setup(TRIGGER_PIN, GPIO.OUT)
GPIO.setup(ECHO_PIN, GPIO.IN)
GPIO.setup(PIR_PIN, GPIO.IN)
GPIO.output(TRIGGER_PIN, False)

# Variáveis globais
current_angle = 0
sensor_data = {'distance': 0.0, 'motion': False}

# Inicialização PWM
pwm = GPIO.PWM(SERVO_PIN, 50)
pwm.start(0)

# Configuração da câmera
picam2 = Picamera2()
preview_config = picam2.create_preview_configuration(
    main={"size": (640, 480)}
)
capture_config = picam2.create_still_configuration()
picam2.configure(preview_config)
picam2.start()

def move_servo(target_angle):
    global current_angle
    target_angle = max(0, min(target_angle, 90))
    if target_angle == current_angle:
        return
    step = 1 if target_angle > current_angle else -1
    for angle in range(current_angle, target_angle, step):
        duty = 2 + (angle / 18)
        pwm.ChangeDutyCycle(duty)
        time.sleep(0.02)
    duty = 2 + (target_angle / 18)
    pwm.ChangeDutyCycle(duty)
    time.sleep(0.1)
    pwm.ChangeDutyCycle(0)
    current_angle = target_angle

def get_distance():
    try:
        GPIO.output(TRIGGER_PIN, True)
        time.sleep(0.00001)
        GPIO.output(TRIGGER_PIN, False)

        start = time.time()
        stop = time.time()

        timeout = time.time() + 0.04
        while GPIO.input(ECHO_PIN) == 0 and time.time() < timeout:
            start = time.time()

        timeout = time.time() + 0.04
        while GPIO.input(ECHO_PIN) == 1 and time.time() < timeout:
            stop = time.time()

        return round((stop - start) * 17150, 2)
    except:
        return 0.0

def sensor_loop():
    while True:
        try:
            sensor_data['motion'] = GPIO.input(PIR_PIN)
            sensor_data['distance'] = get_distance()
            time.sleep(0.5)
        except:
            pass

def generate_frames():
    while True:
        frame = picam2.capture_array()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

def capture_photo():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"photo_{timestamp}.jpg"
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    picam2.switch_mode_and_capture_file(capture_config, save_path)
    return filename

@app.route('/')
def index():
    return render_template('integrated_panel.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture():
    filename = capture_photo()
    return jsonify(filename=filename)

@app.route('/set_angle', methods=['POST'])
def set_angle():
    try:
        angle = int(request.json['angle'])
        move_servo(angle)
        return jsonify(status='OK', angle=current_angle)
    except Exception as e:
        return jsonify(status='ERROR', message=str(e))

@app.route('/get_sensors')
def get_sensors():
    return jsonify(sensor_data)

def cleanup():
    pwm.stop()
    GPIO.cleanup()
    picam2.stop()

if _name_ == '_main_':
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.close()
        
        sensor_thread = threading.Thread(target=sensor_loop, daemon=True)
        sensor_thread.start()
        
        move_servo(0)
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
        
    finally:
        cleanup()