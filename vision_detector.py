# File: vision_detector.py
import time
from collections import Counter, deque
import cv2
import numpy as np
import config

class TomatoDetector:
    def __init__(self):
        self.tracks = {}
        self.next_id = 0
        self.recent_triggers = deque()
        self.open_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.GLOBAL_OPEN_SIZE, config.GLOBAL_OPEN_SIZE)
        )
        self.close_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.GLOBAL_CLOSE_SIZE, config.GLOBAL_CLOSE_SIZE)
        )
        self.erode_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (config.ERODE_FOR_SHADOW, config.ERODE_FOR_SHADOW)
        )

    def build_red_mask(self, hsv: np.ndarray) -> np.ndarray:
        m1 = cv2.inRange(hsv, config.RED1_LOWER, config.RED1_UPPER)
        m2 = cv2.inRange(hsv, config.RED2_LOWER, config.RED2_UPPER)
        return cv2.bitwise_or(m1, m2)

    def build_isolated_object_mask(self, cnt, x: int, y: int, w: int, h: int) -> np.ndarray:
        obj_mask = np.zeros((h, w), dtype=np.uint8)
        shifted_cnt = cnt - [x, y]
        cv2.drawContours(obj_mask, [shifted_cnt], -1, 255, cv2.FILLED)

        cnt_area = cv2.contourArea(cnt)
        hull = cv2.convexHull(shifted_cnt)
        hull_area = max(1.0, cv2.contourArea(hull))
        solidity = cnt_area / hull_area

        if solidity >= 0.78:
            cv2.drawContours(obj_mask, [hull], -1, 255, cv2.FILLED)
        else:
            local_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
            obj_mask = cv2.morphologyEx(obj_mask, cv2.MORPH_CLOSE, local_close)

        return obj_mask

    # --- TRONG FILE vision_detector.py ---
