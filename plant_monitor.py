import io
import logging
import socketserver
from http import server
from threading import Condition

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput
import Adafruit_DHT
import glob
import datetime
import time
import os

PAGE = """\
<html>
<head>
<title>picamera2 MJPEG streaming demo</title>
</head>
<body>
<h1>Picamera2 MJPEG Streaming Demo</h1>
<img src="stream.mjpg" width="640" height="480" />
<p>DHT11 Temperature: {}&deg;C, Humidity: {}%</p>
<p>DS18B20 Temperature: {}&deg;C</p>
</body>
</html>
"""

def take_screenshot():
    now = datetime.datetime.now()
    filename = '/home/pi-admin/Desktop/Snapshots/{}-{}-{}-{}-{}.jpg'.format(now.year, now.month, now.day, now.hour, now.minute)
    with open(filename, 'wb') as f:
        f.write(output.frame)

class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()

class StreamingHandler(server.BaseHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self.last_screenshot_time = datetime.datetime.now()
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            # Read DHT11 sensor data
            humidity, temperature = Adafruit_DHT.read_retry(Adafruit_DHT.DHT11, 27)

            # Read DS18B20 sensor data
            ds18b20_file = glob.glob('/sys/bus/w1/devices/*/w1_slave')[0]
            with open(ds18b20_file, 'r') as f:
                lines = f.readlines()
            ds18b20_temperature = round(int(lines[1].split('=')[1]) / 1000, 1)

            # Format the HTML page with the sensor data
            content = PAGE.format(temperature, humidity, ds18b20_temperature).encode('utf-8')

            # Send the HTTP response with the HTML page
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')


                    # Take a screenshot every 60 minutes
                    elapsed_time = (datetime.datetime.now() - self.last_screenshot_time).total_seconds() / 60
                    if elapsed_time >= 1:
                        self.last_screenshot_time = datetime.datetime.now()
                        filename = '/home/pi-admin/Desktop/Snapshots/{}.jpg'.format(datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
                        with open(filename, 'wb') as f:
                            f.write(frame)
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
output = StreamingOutput()
picam2.start_recording(JpegEncoder(), FileOutput(output))

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    picam2.stop_recording()

