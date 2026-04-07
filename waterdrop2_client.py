import socket
import json
import threading
import time
from urllib.parse import quote

class Waterdrop2Client:
    def __init__(self, ip='192.168.10.10', port=31001):
        self.ip = ip
        self.port = port
        self.sock = None
        self.connected = False
        self.receive_thread = None
        self.status_callback = None  # 状态更新回调函数
        self.data_callback = None  # 非 robot_status 的实时订阅回调
        self.message_callback = None  # 通用消息回调函数
        self.connection_callback = None  # 连接状态变化回调

    def connect(self, timeout=5):
        """连接到底盘 TCP 服务器"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)  # 设置连接超时，防止UI卡死
            self.sock.connect((self.ip, self.port))
            self.sock.settimeout(None)  # 连接成功后恢复为阻塞模式
            self.connected = True
            print(f"[连接成功] 已连接到三帝AI智能底盘控制系统 {self.ip}:{self.port}")

            # 开启接收线程，用于持续监听底盘返回的状态
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            return True
        except Exception as e:
            print(f"[连接失败] 无法连接到底盘: {e}")
            self.connected = False
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None
            return False

    def disconnect(self, reason="用户主动断开", notify=False):
        """断开连接"""
        was_connected = self.connected or self.sock is not None
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            finally:
                self.sock = None
        if was_connected:
            print(f"[断开连接] {reason}")
        if notify and was_connected:
            self._emit_connection_callback(False, reason)

    def _emit_status_callback(self, msg):
        """向上层派发状态消息"""
        if callable(self.status_callback):
            try:
                self.status_callback(msg)
            except Exception as e:
                print(f"[回调错误] 状态回调执行失败: {e}")

    def _emit_message_callback(self, msg):
        """向上层派发通用消息"""
        if callable(self.message_callback):
            try:
                self.message_callback(msg)
            except Exception as e:
                print(f"[回调错误] 通用消息回调执行失败: {e}")

    def _emit_data_callback(self, msg):
        """向上层派发非 robot_status 的实时订阅消息"""
        if callable(self.data_callback):
            try:
                self.data_callback(msg)
            except Exception as e:
                print(f"[回调错误] 实时数据回调执行失败: {e}")

    def _emit_connection_callback(self, connected, reason=""):
        """向上层派发连接状态变化"""
        if callable(self.connection_callback):
            try:
                self.connection_callback({"connected": connected, "reason": reason})
            except Exception as e:
                print(f"[回调错误] 连接状态回调执行失败: {e}")

    def _encode_value(self, value):
        """编码查询参数，兼容中文、空格等特殊字符"""
        return quote(str(value), safe=",")

    def _build_command(self, path, **params):
        """统一构造命令字符串"""
        if not params:
            return path

        query_parts = []
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                value = "true" if value else "false"
            elif isinstance(value, (list, tuple)):
                value = ",".join(str(item) for item in value)
            query_parts.append(f"{key}={self._encode_value(value)}")

        if not query_parts:
            return path
        return f"{path}?{'&'.join(query_parts)}"

    def _receive_loop(self):
        """后台持续接收底盘返回数据的线程"""
        buffer = ""
        while self.connected:
            try:
                data = self.sock.recv(4096)
                if not data:
                    print("[网络断开] 底盘主动关闭了连接")
                    self.disconnect(reason="底盘主动关闭了连接", notify=True)
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

            except socket.error as e:
                if self.connected:
                    print(f"[接收错误] 网络异常: {e}")
                    self.disconnect(reason=f"网络异常: {e}", notify=True)
                break

    def _handle_message(self, msg):
        """处理底盘返回的JSON格式消息"""
        msg_type = msg.get("type")
        
        if msg_type == "response":
            cmd = msg.get("command")
            status = msg.get("status")
            print(f"[收到指令响应] 指令: {cmd}, 状态: {status}")
            
            if cmd == "/api/robot_status" and "results" in msg:
                print(f"  └─ 当前电量: {msg['results'].get('power_percent')}%")
                print(f"  └─ 导航状态: {msg['results'].get('move_status')}")
                self._emit_status_callback(msg)

            self._emit_message_callback(msg)
                
        elif msg_type == "callback":
            topic = msg.get("topic")
            results = msg.get("results", {})
            if topic == "robot_status":
                power = results.get("power_percent")
                move_status = results.get("move_status")
                pose = results.get("current_pose", {})
                print(f"[状态更新] 电量:{power}% 状态:{move_status} 坐标:(x:{pose.get('x')}, y:{pose.get('y')})")
                self._emit_status_callback(msg)
            else:
                print(f"[实时订阅] topic={topic} data={results}")
                self._emit_data_callback(msg)

        elif msg_type == "notification":
            print(f"[系统通知] 状态码: {msg.get('code', '未知')} - {msg.get('description', '')}")
            self._emit_message_callback(msg)
        else:
            pass

    def send_command(self, cmd_str):
        """发送指令到底盘（三帝AI智能底盘控制系统使用类 URL 的命令格式，例如 /api/move?marker=xxx）"""
        if not self.connected:
            print("[发送失败] 未连接到底盘")
            return False
        
        try:
            if not cmd_str.endswith("\n"):
                cmd_str += "\n"
            self.sock.sendall(cmd_str.encode('utf-8'))
            print(f"[发送指令] {cmd_str.strip()}")
            return True
        except Exception as e:
            print(f"[发送失败] {e}")
            return False

    # ================= 1. 机器人移动功能 =================
    def move_to_marker(self, target_name, **options):
        """单目标点移动 (根据标点名称)，支持附带高级导航参数"""
        params = {"marker": target_name}
        params.update(options)
        return self.send_command(self._build_command("/api/move", **params))

    def move_to_location(self, x, y, theta):
        """单目标点移动 (根据绝对坐标)"""
        return self.send_command(self._build_command("/api/move", location=f"{x},{y},{theta}"))

    def move_to_multiple_markers(self, markers_list, distance_tolerance=1.0, count=-1):
        """多目标点巡游移动"""
        return self.send_command(self._build_command(
            "/api/move",
            markers=markers_list,
            distance_tolerance=distance_tolerance,
            count=count,
        ))

    # ================= 2. 移动取消功能 =================
    def cancel_navigation(self):
        """取消当前导航"""
        return self.send_command("/api/move/cancel")

    # ================= 3 & 4. 状态与信息获取 =================
    def get_status(self):
        """获取机器人当前全局状态 (单次)"""
        return self.send_command("/api/robot_status")

    def get_robot_info(self):
        """获取机器人信息 (如序列号、版本等)"""
        return self.send_command("/api/robot_info")

    # ================= 5. 点位 (Marker) 管理功能 =================
    def insert_marker_here(self, name, point_type=0):
        """在机器人当前位置标记marker"""
        return self.send_command(self._build_command("/api/markers/insert", name=name, type=point_type))

    def insert_marker_by_pose(self, name, x, y, theta, floor, point_type=0):
        """指定坐标标记marker"""
        return self.send_command(self._build_command(
            "/api/markers/insert_by_pose",
            name=name,
            x=x,
            y=y,
            theta=theta,
            floor=floor,
            type=point_type,
        ))

    def get_markers_list(self):
        """获取marker点位列表"""
        return self.send_command("/api/markers/query_list")

    def get_markers_brief(self):
        """获取点位摘要信息"""
        return self.send_command("/api/markers/query_brief")

    def get_markers_count(self):
        """获取点位个数"""
        return self.send_command("/api/markers/count")

    def delete_marker(self, name):
        """删除marker点位"""
        return self.send_command(self._build_command("/api/markers/delete", name=name))

    # ================= 6. 机器人直接控制指令 =================
    def move_direct(self, linear_velocity, angular_velocity):
        """直接遥控机器人运动 (线速度m/s, 角速度rad/s)"""
        return self.send_command(self._build_command(
            "/api/joy_control",
            linear_velocity=linear_velocity,
            angular_velocity=angular_velocity,
        ))

    # ================= 7. 机器人急停控制 =================
    def set_estop(self, enable=True):
        """设置软件急停"""
        return self.send_command(self._build_command("/api/estop", flag=enable))

    # ================= 8. 校正位置 =================
    def adjust_position_by_marker(self, marker_name):
        """指定marker校正机器人位置"""
        return self.send_command(self._build_command("/api/position_adjust", marker=marker_name))

    def adjust_position_by_pose(self, x, y, theta):
        """指定坐标校正机器人位置"""
        return self.send_command(self._build_command("/api/position_adjust_by_pose", x=x, y=y, theta=theta))

    # ================= 9. 实时数据请求 (订阅) =================
    def subscribe_data(self, topic="robot_status", frequency=1.0):
        """订阅机器人实时数据 (topic: robot_status, human_detection, robot_velocity)"""
        return self.send_command(self._build_command("/api/request_data", topic=topic, frequency=frequency))

    # ================= 11 & 12. 参数设置与获取 =================
    def set_param(self, param_name, param_value):
        """设置单个机器人运行参数 (如 max_speed_linear)"""
        return self.set_params(**{param_name: param_value})

    def set_params(self, **params):
        """批量设置机器人运行参数"""
        if not params:
            return False
        return self.send_command(self._build_command("/api/set_params", **params))

    def get_params(self):
        """获取机器人运行参数"""
        return self.send_command("/api/get_params")

    # ================= 13. 无线网络接口 =================
    def get_wifi_list(self):
        """获取可用的WiFi列表"""
        return self.send_command("/api/wifi/list")

    def get_wifi_detail_list(self):
        """获取可用的WiFi详细列表"""
        return self.send_command("/api/wifi/detail_list")

    def get_active_wifi(self):
        """获取当前连接的WiFi"""
        return self.send_command("/api/wifi/get_active_connection")

    def get_network_info(self):
        """获取机器人IP和无线网卡地址"""
        return self.send_command("/api/wifi/info")

    def connect_wifi(self, ssid, password):
        """连接WiFi"""
        return self.send_command(self._build_command("/api/wifi/connect", SSID=ssid, password=password))

    # ================= 14. 地图接口 =================
    def get_map_list(self):
        """获取地图列表"""
        return self.send_command("/api/map/list")

    def get_map_list_info(self):
        """获取地图列表详情"""
        return self.send_command("/api/map/list_info")

    def get_current_map(self):
        """获取当前地图"""
        return self.send_command("/api/map/get_current_map")

    def set_current_map(self, map_name, floor=1):
        """设置当前地图"""
        return self.send_command(self._build_command(
            "/api/map/set_current_map",
            hotel_id=map_name,
            map_name=map_name,
            floor=floor,
        ))

    def distance_probe(self, x, y):
        """给定目标点，查询到静态地图障碍和传感器探测障碍物的距离"""
        return self.send_command(self._build_command("/api/map/distance_probe", x=x, y=y))

    def accessible_point_query(self, x, y):
        """给定目标点，在目标点附近寻找可到点的位置"""
        return self.send_command(self._build_command("/api/map/accessible_point_query", x=x, y=y))

    # ================= 15. 关机重启接口 =================
    def shutdown_or_reboot(self, reboot=False):
        """关机或重启"""
        return self.send_command(self._build_command("/api/shutdown", reboot=reboot))

    # ================= 16. 软件更新接口 =================
    def get_software_version(self):
        """获取当前软件版本"""
        return self.send_command("/api/software/get_version")

    def check_for_update(self):
        """检查更新"""
        return self.send_command("/api/software/check_for_update")

    def update_software(self):
        """更新软件"""
        return self.send_command("/api/software/update")

    def restart_software_service(self):
        """重启软件服务"""
        return self.send_command("/api/software/restart")

    # ================= 17. 设置灯带接口 =================
    def set_led_color(self, r, g, b):
        """设置灯带颜色 (r, g, b 取值 0~100)"""
        return self.send_command(self._build_command("/api/LED/set_color", r=r, g=g, b=b))

    def set_led_luminance(self, value):
        """设置灯带亮度 (value 取值 0~100)"""
        return self.send_command(self._build_command("/api/LED/set_luminance", value=value))

    # ================= 18. 自诊断接口 =================
    def get_diagnosis_result(self):
        """获取自诊断结果 (传感器/电机等)"""
        return self.send_command("/api/diagnosis/get_result")

    # ================= 19. 获取电源状态接口 =================
    def get_power_status(self):
        """获取电源详细状态 (电压/电流/电量)"""
        return self.send_command("/api/get_power_status")

    # ================= 20. 获取全局路径接口 =================
    def get_planned_path(self):
        """获取机器人当前规划的全局路径"""
        return self.send_command("/api/get_planned_path")

    # ================= 21. 获取电梯状态接口 =================
    def get_lift_status(self):
        """获取电梯状态"""
        return self.send_command("/api/lift_status")

    # ================= 22. 获取两点间路径接口 =================
    def make_plan(self, start_x, start_y, start_floor, goal_x, goal_y, goal_floor):
        """获取两点间路径 (用于判断是否可达等)"""
        return self.send_command(self._build_command(
            "/api/make_plan",
            start_x=start_x,
            start_y=start_y,
            start_floor=start_floor,
            goal_x=goal_x,
            goal_y=goal_y,
            goal_floor=goal_floor,
        ))


# --- 使用示例 ---
if __name__ == "__main__":
    robot = Waterdrop2Client(ip='192.168.10.10', port=31001)
    
    if robot.connect():
        time.sleep(1)
        
        # 订阅底盘的实时状态（每1秒推送一次，相当于心跳）
        robot.subscribe_data(topic="robot_status", frequency=1.0)
        time.sleep(2)
        
        # 获取一次详细状态
        robot.get_status()
        time.sleep(2)
        
        # 尝试一些新功能：
        # robot.set_led_color(0, 100, 0) # 绿灯
        # robot.get_power_status() # 电源详情
        # robot.get_map_list() # 查看所有地图
        
        try:
            print("进入持续监听模式，按 Ctrl+C 退出...")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            robot.disconnect()
