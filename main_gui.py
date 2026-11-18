import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
from PIL import Image, ImageTk

import config
from serial_comm import ESP32WiFiController
from vision_detector import TomatoDetector


class LatestFrameCamera:
    """Đọc camera liên tục và chỉ lưu frame mới nhất."""

    def __init__(self, camera_index, width, height):
        self.cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.frame = None
        self.sequence = 0

        self.thread = threading.Thread(
            target=self._capture_loop,
            name="camera-capture",
            daemon=True,
        )
        self.thread.start()

    def _capture_loop(self):
        while not self.stop_event.is_set():
            if not self.cap.isOpened():
                self.stop_event.wait(0.1)
                continue

            ret, frame = self.cap.read()
            if not ret:
                self.stop_event.wait(0.01)
                continue

            with self.lock:
                self.frame = frame
                self.sequence += 1

    def read_latest(self):
        with self.lock:
            if self.frame is None:
                return None, None
            return self.sequence, self.frame.copy()

    def close(self):
        self.stop_event.set()

        if self.cap and self.cap.isOpened():
            self.cap.release()

        if self.thread.is_alive():
            self.thread.join(timeout=1.0)


class TomatoSortingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Hệ thống Giám sát và Điều khiển Phân loại Cà chua")
        self.root.geometry("1120x660")
        self.root.configure(bg="#f4f6f9")

        self.esp = ESP32WiFiController()
        self.detector = TomatoDetector()
        self.camera = LatestFrameCamera(
            config.CAMERA_INDEX,
            config.FRAME_WIDTH,
            config.FRAME_HEIGHT,
        )

        self.mode = "AUTO"
        self.counts = {
            "RED": 0,
            "GREEN": 0,
            "ROTTEN": 0,
        }

        self.last_frame_sequence = -1
        self.last_processed_frame = None
        self.photo_image = None
        self.closing = False

        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.update_loop()

    def build_ui(self):
        left_frame = tk.Frame(
            self.root,
            bg="#ffffff",
            bd=2,
            relief="groove",
        )
        left_frame.place(x=15, y=15, width=660, height=630)

        tk.Label(
            left_frame,
            text="CAMERA XỬ LÝ ẢNH & PHÂN LOẠI",
            font=("Arial", 13, "bold"),
            bg="#ffffff",
        ).pack(pady=8)

        self.cam_label = tk.Label(left_frame, bg="#000000")
        self.cam_label.pack(padx=10, pady=5)

        info_frame = tk.Frame(
            left_frame,
            bg="#eef2f7",
            bd=1,
            relief="solid",
        )
        info_frame.pack(fill="x", padx=12, pady=10)

        self.lbl_last_fruit = tk.Label(
            info_frame,
            text="Quả vừa phân loại: Chưa có",
            font=("Arial", 13, "bold"),
            bg="#eef2f7",
            fg="#2980b9",
        )
        self.lbl_last_fruit.pack(pady=6)

        tk.Label(
            info_frame,
            text=f"Điều khiển qua Wi-Fi: {config.ESP32_IP}",
            font=("Arial", 10),
            bg="#eef2f7",
        ).pack(pady=3)

        stat_frame = tk.LabelFrame(
            self.root,
            text=" THỐNG KÊ SỐ LƯỢNG QUẢ ",
            font=("Arial", 12, "bold"),
            bg="#ffffff",
            padx=15,
            pady=10,
        )
        stat_frame.place(x=690, y=15, width=415, height=250)

        self.lbl_red = tk.Label(
            stat_frame,
            text="Quả Đỏ (Gạt Servo 1): 0",
            font=("Arial", 12, "bold"),
            fg="#e74c3c",
            bg="#ffffff",
        )
        self.lbl_red.pack(anchor="w", pady=4)

        self.lbl_green = tk.Label(
            stat_frame,
            text="Quả Xanh (Gạt Servo 2): 0",
            font=("Arial", 12, "bold"),
            fg="#27ae60",
            bg="#ffffff",
        )
        self.lbl_green.pack(anchor="w", pady=4)

        self.lbl_rotten = tk.Label(
            stat_frame,
            text="Quả Đỏ thối (Đi cuối băng tải): 0",
            font=("Arial", 12, "bold"),
            fg="#8e44ad",
            bg="#ffffff",
        )
        self.lbl_rotten.pack(anchor="w", pady=4)

        ttk.Separator(
            stat_frame,
            orient="horizontal",
        ).pack(fill="x", pady=6)

        self.lbl_total = tk.Label(
            stat_frame,
            text="Tổng số quả: 0",
            font=("Arial", 13, "bold"),
            bg="#ffffff",
        )
        self.lbl_total.pack(anchor="w", pady=4)

        tk.Button(
            stat_frame,
            text="Reset bộ đếm & Hàng đợi",
            font=("Arial", 10, "bold"),
            bg="#f39c12",
            fg="white",
            command=self.reset_counters,
        ).pack(fill="x", pady=5)

        ctrl_frame = tk.LabelFrame(
            self.root,
            text=" BẢNG ĐIỀU KHIỂN HỆ THỐNG ",
            font=("Arial", 12, "bold"),
            bg="#ffffff",
            padx=15,
            pady=10,
        )
        ctrl_frame.place(x=690, y=280, width=415, height=365)

        mode_box = tk.Frame(ctrl_frame, bg="#ffffff")
        mode_box.pack(fill="x", pady=5)

        self.btn_auto = tk.Button(
            mode_box,
            text="CHẾ ĐỘ AUTO",
            font=("Arial", 11, "bold"),
            bg="#2ecc71",
            fg="white",
            width=16,
            height=2,
            command=self.switch_to_auto,
        )
        self.btn_auto.pack(side="left", padx=5)

        self.btn_manual = tk.Button(
            mode_box,
            text="CHẾ ĐỘ MANUAL",
            font=("Arial", 11, "bold"),
            bg="#bdc3c7",
            width=16,
            height=2,
            command=self.switch_to_manual,
        )
        self.btn_manual.pack(side="right", padx=5)

        self.lbl_mode_note = tk.Label(
            ctrl_frame,
            text="Đang chạy AUTO: Băng tải bật, tự động phân loại",
            font=("Arial", 10, "italic"),
            bg="#ffffff",
            fg="#27ae60",
        )
        self.lbl_mode_note.pack(pady=6)

        speed_box = tk.Frame(ctrl_frame, bg="#ffffff")
        speed_box.pack(fill="x", pady=4)

        tk.Label(
            speed_box,
            text="Tốc độ băng tải:",
            font=("Arial", 10, "bold"),
            bg="#ffffff",
        ).pack(side="left")

        tk.Button(
            speed_box,
            text="Chậm",
            width=7,
            bg="#3498db",
            fg="white",
            command=self.esp.set_speed_slow,
        ).pack(side="left", padx=3)

        tk.Button(
            speed_box,
            text="Vừa",
            width=7,
            bg="#2980b9",
            fg="white",
            command=self.esp.set_speed_med,
        ).pack(side="left", padx=3)

        tk.Button(
            speed_box,
            text="Nhanh",
            width=7,
            bg="#1f618d",
            fg="white",
            command=self.esp.set_speed_fast,
        ).pack(side="left", padx=3)

        ttk.Separator(
            ctrl_frame,
            orient="horizontal",
        ).pack(fill="x", pady=6)

        tk.Label(
            ctrl_frame,
            text="Điều khiển thủ công (Chỉ mở khi ở MANUAL):",
            font=("Arial", 10, "bold"),
            bg="#ffffff",
        ).pack(anchor="w", pady=4)

        self.manual_buttons = []

        self.create_manual_row(
            ctrl_frame,
            "Băng tải:",
            "Bật chạy",
            self.esp.conveyor_on,
            "#27ae60",
            "Tắt dừng",
            self.esp.conveyor_off,
            "#c0392b",
        )

        self.create_manual_row(
            ctrl_frame,
            "Servo 1 (Đỏ):",
            "Gạt ra",
            self.esp.servo1_push,
            "#2980b9",
            "Thu về",
            self.esp.servo1_pull,
            "#7f8c8d",
        )

        self.create_manual_row(
            ctrl_frame,
            "Servo 2 (Xanh):",
            "Gạt ra",
            self.esp.servo2_push,
            "#2980b9",
            "Thu về",
            self.esp.servo2_pull,
            "#7f8c8d",
        )

    def create_manual_row(
        self,
        parent,
        label_text,
        btn1_text,
        cmd1,
        color1,
        btn2_text,
        cmd2,
        color2,
    ):
        row = tk.Frame(parent, bg="#ffffff")
        row.pack(fill="x", pady=6)

        tk.Label(
            row,
            text=label_text,
            width=16,
            anchor="w",
            font=("Arial", 10),
            bg="#ffffff",
        ).pack(side="left")

        btn1 = tk.Button(
            row,
            text=btn1_text,
            width=11,
            state="disabled",
            bg=color1,
            fg="white",
            command=cmd1,
        )
        btn1.pack(side="left", padx=4)

        btn2 = tk.Button(
            row,
            text=btn2_text,
            width=11,
            state="disabled",
            bg=color2,
            fg="white",
            command=cmd2,
        )
        btn2.pack(side="left", padx=4)

        self.manual_buttons.extend([btn1, btn2])

    def switch_to_auto(self):
        self.mode = "AUTO"
        self.btn_auto.config(bg="#2ecc71", fg="white")
        self.btn_manual.config(bg="#bdc3c7", fg="black")
        self.lbl_mode_note.config(
            text="Đang chạy AUTO: Băng tải bật, tự động phân loại",
            fg="#27ae60",
        )

        for button in self.manual_buttons:
            button.config(state="disabled")

        self.esp.set_mode_auto()

    def switch_to_manual(self):
        self.mode = "MANUAL"
        self.btn_manual.config(bg="#e67e22", fg="white")
        self.btn_auto.config(bg="#bdc3c7", fg="black")
        self.lbl_mode_note.config(
            text="Đang ở MANUAL: Điều khiển băng tải & Servo bằng tay",
            fg="#d35400",
        )

        for button in self.manual_buttons:
            button.config(state="normal")

        self.esp.set_mode_manual()

    def reset_counters(self):
        self.counts = {
            "RED": 0,
            "GREEN": 0,
            "ROTTEN": 0,
        }
        self.refresh_counter_ui()
        self.esp.reset_queue()

    def refresh_counter_ui(self):
        total = sum(self.counts.values())
        self.lbl_red.config(
            text=f"Quả Đỏ (Gạt Servo 1): {self.counts['RED']}"
        )
        self.lbl_green.config(
            text=f"Quả Xanh (Gạt Servo 2): {self.counts['GREEN']}"
        )
        self.lbl_rotten.config(
            text=f"Quả Đỏ thối (Đi cuối băng tải): {self.counts['ROTTEN']}"
        )
        self.lbl_total.config(text=f"Tổng số quả: {total}")

    def update_loop(self):
        if self.closing:
            return

        sequence, frame = self.camera.read_latest()

        if sequence is not None and sequence != self.last_frame_sequence:
            self.last_frame_sequence = sequence
            frame = cv2.resize(
                frame,
                (config.FRAME_WIDTH, config.FRAME_HEIGHT),
            )

            processed_frame, triggered_list = self.detector.process_frame(frame)
            self.last_processed_frame = processed_frame

            if self.mode == "AUTO":
                for label in triggered_list:
                    queued = self.esp.send_fruit_type(label)

                    if not queued:
                        print(
                            f"⚠️ Không xếp được lệnh {label} "
                            "vào queue gửi ESP32"
                        )
                        continue

                    # Bộ đếm này đếm kết quả được PC nhận diện và xếp lệnh,
                    # không phải xác nhận quả đã được servo gạt.
                    self.counts[label] += 1
                    self.refresh_counter_ui()

                    names = {
                        "RED": ("QUẢ ĐỎ (Gạt Servo 1)", "#e74c3c"),
                        "GREEN": ("QUẢ XANH (Gạt Servo 2)", "#27ae60"),
                        "ROTTEN": ("ĐỎ THỐI (Đi thẳng)", "#8e44ad"),
                    }

                    if label in names:
                        text, color = names[label]
                        self.lbl_last_fruit.config(
                            text=f"Quả vừa phân loại: {text}",
                            fg=color,
                        )

            rgb = cv2.cvtColor(
                self.last_processed_frame,
                cv2.COLOR_BGR2RGB,
            )
            self.photo_image = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.cam_label.configure(image=self.photo_image)

        self.root.after(25, self.update_loop)

    def on_closing(self):
        if self.closing:
            return

        self.closing = True
        self.camera.close()
        self.esp.close()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TomatoSortingApp(root)
    root.mainloop()