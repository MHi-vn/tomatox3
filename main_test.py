import network
import socket
import time
from machine import Pin, PWM


class SortingHardware:
    def __init__(self):
        self.ir1 = Pin(4, Pin.IN, Pin.PULL_UP)
        self.ir2 = Pin(5, Pin.IN, Pin.PULL_UP)

        self.servo1 = PWM(Pin(6), freq=50)
        self.servo2 = PWM(Pin(7), freq=50)

        self.ena = PWM(Pin(15), freq=250)
        self.in1 = Pin(16, Pin.OUT)
        self.in2 = Pin(17, Pin.OUT)

        self.ANGLE_PULL = 90
        self.ANGLE_PUSH = 0
        self.current_speed = "MED"
        self.is_running = False

        self.servo1_pull()
        self.servo2_pull()
        time.sleep_ms(150)
        self.conveyor_off()

    def _set_angle(self, servo, angle):
        angle = max(0, min(180, angle))
        pulse_us = 1000 + (angle / 180) * 1000
        duty_u16 = int(pulse_us * 65535 / 20000)
        servo.duty_u16(duty_u16)

    def set_speed(self, speed_mode):
        self.current_speed = speed_mode

        if self.is_running:
            self.conveyor_on()
        else:
            print("-> Đã lưu tốc độ:", self.current_speed)

    def conveyor_on(self):
        self.is_running = True
        self.in1.value(1)
        self.in2.value(0)

        if self.current_speed == "SLOW":
            self.ena.duty_u16(13000)
            speed_pct = "45%"
        elif self.current_speed == "MED":
            self.ena.duty_u16(15000)
            speed_pct = "70%"
        else:
            self.ena.duty_u16(20000)
            speed_pct = "100%"

        print(
            "-> [BĂNG TẢI] MOTOR BẬT:",
            self.current_speed,
            speed_pct,
        )

    def conveyor_off(self):
        self.is_running = False
        self.ena.duty_u16(0)
        self.in1.value(0)
        self.in2.value(0)
        print("-> [BĂNG TẢI] MOTOR ĐÃ DỪNG")

    def servo1_push(self):
        self._set_angle(self.servo1, self.ANGLE_PUSH)

    def servo1_pull(self):
        self._set_angle(self.servo1, self.ANGLE_PULL)

    def servo2_push(self):
        self._set_angle(self.servo2, self.ANGLE_PUSH)

    def servo2_pull(self):
        self._set_angle(self.servo2, self.ANGLE_PULL)


WIFI_SSID = "Hoc Dan"
WIFI_PASS = "0913302827"

wifi_led = Pin(2, Pin.OUT)
wifi_led.value(0)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)

    try:
        wlan.active(False)
        time.sleep_ms(500)
        wlan.active(True)
        time.sleep_ms(1000)

        try:
            wlan.config(pm=wlan.PM_NONE)
        except Exception:
            pass

        for attempt in range(3):
            try:
                if wlan.isconnected():
                    ip = wlan.ifconfig()[0]
                    wifi_led.value(1)
                    print("✅ ESP32-S3 đã kết nối Wi-Fi. IP:", ip)
                    return ip

                print("Đang kết nối Wi-Fi, lần", attempt + 1)
                wlan.connect(WIFI_SSID, WIFI_PASS)

                timeout = 15
                while not wlan.isconnected() and timeout > 0:
                    wifi_led.value(not wifi_led.value())
                    time.sleep(1)
                    timeout -= 1

                if wlan.isconnected():
                    ip = wlan.ifconfig()[0]
                    wifi_led.value(1)
                    print("✅ ESP32-S3 đã kết nối Wi-Fi. IP:", ip)
                    return ip

            except OSError as exc:
                print("⚠️ Lỗi Wi-Fi:", exc)

            try:
                wlan.disconnect()
            except Exception:
                pass

            wlan.active(False)
            time.sleep_ms(1000)
            wlan.active(True)
            time.sleep_ms(1500)

        wifi_led.value(0)
        print("❌ Không kết nối được Wi-Fi sau 3 lần thử")
        return None

    except OSError as exc:
        wifi_led.value(0)
        print("❌ Không khởi tạo được Wi-Fi:", exc)
        return None


def start_wifi_server():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(2)
    server.setblocking(False)
    return server


active_client = None
active_buffer = b""
active_started_ms = 0

seen_command_ids = []
MAX_SEEN_IDS = 128


