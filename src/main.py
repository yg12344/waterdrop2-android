"""
水滴2机器人控制台 - Android APK
基于KivyMD构建的机器人遥控应用
"""

from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.button import MDRaisedButton, MDIconButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.label import MDLabel
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.slider import MDSlider
from kivymd.uix.selectioncontrols import MDSwitch
from kivymd.uix.snackbar import Snackbar
from kivy.uix.screenmanager import SlideTransition
from kivymd.uix.floatlayout import MDFloatLayout
from kivymd.uix.progressindicator import MDCircularProgressIndicator

try:
    from kivymd.uix.toolbar import MDTopAppBar
except:
    try:
        from kivymd.uix.toolbar import MDToolbar as MDTopAppBar
    except:
        from kivymd.uix.appbar import MDTopAppBar

from waterdrop2_client import Waterdrop2Client
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
import threading
import traceback

# 模拟手机屏幕大小
Window.size = (360, 640)


class ConnectionScreen(MDScreen):
    """连接屏幕"""
    pass


class ControlScreen(MDScreen):
    """控制主屏幕"""
    pass


class NavigationScreen(MDScreen):
    """导航控制屏幕"""
    pass


class SettingsScreen(MDScreen):
    """设置屏幕"""
    pass


class Waterdrop2App(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.robot = None
        self.connected = False
        self.current_screen_name = 'connection'
        
    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        self.theme_cls.accent_palette = "Orange"
        
        # 创建屏幕管理器
        self.sm = MDScreenManager()
        
        # 连接屏幕
        self.connection_screen = ConnectionScreen(name='connection')
        self.connection_screen.add_widget(self._build_connection_ui())
        self.sm.add_widget(self.connection_screen)
        
        # 主控制屏幕
        self.control_screen = ControlScreen(name='control')
        self.control_screen.add_widget(self._build_control_ui())
        self.sm.add_widget(self.control_screen)
        
        # 导航屏幕
        self.navigation_screen = NavigationScreen(name='navigation')
        self.navigation_screen.add_widget(self._build_navigation_ui())
        self.sm.add_widget(self.navigation_screen)
        
        # 设置屏幕
        self.settings_screen = SettingsScreen(name='settings')
        self.settings_screen.add_widget(self._build_settings_ui())
        self.sm.add_widget(self.settings_screen)
        
        return self.sm

    def _build_connection_ui(self):
        """构建连接界面"""
        layout = MDFloatLayout()
        
        # 顶部工具栏
        toolbar = MDTopAppBar(
            title="水滴2 机器人控制台",
            elevation=4,
            pos_hint={"top": 1}
        )
        layout.add_widget(toolbar)
        
        # 主容器
        container = MDBoxLayout(
            orientation='vertical',
            padding=30,
            spacing=20,
            pos_hint={"top": 0.9}
        )
        
        # Logo/标题区域
        title_card = MDCard(
            orientation='vertical',
            padding=30,
            size_hint=(1, None),
            height=200,
            elevation=0,
            md_bg_color=self.theme_cls.primary_color
        )
        title_card.radius = [30]
        
        icon_label = MDLabel(
            text="🤖",
            font_size="72sp",
            halign="center"
        )
        title_card.add_widget(icon_label)
        
        title_label = MDLabel(
            text="水滴2 控制台",
            font_style="H4",
            halign="center",
            text_color=(1, 1, 1, 1)
        )
        title_card.add_widget(title_label)
        
        version_label = MDLabel(
            text="v1.0.0",
            font_style="Caption",
            halign="center",
            text_color=(1, 1, 1, 0.7)
        )
        title_card.add_widget(version_label)
        
        container.add_widget(title_card)
        
        # 连接卡片
        conn_card = MDCard(
            orientation='vertical',
            padding=20,
            spacing=15,
            size_hint=(1, None),
            height=220,
            elevation=2,
            radius=[20]
        )
        
        conn_title = MDLabel(
            text="网络连接",
            font_style="H6",
            size_hint_y=None,
            height=40
        )
        conn_card.add_widget(conn_title)
        
        self.ip_input = MDTextField(
            hint_text="机器人 IP 地址",
            text="192.168.10.10",
            icon_right="lan",
            size_hint_x=0.9,
            pos_hint={"center_x": 0.5}
        )
        conn_card.add_widget(self.ip_input)
        
        self.port_input = MDTextField(
            hint_text="端口 (默认 31001)",
            text="31001",
            icon_right="serial-port",
            size_hint_x=0.9,
            pos_hint={"center_x": 0.5}
        )
        conn_card.add_widget(self.port_input)
        
        self.conn_btn = MDRaisedButton(
            text="连  接",
            pos_hint={"center_x": 0.5},
            size_hint_x=0.8,
            height=50,
            on_release=self.toggle_connection
        )
        conn_card.add_widget(self.conn_btn)
        
        container.add_widget(conn_card)
        
        # 状态标签
        self.conn_status_label = MDLabel(
            text="未连接",
            halign="center",
            theme_text_color="Secondary"
        )
        container.add_widget(self.conn_status_label)
        
        layout.add_widget(container)
        return layout

    def _build_control_ui(self):
        """构建主控制界面"""
        layout = MDFloatLayout()
        
        # 顶部工具栏
        self.control_toolbar = MDTopAppBar(
            title="控制面板",
            elevation=4,
            pos_hint={"top": 1},
            left_action_items=[["arrow-left", lambda x: self.go_back()]],
            right_action_items=[["cog", lambda x: self.go_to_settings()]]
        )
        layout.add_widget(self.control_toolbar)
        
        container = MDBoxLayout(
            orientation='vertical',
            padding=15,
            spacing=15,
            pos_hint={"top": 0.92}
        )
        
        # 状态卡片
        status_card = MDCard(
            orientation='horizontal',
            padding=15,
            size_hint=(1, None),
            height=100,
            elevation=2,
            radius=[15]
        )
        
        # 电量显示
        battery_box = MDBoxLayout(orientation='vertical', size_hint_x=0.25)
        self.battery_icon = MDIconButton(icon="battery", icon_size="32sp")
        self.battery_label = MDLabel(text="--%", halign="center", font_style="Caption")
        battery_box.add_widget(self.battery_icon)
        battery_box.add_widget(self.battery_label)
        status_card.add_widget(battery_box)
        
        # 状态信息
        info_box = MDBoxLayout(orientation='vertical', size_hint_x=0.5)
        self.status_label = MDLabel(text="未连接", font_style="Body1")
        self.pose_label = MDLabel(text="位置: --", font_style="Caption", theme_text_color="Secondary")
        info_box.add_widget(self.status_label)
        info_box.add_widget(self.pose_label)
        status_card.add_widget(info_box)
        
        # 急停按钮
        self.estop_btn = MDRaisedButton(
            text="急停",
            md_bg_color=(1, 0, 0, 1),
            size_hint_x=0.25,
            on_release=self.trigger_estop
        )
        status_card.add_widget(self.estop_btn)
        
        container.add_widget(status_card)
        
        # 方向控制卡片
        ctrl_card = MDCard(
            orientation='vertical',
            padding=15,
            size_hint=(1, None),
            height=280,
            elevation=2,
            radius=[15]
        )
        
        ctrl_title = MDLabel(
            text="直接控制 (Joy Control)",
            font_style="H6",
            size_hint_y=None,
            height=35
        )
        ctrl_card.add_widget(ctrl_title)
        
        # 九宫格方向键
        from kivy.uix.gridlayout import GridLayout
        grid = GridLayout(cols=3, rows=3, spacing=8, size_hint=(1, 1))
        
        btn_configs = [
            ("arrow-top-left", 0.4, 0.6), ("arrow-up-bold", 0.5, 0.0), ("arrow-top-right", 0.4, -0.6),
            ("rotate-left", 0.0, 0.8),    ("stop-circle-outline", 0.0, 0.0), ("rotate-right", 0.0, -0.8),
            ("arrow-bottom-left", -0.4, 0.6), ("arrow-down-bold", -0.5, 0.0), ("arrow-bottom-right", -0.4, -0.6)
        ]
        
        for icon, linear, angular in btn_configs:
            if icon == "stop-circle-outline":
                btn = MDIconButton(
                    icon=icon, 
                    icon_size="40sp", 
                    theme_text_color="Custom", 
                    text_color=(1, 0, 0, 1),
                    md_bg_color=(0.95, 0.95, 0.95, 1)
                )
            else:
                btn = MDIconButton(
                    icon=icon, 
                    icon_size="40sp",
                    md_bg_color=(0.9, 0.95, 1, 1)
                )
            btn.bind(on_press=lambda instance, l=linear, a=angular: self.send_joy_control(l, a))
            btn.bind(on_release=lambda instance: self.send_joy_control(0.0, 0.0))
            grid.add_widget(btn)
            
        ctrl_card.add_widget(grid)
        container.add_widget(ctrl_card)
        
        # 底部导航按钮
        nav_card = MDCard(
            orientation='horizontal',
            padding=10,
            size_hint=(1, None),
            height=60,
            elevation=2,
            radius=[15]
        )
        
        nav_btn1 = MDFlatButton(
            text="控制",
            icon="gamepad",
            on_release=lambda x: self.switch_to("control")
        )
        nav_btn2 = MDFlatButton(
            text="导航",
            icon="navigation",
            on_release=lambda x: self.switch_to("navigation")
        )
        nav_btn3 = MDFlatButton(
            text="设置",
            icon="cog",
            on_release=lambda x: self.switch_to("settings")
        )
        
        nav_card.add_widget(nav_btn1)
        nav_card.add_widget(nav_btn2)
        nav_card.add_widget(nav_btn3)
        container.add_widget(nav_card)
        
        layout.add_widget(container)
        return layout

    def _build_navigation_ui(self):
        """构建导航界面"""
        layout = MDFloatLayout()
        
        toolbar = MDTopAppBar(
            title="导航控制",
            elevation=4,
            pos_hint={"top": 1},
            left_action_items=[["arrow-left", lambda x: self.go_back()]],
            right_action_items=[["refresh", lambda x: self.refresh_markers()]]
        )
        layout.add_widget(toolbar)
        
        container = MDBoxLayout(
            orientation='vertical',
            padding=15,
            spacing=15,
            pos_hint={"top": 0.92}
        )
        
        # 导航操作卡片
        nav_ops_card = MDCard(
            orientation='vertical',
            padding=15,
            size_hint=(1, None),
            height=150,
            elevation=2,
            radius=[15]
        )
        
        nav_ops_card.add_widget(MDLabel(text="导航操作", font_style="H6", size_hint_y=None, height=35))
        
        coord_box = MDBoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=50)
        self.x_input = MDTextField(hint_text="X", size_hint_x=0.33)
        self.y_input = MDTextField(hint_text="Y", size_hint_x=0.33)
        self.theta_input = MDTextField(hint_text="θ", size_hint_x=0.33)
        coord_box.add_widget(self.x_input)
        coord_box.add_widget(self.y_input)
        coord_box.add_widget(self.theta_input)
        nav_ops_card.add_widget(coord_box)
        
        btn_box = MDBoxLayout(orientation='horizontal', spacing=10, size_hint_y=None, height=50)
        go_btn = MDRaisedButton(text="前往坐标", on_release=self.go_to_coord)
        cancel_btn = MDRaisedButton(text="取消导航", on_release=self.cancel_nav)
        btn_box.add_widget(go_btn)
        btn_box.add_widget(cancel_btn)
        nav_ops_card.add_widget(btn_box)
        
        container.add_widget(nav_ops_card)
        
        # Marker列表卡片
        markers_card = MDCard(
            orientation='vertical',
            padding=15,
            size_hint=(1, 1),
            elevation=2,
            radius=[15]
        )
        
        markers_card.add_widget(MDLabel(text="目标点 (Markers)", font_style="H6", size_hint_y=None, height=35))
        
        from kivy.uix.scrollview import ScrollView
        from kivy.uix.listview import ListView
        
        self.marker_list = ListView(item_strings=["加载中..."])
        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(self.marker_list)
        markers_card.add_widget(scroll)
        
        container.add_widget(markers_card)
        
        # 底部导航
        nav_card = MDCard(
            orientation='horizontal',
            padding=10,
            size_hint=(1, None),
            height=60,
            elevation=2,
            radius=[15]
        )
        
        nav_card.add_widget(MDFlatButton(text="控制", icon="gamepad", on_release=lambda x: self.switch_to("control")))
        nav_card.add_widget(MDFlatButton(text="导航", icon="navigation"))
        nav_card.add_widget(MDFlatButton(text="设置", icon="cog", on_release=lambda x: self.switch_to("settings")))
        
        container.add_widget(nav_card)
        
        layout.add_widget(container)
        return layout

    def _build_settings_ui(self):
        """构建设置界面"""
        layout = MDFloatLayout()
        
        toolbar = MDTopAppBar(
            title="设置",
            elevation=4,
            pos_hint={"top": 1},
            left_action_items=[["arrow-left", lambda x: self.go_back()]]
        )
        layout.add_widget(toolbar)
        
        container = MDBoxLayout(
            orientation='vertical',
            padding=15,
            spacing=15,
            pos_hint={"top": 0.92}
        )
        
        # 机器人信息卡片
        info_card = MDCard(
            orientation='vertical',
            padding=15,
            size_hint=(1, None),
            height=120,
            elevation=2,
            radius=[15]
        )
        
        info_card.add_widget(MDLabel(text="机器人信息", font_style="H6", size_hint_y=None, height=35))
        self.robot_info_label = MDLabel(text="点击刷新获取信息", theme_text_color="Secondary")
        info_card.add_widget(self.robot_info_label)
        
        refresh_btn = MDRaisedButton(text="刷新信息", on_release=self.refresh_robot_info)
        info_card.add_widget(refresh_btn)
        
        container.add_widget(info_card)
        
        # 灯光控制卡片
        led_card = MDCard(
            orientation='vertical',
            padding=15,
            size_hint=(1, None),
            height=180,
            elevation=2,
            radius=[15]
        )
        
        led_card.add_widget(MDLabel(text="灯光控制", font_style="H6", size_hint_y=None, height=35))
        
        self.led_r = MDSlider(min=0, max=100, value=0, hint_text="红")
        self.led_g = MDSlider(min=0, max=100, value=0, hint_text="绿")
        self.led_b = MDSlider(min=0, max=100, value=0, hint_text="蓝")
        
        led_card.add_widget(self.led_r)
        led_card.add_widget(self.led_g)
        led_card.add_widget(self.led_b)
        
        led_btn = MDRaisedButton(text="设置灯光", on_release=self.set_led)
        led_card.add_widget(led_btn)
        
        container.add_widget(led_card)
        
        # 系统操作卡片
        sys_card = MDCard(
            orientation='vertical',
            padding=15,
            size_hint=(1, None),
            height=180,
            elevation=2,
            radius=[15]
        )
        
        sys_card.add_widget(MDLabel(text="系统操作", font_style="H6", size_hint_y=None, height=35))
        
        diag_btn = MDRaisedButton(text="自诊断", on_release=self.run_diagnosis)
        sys_card.add_widget(diag_btn)
        
        reboot_btn = MDRaisedButton(text="重启软件", on_release=self.reboot_software)
        sys_card.add_widget(reboot_btn)
        
        shutdown_btn = MDRaisedButton(text="关机", md_bg_color=(1, 0, 0, 1), on_release=self.shutdown_robot)
        sys_card.add_widget(shutdown_btn)
        
        container.add_widget(sys_card)
        
        # 底部导航
        nav_card = MDCard(
            orientation='horizontal',
            padding=10,
            size_hint=(1, None),
            height=60,
            elevation=2,
            radius=[15]
        )
        
        nav_card.add_widget(MDFlatButton(text="控制", icon="gamepad", on_release=lambda x: self.switch_to("control")))
        nav_card.add_widget(MDFlatButton(text="导航", icon="navigation", on_release=lambda x: self.switch_to("navigation")))
        nav_card.add_widget(MDFlatButton(text="设置", icon="cog"))
        
        container.add_widget(nav_card)
        
        layout.add_widget(container)
        return layout

    def toggle_connection(self, instance):
        """切换连接状态"""
        if self.connected:
            self.disconnect_robot()
        else:
            self.connect_robot()

    def connect_robot(self):
        """连接机器人"""
        ip = self.ip_input.text.strip()
        port = int(self.port_input.text.strip() or "31001")
        
        self.conn_btn.text = "连接中..."
        self.conn_btn.disabled = True
        
        threading.Thread(target=self._connect_task, args=(ip, port), daemon=True).start()

    def _connect_task(self, ip, port):
        """连接任务"""
        self.robot = Waterdrop2Client(ip=ip, port=port)
        
        def on_result(success):
            if success:
                self.connected = True
                self.conn_btn.text = "断开"
                self.conn_btn.md_bg_color = (1, 0, 0, 1)
                self.conn_status_label.text = f"已连接到 {ip}"
                self.conn_status_label.text_color = (0, 0.5, 0, 1)
                Snackbar(text="连接成功!").open()
                
                # 设置回调
                self.robot.set_status_callback(self.on_status_update)
                
                # 订阅状态
                self.robot.subscribe_data(topic="robot_status", frequency=1.0)
                self.robot.get_status()
                
                # 切换到控制界面
                Clock.schedule_once(lambda dt: self.switch_to("control"))
            else:
                self.conn_btn.text = "连接"
                self.conn_status_label.text = "连接失败，请检查IP和网络"
                self.conn_status_label.text_color = (1, 0, 0, 1)
                Snackbar(text="连接失败!").open()
            
            self.conn_btn.disabled = False
        
        success = self.robot.connect()
        Clock.schedule_once(lambda dt: on_result(success))

    def disconnect_robot(self):
        """断开连接"""
        if self.robot:
            self.robot.disconnect()
        self.connected = False
        self.conn_btn.text = "连接"
        self.conn_btn.md_bg_color = self.theme_cls.primary_color
        self.conn_status_label.text = "未连接"
        self.switch_to("connection")

    def on_status_update(self, status):
        """状态更新回调"""
        Clock.schedule_once(lambda dt: self._update_status_ui(status))

    def _update_status_ui(self, status):
        """更新状态UI"""
        power = status.get('power', 0)
        move_status = status.get('move_status', '')
        pose = status.get('pose', {})
        
        self.battery_label.text = f"{power}%"
        
        if power > 50:
            self.battery_icon.icon = "battery"
        elif power > 20:
            self.battery_icon.icon = "battery-50"
        else:
            self.battery_icon.icon = "battery-alert"
        
        self.status_label.text = f"状态: {move_status}"
        
        if pose:
            x = pose.get('x', 0)
            y = pose.get('y', 0)
            self.pose_label.text = f"位置: ({x:.2f}, {y:.2f})"

    def send_joy_control(self, linear, angular):
        """发送遥控指令"""
        if self.robot and self.connected:
            self.robot.move_direct(linear, angular)

    def trigger_estop(self, instance):
        """触发急停"""
        if self.robot and self.connected:
            self.robot.set_estop(True)
            Snackbar(text="急停已触发!").open()

    def go_to_coord(self, instance):
        """前往坐标"""
        try:
            x = float(self.x_input.text)
            y = float(self.y_input.text)
            theta = float(self.theta_input.text or "0")
            
            if self.robot and self.connected:
                self.robot.move_to_location(x, y, theta)
                Snackbar(text=f"正在前往 ({x}, {y})...").open()
        except ValueError:
            Snackbar(text="请输入有效的坐标值").open()

    def cancel_nav(self, instance):
        """取消导航"""
        if self.robot and self.connected:
            self.robot.cancel_navigation()
            Snackbar(text="导航已取消").open()

    def refresh_markers(self):
        """刷新Marker列表"""
        if self.robot and self.connected:
            self.robot.get_markers_list()
            Snackbar(text="正在刷新目标点...").open()

    def refresh_robot_info(self, instance):
        """刷新机器人信息"""
        if self.robot and self.connected:
            self.robot.get_robot_info()
            self.robot.get_power_status()
            Snackbar(text="正在获取信息...").open()

    def set_led(self, instance):
        """设置LED灯光"""
        if self.robot and self.connected:
            r = int(self.led_r.value)
            g = int(self.led_g.value)
            b = int(self.led_b.value)
            self.robot.set_led_color(r, g, b)
            Snackbar(text=f"灯光: RGB({r}, {g}, {b})").open()

    def run_diagnosis(self, instance):
        """运行自诊断"""
        if self.robot and self.connected:
            self.robot.get_diagnosis_result()
            Snackbar(text="正在自诊断...").open()

    def reboot_software(self, instance):
        """重启软件"""
        if self.robot and self.connected:
            self.robot.restart_software_service()
            Snackbar(text="正在重启软件...").open()

    def shutdown_robot(self, instance):
        """关闭机器人"""
        if self.robot and self.connected:
            self.robot.shutdown_or_reboot(reboot=False)
            Snackbar(text="正在关机...").open()

    def switch_to(self, screen_name):
        """切换屏幕"""
        self.current_screen_name = screen_name
        self.sm.current = screen_name

    def go_back(self):
        """返回"""
        if self.connected:
            self.switch_to("control")
        else:
            self.switch_to("connection")


if __name__ == '__main__':
    try:
        Waterdrop2App().run()
    except Exception as e:
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(f"应用崩溃:\n{traceback.format_exc()}")
        print(f"应用崩溃: {e}")
