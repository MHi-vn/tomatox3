import queue
import threading
import time
import uuid
import urllib.request

import config


class ESP32WiFiController:
    def __init__(self):
        self.base_url = f"http://{config.ESP32_IP}:{config.HTTP_PORT}"
        self.is_connected = True

        self._session_id = uuid.uuid4().hex[:12]
        self._next_id = 0
        self._commands = queue.Queue(maxsize=128)
        self._lock = threading.Lock()
        self._closed = False

        self._worker = threading.Thread(
            target=self._sender_loop,
            name="esp32-command-sender",
            daemon=True,
        )
        self._worker.start()

    def _enqueue_locked(self, cmd, done_event=None, timeout=0):
        """Gọi khi đang giữ self._lock."""
        if self._closed:
            print(f"⚠️ Controller đã đóng, bỏ lệnh: {cmd}")
            return False

        self._next_id += 1
        command_id = f"{self._session_id}-{self._next_id}"

        try:
            item = (command_id, cmd, done_event)
            if timeout:
                self._commands.put(item, timeout=timeout)
            else:
                self._commands.put_nowait(item)
            return True
        except queue.Full:
            print(
                f"⚠️ Queue lệnh PC đầy "
                f"({self._commands.qsize()} lệnh), không xếp được: {cmd}"
            )
            return False

    def send_cmd(self, cmd):
        if not getattr(config, "ENABLE_ESP", True):
            print(f"📡 [MÔ PHỎNG] Gửi lệnh: {cmd}")
            return True

        with self._lock:
            return self._enqueue_locked(cmd)

    def _sender_loop(self):
        while True:
            command_id, cmd, done_event = self._commands.get()

            try:
                url = (
                    f"{self.base_url}/cmd"
                    f"?val={cmd}&id={command_id}"
                )

                last_error = None
                succeeded = False

                # Retry một lần, dùng lại cùng ID.
                for attempt in range(2):
                    try:
                        with urllib.request.urlopen(url, timeout=0.7) as response:
                            reply = response.read().decode(
                                "utf-8",
                                errors="ignore",
                            ).strip()

                        if reply in ("OK", "DUPLICATE"):
                            self.is_connected = True
                            print(
                                f"✅ [PC -> ESP32] {cmd} "
                                f"(id={command_id}) -> {reply}"
                            )
                            succeeded = True
                        else:
                            self.is_connected = True
                            print(
                                f"⚠️ ESP32 không chấp nhận {cmd} "
                                f"(id={command_id}): {reply}"
                            )
                        break

                    except Exception as exc:
                        last_error = exc
                        self.is_connected = False
                        if attempt == 0:
                            time.sleep(0.1)

                if not succeeded and last_error is not None:
                    print(
                        f"⚠️ Gửi thất bại: {cmd} "
                        f"(id={command_id}): {last_error}"
                    )

            finally:
                if done_event is not None:
                    done_event.set()
                self._commands.task_done()

    # Chế độ và phân loại
    def set_mode_auto(self):
        return self.send_cmd("MODE_AUTO")

    def set_mode_manual(self):
        return self.send_cmd("MODE_MANUAL")

    def reset_queue(self):
        return self.send_cmd("RESET_QUEUE")

    def send_fruit_type(self, label):
        if label not in ("RED", "GREEN", "ROTTEN"):
            print(f"⚠️ Nhãn phân loại không hợp lệ: {label}")
            return False
        return self.send_cmd(label)

    # Tốc độ băng tải
    def set_speed_slow(self):
        return self.send_cmd("SPEED_SLOW")

    def set_speed_med(self):
        return self.send_cmd("SPEED_MED")

    def set_speed_fast(self):
        return self.send_cmd("SPEED_FAST")

    # Điều khiển bằng tay
    def conveyor_on(self):
        return self.send_cmd("CONV_ON")

    def conveyor_off(self):
        return self.send_cmd("CONV_OFF")

    def servo1_push(self):
        return self.send_cmd("S1_PUSH")

    def servo1_pull(self):
        return self.send_cmd("S1_PULL")

    def servo2_push(self):
        return self.send_cmd("S2_PUSH")

    def servo2_pull(self):
        return self.send_cmd("S2_PULL")

    def close(self):
        """Ưu tiên gửi lệnh dừng khi đóng ứng dụng."""
        if not getattr(config, "ENABLE_ESP", True):
            return

        done = threading.Event()

        with self._lock:
            if self._closed:
                return

            # Bỏ các lệnh còn đang chờ khi đóng ứng dụng để lệnh dừng
            # không phải đợi hết hàng đợi phân loại.
            while True:
                try:
                    self._commands.get_nowait()
                    self._commands.task_done()
                except queue.Empty:
                    break

            queued = self._enqueue_locked(
                "CONV_OFF",
                done_event=done,
                timeout=1.0,
            )
            self._closed = True

        if queued:
            done.wait(timeout=2.0)