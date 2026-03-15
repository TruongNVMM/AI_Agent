# PTZ Camera Controller

Ứng dụng điều khiển camera PTZ sử dụng MTRPC API với giao diện đồ họa.

## Tính năng

- ✅ **Xác thực an toàn**: Digest authentication
- ✅ **Điều khiển PTZ đầy đủ**: 8 hướng di chuyển, zoom, focus
- ✅ **Quản lý Preset**: Lưu, di chuyển đến, và xóa preset positions
- ✅ **Giao diện trực quan**: GUI hiện đại với tkinter
- ✅ **Session tự động**: Heartbeat duy trì kết nối

## Cài đặt

### Yêu cầu
- Python 3.7+
- tkinter (thường đi kèm với Python)

### Cài đặt dependencies

```bash
pip install -r requirements.txt
```

## Sử dụng

### Chạy ứng dụng GUI

```bash
python ptz_controller_gui.py
```

### Sử dụng API trực tiếp

```python
from mtrpc_client import MTRPCClient

# Kết nối camera
client = MTRPCClient("192.168.1.100", port=80)
client.login("admin", "password")

# Điều khiển PTZ
client.move_left(speed=5)
client.zoom_in(speed=3)
client.auto_focus()

# Quản lý preset
client.set_preset(1)  # Lưu vị trí hiện tại
client.goto_preset(1)  # Di chuyển đến preset
client.clear_preset(1)  # Xóa preset

# Lấy danh sách preset
presets = client.get_all_presets()
for preset in presets:
    print(f"Preset {preset['index']}: {preset['name']}")

# Ngắt kết nối
client.logout()
```

## Cấu hình

Chỉnh sửa `config.json` để thiết lập mặc định:

```json
{
  "camera": {
    "host": "192.168.1.100",
    "port": 80,
    "username": "admin",
    "password": ""
  },
  "ptz": {
    "default_speed": 5
  }
}
```

## Các lệnh PTZ hỗ trợ

### Di chuyển
- `move_left()`, `move_right()`, `move_up()`, `move_down()`
- `move_left_up()`, `move_left_down()`, `move_right_up()`, `move_right_down()`
- `stop_move()`

### Zoom
- `zoom_in()`, `zoom_out()`, `stop_zoom()`

### Focus
- `focus_near()`, `focus_far()`, `stop_focus()`, `auto_focus()`

### Preset
- `set_preset(id)` - Lưu vị trí hiện tại
- `goto_preset(id)` - Di chuyển đến preset
- `clear_preset(id)` - Xóa preset
- `get_all_presets()` - Lấy danh sách tất cả preset

## Giao diện GUI

### Connection Panel
- Nhập thông tin kết nối camera (Host, Port, Username, Password)
- Nút Connect/Disconnect

### PTZ Control Panel
- 8 nút điều hướng (↑ ↓ ← → và 4 góc)
- Nút STOP để dừng tất cả chuyển động
- Zoom In/Out buttons
- Focus Near/Far/Auto buttons
- Speed slider (1-8)

### Preset Management Panel
- Danh sách các preset đã lưu
- Nhập Preset ID
- Nút Set Preset, Go To, Delete
- Nút Refresh List

### Status Bar
- Hiển thị trạng thái kết nối và thông báo

## Lưu ý

- Camera phải hỗ trợ MTRPC API
- Đảm bảo kết nối mạng đến camera
- Preset ID hợp lệ: 1-255
- Speed/Step hợp lệ: 1-8

## Troubleshooting

### Không kết nối được
- Kiểm tra IP và port của camera
- Kiểm tra username/password
- Kiểm tra firewall và kết nối mạng

### PTZ không hoạt động
- Kiểm tra camera có hỗ trợ PTZ không
- Kiểm tra quyền user có được phép điều khiển PTZ

### Preset không hiển thị
- Nhấn nút "Refresh List"
- Kiểm tra camera đã có preset nào được lưu chưa

## License

MIT License