# Bạn thay thế toàn bộ hàm classify_single_tomato và compute_stable_label thành:

    def classify_single_tomato(self, roi_bgr, obj_mask):
        if roi_bgr is None or roi_bgr.size == 0 or obj_mask is None:
            return "unknown"

        isolated_bgr = cv2.bitwise_and(roi_bgr, roi_bgr, mask=obj_mask)
        hsv = cv2.cvtColor(isolated_bgr, cv2.COLOR_BGR2HSV)

        red_raw = self.build_red_mask(hsv)
        green_raw = cv2.inRange(hsv, config.GREEN_LOWER, config.GREEN_UPPER)
        dark_raw = cv2.inRange(hsv, config.DARK_LOWER, config.DARK_UPPER)

        k3 = np.ones((3, 3), np.uint8)
        red_mask = cv2.morphologyEx(cv2.bitwise_and(red_raw, obj_mask), cv2.MORPH_OPEN, k3)
        green_mask = cv2.morphologyEx(cv2.bitwise_and(green_raw, obj_mask), cv2.MORPH_OPEN, k3)

        red_area = cv2.countNonZero(red_mask)
        green_area = cv2.countNonZero(green_mask)
        obj_area = cv2.countNonZero(obj_mask)

        if (red_area + green_area) < config.MIN_FRUIT_AREA or obj_area == 0:
            return "unknown"

        is_red_dominant = red_area >= green_area and red_area > 200
        is_green_dominant = green_area > red_area and green_area > 200

        # Nếu là quả Đỏ, tiến hành quét tìm vết thối
        if is_red_dominant:
            inner_fruit_mask = cv2.erode(obj_mask, self.erode_kernel)
            color_union = cv2.bitwise_or(red_mask, green_mask)
            non_fruit_color = cv2.bitwise_not(color_union)

            black_in_fruit = cv2.bitwise_and(dark_raw, inner_fruit_mask)
            black_in_fruit = cv2.bitwise_and(black_in_fruit, non_fruit_color)
            black_in_fruit = cv2.morphologyEx(black_in_fruit, cv2.MORPH_OPEN, k3)
            black_in_fruit = cv2.morphologyEx(black_in_fruit, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

            black_contours, _ = cv2.findContours(black_in_fruit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            s_channel = hsv[:, :, 1]
            v_channel = hsv[:, :, 2]

            dynamic_min_spot = max(config.MIN_ROT_SPOT_AREA, int(obj_area * config.ROT_AREA_RATIO))
            total_black_area = 0

            for b_cnt in black_contours:
                area = cv2.contourArea(b_cnt)
                if area < dynamic_min_spot * 0.5:
                    continue

                spot_mask = np.zeros(obj_mask.shape, dtype=np.uint8)
                cv2.drawContours(spot_mask, [b_cnt], -1, 255, -1)
                mean_s = cv2.mean(s_channel, mask=spot_mask)[0]
                mean_v = cv2.mean(v_channel, mask=spot_mask)[0]

                if mean_s < 120 and mean_v < 85:
                    total_black_area += area

            if total_black_area >= dynamic_min_spot:
                return "Đỏ thối"
            return "Đỏ"

        # Bỏ qua hoàn toàn quét đốm đen nếu là quả Xanh
        if is_green_dominant:
            return "Xanh"

        return "unknown"

    @staticmethod
    def compute_stable_label(track: dict) -> str:
        history = track["history"]
        if not history:
            return "unknown"
            
        # Chỉ còn khóa cứng nhãn nếu là quả Đỏ thối
        if track.get("rot_red_count", 0) >= 2:
            return "Đỏ thối"
            
        most_common_label, _ = Counter(history).most_common(1)[0]
        return most_common_label

    def process_frame(self, frame):
        triggered_fruits = []
        now = time.time()

        if getattr(config, "FLIP_FRAME", True):
            frame = cv2.flip(frame, 1)

        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

        fruit_mask = cv2.bitwise_or(
            self.build_red_mask(hsv),
            cv2.inRange(hsv, config.GREEN_LOWER, config.GREEN_UPPER),
        )
        fruit_mask = cv2.morphologyEx(fruit_mask, cv2.MORPH_OPEN, self.open_kernel)
        fruit_mask = cv2.morphologyEx(fruit_mask, cv2.MORPH_CLOSE, self.close_kernel)

        # Vẽ vạch Trigger
        if getattr(config, "TRIGGER_HORIZONTAL", True):
            cv2.line(frame, (0, config.LINE_Y), (frame.shape[1], config.LINE_Y), (0, 255, 255), 2)
            cv2.putText(frame, "TRIGGER LINE", (10, config.LINE_Y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        else:
            cv2.line(frame, (config.LINE_X, 0), (config.LINE_X, frame.shape[0]), (0, 255, 255), 2)
            cv2.putText(frame, "TRIGGER LINE", (config.LINE_X + 6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

        contours, _ = cv2.findContours(fruit_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections = []

        for cnt in contours:
            if cv2.contourArea(cnt) < config.MIN_CONTOUR_AREA:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            if w < 25 or h < 25:
                continue

            obj_mask = self.build_isolated_object_mask(cnt, x, y, w, h)
            moments = cv2.moments(obj_mask, binaryImage=True)
            if moments["m00"] > 0:
                cx = x + int(moments["m10"] / moments["m00"])
                cy = y + int(moments["m01"] / moments["m00"])
            else:
                cx, cy = x + w // 2, y + h // 2

            roi_bgr = frame[y : y + h, x : x + w]
            raw_label = self.classify_single_tomato(roi_bgr, obj_mask)

            detections.append({
                "cx": cx,
                "cy": cy,
                "box": (x, y, w, h),
                "cnt": cnt,
                "raw_label": raw_label,
            })

        # Cập nhật Tracker theo ID
        used_tracks = set()
        new_tracks = {}
        self.recent_triggers = deque(
            [t for t in self.recent_triggers if (now - t[0]) < config.TRIGGER_COOLDOWN]
        )

        label_to_gui_code = {
            "Đỏ": "RED",
            "Xanh": "GREEN",
            "Đỏ thối": "ROTTEN",
        }

        for det in detections:
            best_id = None
            best_dist = config.DIST_THRESHOLD

            for tid, tr in self.tracks.items():
                if tid in used_tracks:
                    continue
                dist = ((det["cx"] - tr["cx"]) ** 2 + (det["cy"] - tr["cy"]) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_id = tid

            if best_id is None:
                best_id = self.next_id
                self.next_id += 1
                track_data = {
                    "cx": det["cx"],
                    "cy": det["cy"],
                    "prev_cx": det["cx"],
                    "prev_cy": det["cy"],
                    "triggered": False,
                    "missing": 0,
                    "history": deque(maxlen=config.HISTORY_LEN),
                    "rot_red_count": 0,
                }
            else:
                used_tracks.add(best_id)
                old_tr = self.tracks[best_id]
                track_data = {
                    "cx": det["cx"],
                    "cy": det["cy"],
                    "prev_cx": old_tr["cx"],
                    "prev_cy": old_tr["cy"],
                    "triggered": old_tr["triggered"],
                    "missing": 0,
                    "history": old_tr["history"],
                    "rot_red_count": old_tr.get("rot_red_count", 0),
                }

            # Cập nhật lịch sử (Xóa bộ đếm nếu quả lăn mất vết thối)
            raw_label = det["raw_label"]
            if raw_label != "unknown":
                track_data["history"].append(raw_label)
                # Tích lũy số lần thấy vết thối (KHÔNG reset về 0 khi quả lăn khuất vết thối)
                if raw_label == "Đỏ thối":
                    track_data["rot_red_count"] += 1

            stable_label = self.compute_stable_label(track_data)

            # Map màu hiển thị lên màn hình
            if stable_label == "Xanh":
                color, display_txt = (0, 255, 0), "QUA XANH"
            elif stable_label == "Đỏ":
                color, display_txt = (0, 0, 255), "QUA DO"
            elif stable_label == "Đỏ thối":
                color, display_txt = (0, 165, 255), "QUA THOI"
            else:
                color, display_txt = (200, 200, 200), "UNKNOWN"

            # Kiểm tra chạm vạch Trigger
            if getattr(config, "TRIGGER_HORIZONTAL", True):
                in_zone = abs(det["cy"] - config.LINE_Y) <= config.LINE_OFFSET
                crossed = (track_data["prev_cy"] < config.LINE_Y <= det["cy"]) or (
                    track_data["prev_cy"] > config.LINE_Y >= det["cy"]
                )
            else:
                in_zone = abs(det["cx"] - config.LINE_X) <= config.LINE_OFFSET
                crossed = (track_data["prev_cx"] < config.LINE_X <= det["cx"]) or (
                    track_data["prev_cx"] > config.LINE_X >= det["cx"]
                )

            if (in_zone or crossed) and stable_label != "unknown" and not track_data["triggered"]:
                is_duplicate = any(
                    ((det["cx"] - tx) ** 2 + (det["cy"] - ty) ** 2) ** 0.5 < 50
                    for _, tx, ty in self.recent_triggers
                )
                if not is_duplicate:
                    track_data["triggered"] = True
                    self.recent_triggers.append((now, det["cx"], det["cy"]))
                    gui_code = label_to_gui_code.get(stable_label)
                    if gui_code:
                        triggered_fruits.append(gui_code)

            new_tracks[best_id] = track_data

            # Vẽ thông tin Tracking lên khung hình
            x, y, w, h = det["box"]
            cv2.drawContours(frame, [det["cnt"]], -1, color, 2)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 1)
            cv2.circle(frame, (det["cx"], det["cy"]), 4, (255, 255, 0), -1)
            cv2.putText(
                frame,
                f"ID:{best_id} {display_txt}",
                (x, max(25, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )

        for tid, tr in self.tracks.items():
            if tid not in new_tracks:
                tr["missing"] += 1
                if tr["missing"] < config.MAX_MISSING:
                    new_tracks[tid] = tr

        self.tracks = new_tracks
        return frame, triggered_fruits