def parse_request_line(request_line):
    parts = request_line.split()

    if len(parts) < 2 or parts[0] != "GET":
        return None, None

    path = parts[1]

    if "?" in path:
        route, query = path.split("?", 1)
    else:
        route, query = path, ""

    params = {}

    for item in query.split("&"):
        if "=" in item:
            key, value = item.split("=", 1)
            params[key] = value

    command_id = params.get("id")

    if route == "/cmd":
        return params.get("val"), command_id

    if route == "/classify":
        type_map = {
            "A": "GREEN",
            "B": "RED",
            "C": "ROTTEN",
        }
        return type_map.get(params.get("type")), command_id

    if route == "/clear":
        return "RESET_QUEUE", command_id

    return None, command_id


def poll_wifi_request(server):
    global active_client, active_buffer, active_started_ms

    if active_client is None:
        try:
            active_client, _ = server.accept()
            active_client.setblocking(False)
            active_buffer = b""
            active_started_ms = time.ticks_ms()
        except OSError:
            return None

    try:
        chunk = active_client.recv(256)

        if chunk:
            active_buffer += chunk
        else:
            try:
                active_client.close()
            except Exception:
                pass

            active_client = None
            active_buffer = b""
            return None

    except OSError:
        pass

    if b"\r\n" in active_buffer:
        request_line = active_buffer.split(b"\r\n", 1)[0].decode(
            "utf-8",
            "ignore",
        )

        cmd, command_id = parse_request_line(request_line)
        duplicate = (
            command_id is not None
            and command_id in seen_command_ids
        )

        return active_client, cmd, command_id, duplicate

    if time.ticks_diff(time.ticks_ms(), active_started_ms) > 1000:
        try:
            active_client.close()
        except Exception:
            pass

        active_client = None
        active_buffer = b""

    return None


def finish_http_request(client, response_text):
    global active_client, active_buffer

    try:
        body = response_text.encode()

        header = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            b"Connection: close\r\n"
            b"Content-Length: "
            + str(len(body)).encode()
            + b"\r\n\r\n"
        )

        client.settimeout(0.05)
        client.sendall(header + body)

    except Exception:
        pass

    finally:
        try:
            client.close()
        except Exception:
            pass

        active_client = None
        active_buffer = b""


def remember_command_id(command_id):
    if not command_id:
        return

    seen_command_ids.append(command_id)

    if len(seen_command_ids) > MAX_SEEN_IDS:
        seen_command_ids.pop(0)


hw = SortingHardware()

wifi_ip = connect_wifi()
server = start_wifi_server()

if wifi_ip:
    hw.conveyor_on()
else:
    print("⚠️ Chưa kết nối Wi-Fi; băng tải đang dừng")

HOLD_TIME_MS = 600
LOW_CONFIRM_MS = 20
HIGH_REARM_MS = 50
DEBOUNCE_MS = 100
MAX_FRUIT_QUEUE = 64

auto_mode = True
system_fault = False

queue_ir1 = []
queue_ir2 = []

s1_active = False
s1_timer = 0
s2_active = False
s2_timer = 0

ir1_last_trig = 0
ir2_last_trig = 0

ir1_filter = {
    "armed": True,
    "low_since": None,
    "high_since": None,
}

ir2_filter = {
    "armed": True,
    "low_since": None,
    "high_since": None,
}


def sensor_triggered(pin, state, now):
    value = pin.value()

    if value == 0:
        state["high_since"] = None

        if state["armed"]:
            if state["low_since"] is None:
                state["low_since"] = now
            elif time.ticks_diff(now, state["low_since"]) >= LOW_CONFIRM_MS:
                state["armed"] = False
                state["low_since"] = None
                return True

    else:
        state["low_since"] = None

        if not state["armed"]:
            if state["high_since"] is None:
                state["high_since"] = now
            elif time.ticks_diff(now, state["high_since"]) >= HIGH_REARM_MS:
                state["armed"] = True
                state["high_since"] = None

    return False


