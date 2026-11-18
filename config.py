import numpy as np

# Wi-Fi & IP của ESP32-S3
ESP32_IP = "192.168.1.4"
HTTP_PORT = 80
ENABLE_ESP = True

# Camera
CAMERA_INDEX = 0
FRAME_WIDTH = 630
FRAME_HEIGHT = 460
FLIP_FRAME = True

# Vạch trigger ngang.
# 0.40 = 40% chiều cao ảnh, nằm phía trên tâm.
TRIGGER_HORIZONTAL = True
TRIGGER_LINE_RATIO = 0.40
LINE_Y = int(FRAME_HEIGHT * TRIGGER_LINE_RATIO)
LINE_X = FRAME_WIDTH // 2
LINE_OFFSET = 14

# Ngưỡng HSV
RED1_LOWER = np.array([0, 85, 65])
RED1_UPPER = np.array([12, 255, 255])
RED2_LOWER = np.array([165, 85, 65])
RED2_UPPER = np.array([180, 255, 255])

GREEN_LOWER = np.array([28, 65, 60])
GREEN_UPPER = np.array([92, 255, 255])

DARK_LOWER = np.array([0, 0, 0])
DARK_UPPER = np.array([180, 125, 90])

# Diện tích và lọc bóng
MIN_CONTOUR_AREA = 3200
MIN_FRUIT_AREA = 400
MIN_ROT_SPOT_AREA = 170
ROT_AREA_RATIO = 0.02
ERODE_FOR_SHADOW = 13
GLOBAL_OPEN_SIZE = 5
GLOBAL_CLOSE_SIZE = 5

# Tracking
MAX_MISSING = 12
DIST_THRESHOLD = 50
HISTORY_LEN = 5
TRIGGER_COOLDOWN = 0.2