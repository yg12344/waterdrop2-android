"""
水滴2机器人 TCP 客户端
用于Android APK与机器人通信
"""

import socket
import json
import threading
import time

class Waterdrop2Client:
    def __init__(self, ip='192.168.10.10', port=31001):
        self.ip = ip
        self.port = port
        self.sock = None
        self.connected = False
        self.receive_thread = None
        self._status_callback = None
        self._notification_callback = None

    def set_status_callback(self, callback):
        """设置状态回调函数"""
        self._status_callback = callback

    def set_notification_callback(self, callback):
        """设置通知回调函数"""
        self._notification_callback = callback

    def connect(self, timeout=5):
        """连接到底盘 TCP 服务器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((self.ip, self.port))
            self.sock.settimeout(None)
            self.connected = True
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            return True
        except Exception as e:
            self.connected = False
            return False

    def disconnect(self):
        """断开连接"""
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

    def _receive_loop(self):
        """后台持续接收底盘返回数据的线程"""
        buffer = ""
        while self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                
                buffer += data.decode('utf-8')
                
                while True:
                    buffer = buffer.lstrip()
                    if not buffer:
                        break
                    
                    try:
                        decoder = json.JSONDecoder()
                        msg, index = decoder.raw_decode(buffer)
                        self._handle_message(msg)
                        buffer = buffer[index:]
                    except json.JSONDecodeError:
                        break
            except:
                if self.connected:
                    self.disconnect()
                break

    def _handle_message(self, msg):
        """处理底盘返回的JSON格式消息"""
        msg_type = msg.get("type")
        
        if msg_type == "response":
            cmd = msg.get("command")
            status = msg.get("status")
            
        elif msg_type == "callback":
            topic = msg.get("topic")
            if topic == "robot_status" and self._status_callback:
                results = msg.get("results", {})
                self._status_callback({
                    'power': results.get("power_percent", 0),
                    'move_status': results.get("move_status", ""),
                    'pose': results.get("current_pose", {}),
                    'velocity': results.get("robot_velocity", {})
                })
                
        elif msg_type == "notification":
            if self._notification_callback:
                self._notification_callback({
                    'code': msg.get('code', ''),
                    'description': msg.get('description', '')
                })

    def send_command(self, cmd_str):
        """发送指令到底盘"""
        if not self.connected:
            return False
        
        try:
            if not cmd_str.endswith("\n"):
                cmd_str += "\n"
            self.sock.sendall(cmd_str.encode('utf-8'))
            return True
        except:
            return False

    # ================= 1. 机器人移动功能 =================
    def move_to_marker(self, target_name):
        """单目标点移动 (根据标点名称)"""
        self.send_command(f"/api/move?marker={target_name}")

    def move_to_location(self, x, y, theta):
        """单目标点移动 (根据绝对坐标)"""
        self.send_command(f"/api/move?location={x},{y},{theta}")

    def move_to_multiple_markers(self, markers_list, distance_tolerance=1.0, count=-1):
        """多目标点巡游移动"""
        markers_str = ",".join(markers_list)
        self.send_command(f"/api/move?markers={markers_str}&distance_tolerance={distance_tolerance}&count={count}")

    # ================= 2. 移动取消功能 =================
    def cancel_navigation(self):
        """取消当前导航"""
        self.send_command("/api/cancel_move")

    # ================= 3 & 4. 状态与信息获取 =================
    def get_status(self):
        """获取机器人当前全局状态"""
        self.send_command("/api/robot_status")

    def get_robot_info(self):
        """获取机器人信息"""
        self.send_command("/api/robot_info")

    # ================= 5. 点位 (Marker) 管理功能 =================
    def insert_marker_here(self, name, point_type=0):
        """在机器人当前位置标记marker"""
        self.send_command(f"/api/markers/insert?name={name}&type={point_type}")

    def insert_marker_by_pose(self, name, x, y, theta, floor, point_type=0):
        """指定坐标标记marker"""
        self.send_command(f"/api/markers/insert_by_pose?name={name}&x={x}&y={y}&theta={theta}&floor={floor}&type={point_type}")

    def get_markers_list(self):
        """获取marker点位列表"""
        self.send_command("/api/markers/query_list")

    def get_markers_brief(self):
        """获取点位摘要信息"""
        self.send_command("/api/markers/query_brief")

    def get_markers_count(self):
        """获取点位个数"""
        self.send_command("/api/markers/count")

    def delete_marker(self, name):
        """删除marker点位"""
        self.send_command(f"/api/markers/delete?name={name}")

    # ================= 6. 机器人直接控制指令 =================
    def move_direct(self, linear_velocity, angular_velocity):
        """直接遥控机器人运动"""
        self.send_command(f"/api/joy_control?linear_velocity={linear_velocity}&angular_velocity={angular_velocity}")

    # ================= 7. 机器人急停控制 =================
    def set_estop(self, enable=True):
        """设置软件急停"""
        flag_str = "true" if enable else "false"
        self.send_command(f"/api/estop?flag={flag_str}")

    # ================= 8. 校正位置 =================
    def adjust_position_by_marker(self, marker_name):
        """指定marker校正机器人位置"""
        self.send_command(f"/api/position_adjust?marker={marker_name}")

    def adjust_position_by_pose(self, x, y, theta):
        """指定坐标校正机器人位置"""
        self.send_command(f"/api/position_adjust_by_pose?x={x}&y={y}&theta={theta}")

    # ================= 9. 实时数据请求 =================
    def subscribe_data(self, topic="robot_status", frequency=1.0):
        """订阅机器人实时数据"""
        self.send_command(f"/api/request_data?topic={topic}&frequency={frequency}")

    # ================= 11 & 12. 参数设置与获取 =================
    def set_param(self, param_name, param_value):
        """设置机器人运行参数"""
        self.send_command(f"/api/set_params?{param_name}={param_value}")

    def get_params(self):
        """获取机器人运行参数"""
        self.send_command("/api/get_params")

    # ================= 13. 无线网络接口 =================
    def get_wifi_list(self):
        """获取可用的WiFi列表"""
        self.send_command("/api/wifi/list")

    def get_active_wifi(self):
        """获取当前连接的WiFi"""
        self.send_command("/api/wifi/get_active_connection")

    def get_network_info(self):
        """获取机器人IP和无线网卡地址"""
        self.send_command("/api/wifi/info")

    def connect_wifi(self, ssid, password):
        """连接WiFi"""
        self.send_command(f"/api/wifi/connect?SSID={ssid}&password={password}")

    # ================= 14. 地图接口 =================
    def get_map_list(self):
        """获取地图列表"""
        self.send_command("/api/map/list")

    def get_current_map(self):
        """获取当前地图"""
        self.send_command("/api/map/get_current_map")
        
    def set_current_map(self, map_name, floor=1):
        """设置当前地图"""
        self.send_command(f"/api/map/set_current_map?map_name={map_name}&floor={floor}")

    # ================= 15. 关机重启接口 =================
    def shutdown_or_reboot(self, reboot=False):
        """关机或重启"""
        cmd = f"/api/shutdown?reboot={'true' if reboot else 'false'}"
        self.send_command(cmd)

    # ================= 17. 设置灯带接口 =================
    def set_led_color(self, r, g, b):
        """设置灯带颜色 (r, g, b 取值 0~100)"""
        self.send_command(f"/api/LED/set_color?r={r}&g={g}&b={b}")

    def set_led_luminance(self, value):
        """设置灯带亮度 (value 取值 0~100)"""
        self.send_command(f"/api/LED/set_luminance?value={value}")

    # ================= 18. 自诊断接口 =================
    def get_diagnosis_result(self):
        """获取自诊断结果"""
        self.send_command("/api/diagnosis/get_result")

    # ================= 19. 获取电源状态接口 =================
    def get_power_status(self):
        """获取电源详细状态"""
        self.send_command("/api/get_power_status")

    # ================= 21. 获取电梯状态接口 =================
    def get_lift_status(self):
        """获取电梯状态"""
        self.send_command("/api/lift_status")