def handle_command(cmd):
    global auto_mode, HOLD_TIME_MS, system_fault
    global s1_active, s2_active

    if cmd == "SPEED_SLOW":
        HOLD_TIME_MS = 700
        hw.set_speed("SLOW")
        return True

    if cmd == "SPEED_MED":
        HOLD_TIME_MS = 400
        hw.set_speed("MED")
        return True

    if cmd == "SPEED_FAST":
        HOLD_TIME_MS = 250
        hw.set_speed("FAST")
        return True

    if cmd == "MODE_AUTO":
        auto_mode = True
        s1_active = False
        s2_active = False
        hw.servo1_pull()
        hw.servo2_pull()

        if not system_fault:
            hw.conveyor_on()
        return True

    if cmd == "MODE_MANUAL":
        auto_mode = False
        s1_active = False
        s2_active = False
        system_fault = False
        queue_ir1.clear()
        queue_ir2.clear()
        hw.conveyor_off()
        hw.servo1_pull()
        hw.servo2_pull()
        return True

    if cmd == "RESET_QUEUE":
        queue_ir1.clear()
        queue_ir2.clear()
        s1_active = False
        s2_active = False
        system_fault = False
        hw.servo1_pull()
        hw.servo2_pull()

        if auto_mode:
            hw.conveyor_on()
        return True

    if cmd in ("RED", "GREEN", "ROTTEN"):
        if not auto_mode or system_fault:
            return False

        if len(queue_ir1) >= MAX_FRUIT_QUEUE:
            print("❌ Hàng đợi IR1 đầy")
            system_fault = True
            hw.conveyor_off()
            return False

        if not hw.is_running:
            hw.conveyor_on()

        queue_ir1.append(cmd)
        print("-> IR1:", queue_ir1, "| IR2:", queue_ir2)
        return True

    if cmd == "CONV_ON":
        hw.conveyor_on()
        return True

    if cmd == "CONV_OFF":
        hw.conveyor_off()
        return True

    if cmd == "S1_PUSH":
        hw.servo1_push()
        return True

    if cmd == "S1_PULL":
        hw.servo1_pull()
        return True

    if cmd == "S2_PUSH":
        hw.servo2_push()
        return True

    if cmd == "S2_PULL":
        hw.servo2_pull()
        return True

    return False


while True:
    try:
        request = poll_wifi_request(server)

        if request is not None:
            client, cmd, command_id, duplicate = request

            if duplicate:
                finish_http_request(client, "DUPLICATE")

            elif cmd is None:
                finish_http_request(client, "ERR")

            else:
                accepted = handle_command(cmd)

                if accepted:
                    remember_command_id(command_id)
                    print("📥 Đã xử lý lệnh:", cmd)
                    finish_http_request(client, "OK")
                else:
                    print("⚠️ Không chấp nhận lệnh:", cmd)
                    finish_http_request(client, "ERR")

        now = time.ticks_ms()

        if auto_mode and not system_fault:
            ir1_event = sensor_triggered(hw.ir1, ir1_filter, now)
            ir2_event = sensor_triggered(hw.ir2, ir2_filter, now)

            if ir1_event:
                if time.ticks_diff(now, ir1_last_trig) <= DEBOUNCE_MS:
                    ir1_event = False
                else:
                    ir1_last_trig = now

            if ir2_event:
                if time.ticks_diff(now, ir2_last_trig) <= DEBOUNCE_MS:
                    ir2_event = False
                else:
                    ir2_last_trig = now

            if ir1_event:
                if not queue_ir1:
                    print("❌ IR1 có xung ổn định nhưng queue IR1 rỗng")
                    system_fault = True
                    hw.conveyor_off()

                elif (
                    queue_ir1[0] != "RED"
                    and len(queue_ir2) >= MAX_FRUIT_QUEUE
                ):
                    print("❌ Queue IR2 đầy")
                    system_fault = True
                    hw.conveyor_off()

                else:
                    fruit = queue_ir1.pop(0)
                    print("🎯 IR1:", fruit, "| Còn:", queue_ir1)

                    if fruit == "RED":
                        hw.servo1_push()
                        s1_active = True
                        s1_timer = now
                    else:
                        queue_ir2.append(fruit)

            if not system_fault and ir2_event:
                if not queue_ir2:
                    print("❌ IR2 có xung ổn định nhưng queue IR2 rỗng")
                    system_fault = True
                    hw.conveyor_off()
                else:
                    fruit = queue_ir2.pop(0)
                    print("🎯 IR2:", fruit, "| Còn:", queue_ir2)

                    if fruit == "GREEN":
                        hw.servo2_push()
                        s2_active = True
                        s2_timer = now

        if s1_active and time.ticks_diff(now, s1_timer) >= HOLD_TIME_MS:
            hw.servo1_pull()
            s1_active = False

        if s2_active and time.ticks_diff(now, s2_timer) >= HOLD_TIME_MS:
            hw.servo2_pull()
            s2_active = False

        time.sleep_ms(5)

    except KeyboardInterrupt:
        hw.conveyor_off()
        break

    except Exception as exc:
        print("⚠️ Lỗi trong vòng lặp ESP32:", exc)
        time.sleep_ms(20)
