from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.button import MDRaisedButton, MDIconButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.label import MDLabel
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.spinner import MDSpinner
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import ScreenManager, NoTransition
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.utils import platform
import json
import os
import re
import threading
import time
import traceback

APP_ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", "sd_icon.png")
CHARGE_DOCK_TYPE = 11
CHARGE_DOCK_KEYWORDS = ("charge", "dock", "charger", "充电", "回充")
LIVE_SUBSCRIPTION_TOPICS = (
    ("robot_status", 1.0),
    ("robot_velocity", 2.0),
    ("human_detection", 1.0),
)

# 兼容不同版本 KivyMD 的 Toolbar 导入

try:
    from kivymd.uix.toolbar import MDTopAppBar
except ImportError:
    try:
        from kivymd.uix.toolbar import MDToolbar as MDTopAppBar
    except ImportError:
        from kivymd.uix.appbar import MDTopAppBar

from waterdrop2_client import Waterdrop2Client


def configure_android_fonts():
    """在 Android 上启用系统中文字体，避免标题和标签显示方块字"""
    if platform != "android":
        return

    font_path = "/system/fonts/NotoSansCJK-Regular.ttc"
    for font_name in ("Roboto", "RobotoThin", "RobotoLight", "RobotoMedium"):
        try:
            LabelBase.register(font_name, font_path)
        except Exception:
            pass


class RobotControllerApp(MDApp):

    # ------------------------------------------------------------------ #
    # Tab 配置表：(key, 显示标签, 图标)
    # ------------------------------------------------------------------ #
    _TABS = [
        ("home",    "首页",   "home-outline"),
        ("status",  "状态",   "information-outline"),
        ("control", "直控",   "gamepad-variant-outline"),
        ("profile", "速度",   "speedometer-slow"),
        ("function","快操",   "lightning-bolt-outline"),
        ("wifi",    "WiFi",   "wifi"),
        ("map",     "地图",   "map-outline"),
        ("plan",    "规划",   "map-search-outline"),
        ("system",  "系统",   "cog-outline"),
        ("cruise",  "巡游",   "routes"),
        ("danger",  "高危",   "alert-octagon-outline"),
    ]

    def build(self):
        configure_android_fonts()
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        self.robot = None
        self.dialog = None
        self.status_update_event = None
        self.last_status = {}
        self.speed_params = {}
        self.linear_speed_limit = 0.45
        self.angular_speed_limit = 1.20
        self.marker_cache = []
        self.charge_dock_marker_name = ""
        self.latest_velocity_payload = {}
        self.latest_human_detection_payload = {}
        self.auto_charge_triggered = False
        self.auto_charge_lookup_in_progress = False
        self.last_auto_charge_lookup_at = 0.0
        self.silent_marker_refresh = False
        self.silent_params_refresh = False
        self.main_scroll = None
        self.section_targets = {}
        self.auto_height_cards = []
        self.responsive_rows = []
        self.responsive_grids = []
        self.sections_grid = None
        self._tab_buttons = {}          # key → MDFlatButton
        self._current_page = "home"
        # 直控连续运动相关
        self._joy_control_active = False
        self._joy_control_linear = 0.0
        self._joy_control_angular = 0.0
        self._joy_control_event = None
        if os.path.exists(APP_ICON_PATH):
            self.icon = APP_ICON_PATH

        screen = MDScreen()
        root_layout = MDBoxLayout(orientation="vertical")

        # ── 顶部标题栏 ──────────────────────────────────────────────────
        self.toolbar = MDTopAppBar(
            title="三帝AI智能底盘控制系统",
            elevation=4,
            size_hint_y=None,
            height=dp(50),
        )
        root_layout.add_widget(self.toolbar)

        # ── Tab 导航栏（可横向滚动）──────────────────────────────────────
        tab_bar_scroll = ScrollView(
            do_scroll_y=False,
            do_scroll_x=True,
            bar_width=0,
            size_hint=(1, None),
            height=dp(46),
        )
        tab_bar_inner = MDBoxLayout(
            orientation="horizontal",
            spacing=dp(2),
            padding=[dp(4), dp(4), dp(4), dp(4)],
            size_hint=(None, 1),
        )
        tab_bar_inner.bind(minimum_width=tab_bar_inner.setter("width"))

        for key, label, _ in self._TABS:
            btn = MDFlatButton(
                text=label,
                size_hint=(None, 1),
                width=dp(62),
                on_release=lambda inst, k=key: self._switch_page(k),
            )
            self._tab_buttons[key] = btn
            tab_bar_inner.add_widget(btn)

        tab_bar_scroll.add_widget(tab_bar_inner)

        tab_bar_wrap = MDBoxLayout(
            orientation="vertical",
            size_hint=(1, None),
            height=dp(46),
            md_bg_color=(0.95, 0.97, 1.0, 1),
        )
        tab_bar_wrap.add_widget(tab_bar_scroll)
        root_layout.add_widget(tab_bar_wrap)

        # ── ScreenManager ───────────────────────────────────────────────
        self.sm = ScreenManager(transition=NoTransition())

        # ── 逐页构建 ────────────────────────────────────────────────────
        self._build_page_home()
        self._build_page_status()
        self._build_page_control()
        self._build_page_profile()
        self._build_page_function()
        self._build_page_wifi()
        self._build_page_map()
        self._build_page_plan()
        self._build_page_system()
        self._build_page_cruise()
        self._build_page_danger()

        root_layout.add_widget(self.sm)
        screen.add_widget(root_layout)

        # 初始高亮首页 Tab
        self._switch_page("home")

        Window.bind(size=self._apply_responsive_layout)
        Clock.schedule_once(self._sync_dashboard_overview, 0)
        Clock.schedule_once(self._apply_responsive_layout, 0)

        return screen

    # ================================================================== #
    # Tab 切换辅助
    # ================================================================== #
    def _switch_page(self, key):
        """切换到指定 key 对应的页面并高亮 Tab 按钮。"""
        self._current_page = key
        self.sm.current = key
        for k, btn in self._tab_buttons.items():
            if k == key:
                btn.md_bg_color = (0.18, 0.49, 0.9, 1)
                btn.theme_text_color = "Custom"
                btn.text_color = (1, 1, 1, 1)
            else:
                btn.md_bg_color = (0, 0, 0, 0)
                btn.theme_text_color = "Primary"
                btn.text_color = self.theme_cls.text_color

    def _make_page_scroll(self, page_key):
        """创建一个带 ScrollView 的 MDScreen，返回 (screen, content_box)。"""
        pg = MDScreen(name=page_key)
        sv = ScrollView(do_scroll_x=False, bar_width=dp(5))
        box = MDBoxLayout(
            orientation="vertical",
            padding=[dp(12), dp(10), dp(12), dp(16)],
            spacing=dp(12),
            size_hint_y=None,
        )
        box.bind(minimum_height=box.setter("height"))
        sv.add_widget(box)
        pg.add_widget(sv)
        self.sm.add_widget(pg)
        return box

    # ================================================================== #
    # 页面 0：首页
    # ================================================================== #
    def _build_page_home(self):
        box = self._make_page_scroll("home")

        # —— 连接卡 ——
        conn_card = MDCard(
            orientation="vertical",
            padding=dp(14),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=4,
            radius=[20],
            md_bg_color=(0.96, 0.98, 1, 1),
        )
        conn_card.bind(minimum_height=conn_card.setter("height"))
        conn_card.add_widget(MDLabel(
            text="连接设备",
            font_style="H6",
            theme_text_color="Primary",
            size_hint_y=None,
            height=dp(30),
        ))
        self.dashboard_primary_status = MDLabel(
            text="当前状态：未连接",
            theme_text_color="Primary",
            bold=True,
            size_hint_y=None,
            height=dp(26),
        )
        conn_card.add_widget(self.dashboard_primary_status)
        self.dashboard_notice_value = MDLabel(
            text="最近操作：--",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(40),
        )
        conn_card.add_widget(self.dashboard_notice_value)
        self.ip_input = MDTextField(
            text="192.168.10.10",
            hint_text="机器人 IP 地址",
            icon_right="lan",
            mode="rectangle",
        )
        conn_card.add_widget(self.ip_input)
        self.conn_btn = MDRaisedButton(
            text="连接设备",
            size_hint=(1, None),
            height=dp(44),
            on_release=self.toggle_connection,
            md_bg_color=(0.2, 0.5, 0.9, 1),
        )
        conn_card.add_widget(self.conn_btn)
        box.add_widget(conn_card)

        # —— 摘要指标卡 ——
        metrics_card = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
            size_hint=(1, None),
            elevation=2,
            radius=[16],
            md_bg_color=(1, 1, 1, 1),
        )
        metrics_card.bind(minimum_height=metrics_card.setter("height"))
        metrics_card.add_widget(MDLabel(
            text="实时概览",
            font_style="Subtitle1",
            theme_text_color="Primary",
            size_hint_y=None,
            height=dp(28),
        ))
        self.dashboard_metrics_grid = GridLayout(
            cols=2,
            spacing=dp(8),
            size_hint_y=None,
        )
        self.dashboard_metrics_grid.bind(minimum_height=self.dashboard_metrics_grid.setter("height"))
        self._register_responsive_grid(self.dashboard_metrics_grid, [(0, 2), (560, 3), (860, 4)])
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("连接", "dashboard_connection_value", "未连接"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("电量", "dashboard_power_value", "--"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("地图", "dashboard_map_value", "--"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("WiFi", "dashboard_wifi_value", "--"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("运动", "dashboard_motion_value", "--"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("姿态", "dashboard_pose_value", "--"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("实测速", "dashboard_velocity_value", "等待数据"))
        self.dashboard_metrics_grid.add_widget(self._create_dashboard_metric_card("人检测", "dashboard_human_value", "暂无数据"))
        metrics_card.add_widget(self.dashboard_metrics_grid)
        box.add_widget(metrics_card)

        # —— 一键工作台 ——
        scene_card = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
            size_hint=(1, None),
            elevation=2,
            radius=[18],
            md_bg_color=(1, 1, 1, 1),
        )
        scene_card.bind(minimum_height=scene_card.setter("height"))
        scene_card.add_widget(MDLabel(
            text="一键工作台",
            font_style="Subtitle1",
            theme_text_color="Primary",
            size_hint_y=None,
            height=dp(28),
        ))
        scene_card.add_widget(MDLabel(
            text="把高频流程折叠成 4 个入口，现场少翻页。",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(22),
        ))
        self.dashboard_scene_grid = GridLayout(
            cols=2,
            spacing=dp(8),
            size_hint_y=None,
        )
        self.dashboard_scene_grid.bind(minimum_height=self.dashboard_scene_grid.setter("height"))
        self._register_responsive_grid(self.dashboard_scene_grid, [(0, 2), (940, 4)])
        self.dashboard_scene_grid.add_widget(self._create_scene_button("联机巡检", lambda x: self.run_readiness_check_action(), (0.21, 0.53, 0.85, 1)))
        self.dashboard_scene_grid.add_widget(self._create_scene_button("地图作业", lambda x: self.open_navigation_workspace_action(), (0.35, 0.58, 0.47, 1)))
        self.dashboard_scene_grid.add_widget(self._create_scene_button("网络维护", lambda x: self.open_network_workspace_action(), (0.48, 0.48, 0.76, 1)))
        self.dashboard_scene_grid.add_widget(self._create_scene_button("安全处置", lambda x: self.open_safety_workspace_action(), (0.86, 0.35, 0.26, 1)))
        scene_card.add_widget(self.dashboard_scene_grid)
        box.add_widget(scene_card)

        # —— 常用快捷按钮 ——
        quick_card = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
            size_hint=(1, None),
            elevation=2,
            radius=[16],
            md_bg_color=(0.97, 0.99, 1, 1),
        )
        quick_card.bind(minimum_height=quick_card.setter("height"))
        quick_card.add_widget(MDLabel(
            text="常用快捷",
            font_style="Subtitle1",
            theme_text_color="Primary",
            size_hint_y=None,
            height=dp(28),
        ))
        self.dashboard_quick_grid = GridLayout(
            cols=2,
            spacing=dp(8),
            size_hint_y=None,
        )
        self.dashboard_quick_grid.bind(minimum_height=self.dashboard_quick_grid.setter("height"))
        self._register_responsive_grid(self.dashboard_quick_grid, [(0, 2), (540, 3)])
        self.dashboard_quick_grid.add_widget(self._create_action_button("获取状态", lambda x: self.get_robot_status(), (0.25, 0.55, 0.85, 1), size_hint_x=1))
        self.dashboard_quick_grid.add_widget(self._create_action_button("当前地图", lambda x: self.get_current_map_info(), (0.35, 0.55, 0.8, 1), size_hint_x=1))
        self.dashboard_quick_grid.add_widget(self._create_action_button("当前网络", lambda x: self.get_active_wifi_info(), (0.35, 0.6, 0.45, 1), size_hint_x=1))
        self.dashboard_quick_grid.add_widget(self._create_action_button("点位简表", lambda x: self.get_markers_list(), (0.55, 0.55, 0.55, 1), size_hint_x=1))
        self.dashboard_quick_grid.add_widget(self._create_action_button("急停", lambda x: self.emergency_stop(), (0.9, 0.2, 0.2, 1), size_hint_x=1))
        self.dashboard_quick_grid.add_widget(self._create_action_button("解除急停", lambda x: self.release_emergency_stop(), (0.85, 0.55, 0.2, 1), size_hint_x=1))
        quick_card.add_widget(self.dashboard_quick_grid)
        box.add_widget(quick_card)

    # ================================================================== #
    # 页面 1：状态
    # ================================================================== #
    def _build_page_status(self):
        box = self._make_page_scroll("status")

        status_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(8),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(1, 1, 1, 1),
        )
        status_card.bind(minimum_height=status_card.setter("height"))
        status_card.add_widget(MDLabel(
            text="实时状态",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        ))
        self.status_label = MDLabel(text="未连接", theme_text_color="Secondary", size_hint_y=None, height=dp(26))
        self.power_label = MDLabel(text="电量: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.move_label = MDLabel(text="运动状态: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.pose_label = MDLabel(text="坐标: (--, --)", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.notice_label = MDLabel(text="最近操作: --", theme_text_color="Hint", size_hint_y=None, height=dp(36))
        for w in [self.status_label, self.power_label, self.move_label, self.pose_label, self.notice_label]:
            status_card.add_widget(w)
        status_card.add_widget(self._create_action_button("获取状态", lambda x: self.get_robot_status(), (0.25, 0.55, 0.85, 1), size_hint_x=1))
        box.add_widget(status_card)

        telem_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(8),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(0.96, 0.98, 1, 1),
        )
        telem_card.bind(minimum_height=telem_card.setter("height"))
        telem_card.add_widget(MDLabel(
            text="实时订阅",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        ))
        telem_card.add_widget(MDLabel(
            text="连接后自动订阅速度和人检测；底盘重启后可手动重订阅。",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(38),
        ))
        self.velocity_live_label = MDLabel(text="实测速: 等待订阅数据", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.human_detection_label = MDLabel(text="人检测: 暂无数据", theme_text_color="Hint", size_hint_y=None, height=dp(42))
        telem_card.add_widget(self.velocity_live_label)
        telem_card.add_widget(self.human_detection_label)
        telem_card.add_widget(self._create_action_button("重订阅实时数据", lambda x: self.resubscribe_live_topics_action(), (0.35, 0.55, 0.8, 1), size_hint_x=1))
        box.add_widget(telem_card)

    # ================================================================== #
    # 页面 2：直控
    # ================================================================== #
    def _build_page_control(self):
        box = self._make_page_scroll("control")

        ctrl_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(8),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(0.99, 0.995, 1, 1),
        )
        ctrl_card.bind(minimum_height=ctrl_card.setter("height"))
        ctrl_card.add_widget(MDLabel(
            text="直接控制",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        ))
        ctrl_card.add_widget(MDLabel(
            text="按住方向键移动，松手后自动停止。遥控速度跟随速度页设置。",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(42),
        ))

        grid = GridLayout(
            cols=3,
            spacing=dp(10),
            padding=[dp(10), dp(4), dp(10), dp(4)],
            size_hint=(1, None),
            height=dp(224),
            row_force_default=True,
            row_default_height=dp(64),
        )
        self.control_pad_grid = grid

        btn_configs = [
            ("arrow-top-left", 0.75, 0.65),
            ("arrow-up-bold", 1.0, 0.0),
            ("arrow-top-right", 0.75, -0.65),
            ("rotate-left", 0.0, 1.0),
            ("stop-circle-outline", 0.0, 0.0),
            ("rotate-right", 0.0, -1.0),
            ("arrow-bottom-left", -0.75, 0.65),
            ("arrow-down-bold", -1.0, 0.0),
            ("arrow-bottom-right", -0.75, -0.65),
        ]
        for icon, linear, angular in btn_configs:
            if icon == "stop-circle-outline":
                btn = MDIconButton(
                    icon=icon,
                    icon_size="48sp",
                    theme_text_color="Custom",
                    text_color=(1, 0, 0, 1),
                    on_release=lambda x, l=0.0, a=0.0: self._stop_joy_control(),
                )
            else:
                btn = MDIconButton(icon=icon, icon_size="48sp", theme_text_color="Primary")
                btn.bind(on_press=lambda inst, l=linear, a=angular: self._start_joy_control(l, a))
                btn.bind(on_release=lambda inst: self._stop_joy_control())
            grid.add_widget(btn)

        ctrl_card.add_widget(grid)
        self.drive_profile_label = MDLabel(
            text="遥控速度: 直线 0.45 m/s | 角速度 1.20 rad/s",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(28),
        )
        ctrl_card.add_widget(self.drive_profile_label)
        box.add_widget(ctrl_card)

    # ================================================================== #
    # 页面 3：速度与回充
    # ================================================================== #
    def _build_page_profile(self):
        box = self._make_page_scroll("profile")

        profile_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(1, 0.985, 0.965, 1),
        )
        profile_card.bind(minimum_height=profile_card.setter("height"))
        profile_card.add_widget(MDLabel(
            text="速度与自动回充",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        ))
        profile_card.add_widget(MDLabel(
            text="参数同时影响遥控速度上限和导航策略；低电量时优先回充电桩。",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(42),
        ))
        self.speed_summary_label = MDLabel(
            text="速度参数: 直线 0.45 m/s | 角速度 1.20 rad/s",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(28),
        )
        profile_card.add_widget(self.speed_summary_label)

        speed_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.linear_speed_input = MDTextField(text="0.45", hint_text="直线速度 0.1~1.0", icon_right="arrow-up-down", mode="rectangle")
        self.angular_speed_input = MDTextField(text="1.20", hint_text="角速度 0.5~3.5", icon_right="rotate-3d-variant", mode="rectangle")
        speed_row.add_widget(self.linear_speed_input)
        speed_row.add_widget(self.angular_speed_input)
        profile_card.add_widget(speed_row)

        speed_btn_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        speed_btn_row.add_widget(self._create_action_button("读取速度", lambda x: self.get_speed_params_action(), (0.25, 0.55, 0.85, 1)))
        speed_btn_row.add_widget(self._create_action_button("应用速度", lambda x: self.apply_speed_settings_action(), (0.3, 0.65, 0.45, 1)))
        profile_card.add_widget(speed_btn_row)

        profile_card.add_widget(MDLabel(
            text="高级导航参数（导航/巡游/自动回充都会带上）",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(28),
        ))

        nav_r1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.nav_distance_tolerance_input = MDTextField(text="0.35", hint_text="距离容差(m)", icon_right="ruler", mode="rectangle")
        self.nav_theta_tolerance_input = MDTextField(text="0.35", hint_text="角度容差(rad)", icon_right="angle-acute", mode="rectangle")
        nav_r1.add_widget(self.nav_distance_tolerance_input)
        nav_r1.add_widget(self.nav_theta_tolerance_input)
        profile_card.add_widget(nav_r1)

        nav_r2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.nav_occupied_tolerance_input = MDTextField(text="0.45", hint_text="让步停靠(m)", icon_right="map-marker-distance", mode="rectangle")
        self.nav_retry_input = MDTextField(text="30", hint_text="重试次数", icon_right="repeat", mode="rectangle")
        nav_r2.add_widget(self.nav_occupied_tolerance_input)
        nav_r2.add_widget(self.nav_retry_input)
        profile_card.add_widget(nav_r2)

        nav_r3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.nav_angle_offset_input = MDTextField(text="0", hint_text="角度偏移 -3.14~3.14", icon_right="compass-outline", mode="rectangle")
        self.nav_reverse_allowed_input = MDTextField(text="-1", hint_text="双向停靠 -1/0/1", icon_right="swap-horizontal", mode="rectangle")
        nav_r3.add_widget(self.nav_angle_offset_input)
        nav_r3.add_widget(self.nav_reverse_allowed_input)
        profile_card.add_widget(nav_r3)

        self.auto_charge_label = MDLabel(
            text="自动回充: 阈值 20% | 充电桩待识别",
            theme_text_color="Hint",
            size_hint_y=None,
            height=dp(45),
        )
        profile_card.add_widget(self.auto_charge_label)

        ac_r1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.auto_charge_threshold_input = MDTextField(text="20", hint_text="回充阈值(%)", icon_right="battery-alert-variant-outline", mode="rectangle", size_hint_x=0.35)
        self.charge_dock_input = MDTextField(hint_text="充电桩点位名（留空则自动识别）", icon_right="ev-station", mode="rectangle", size_hint_x=0.65)
        ac_r1.add_widget(self.auto_charge_threshold_input)
        ac_r1.add_widget(self.charge_dock_input)
        profile_card.add_widget(ac_r1)

        ac_r2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        ac_r2.add_widget(self._create_action_button("识别充电桩", lambda x: self.refresh_charge_dock_candidates(), (0.35, 0.55, 0.8, 1)))
        ac_r2.add_widget(self._create_action_button("立即回充", lambda x: self.navigate_to_charge_dock_action(), (0.75, 0.55, 0.2, 1)))
        profile_card.add_widget(ac_r2)
        box.add_widget(profile_card)

    # ================================================================== #
    # 页面 4：快速操作
    # ================================================================== #
    def _build_page_function(self):
        box = self._make_page_scroll("function")

        func_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(0.97, 1, 0.98, 1),
        )
        func_card.bind(minimum_height=func_card.setter("height"))
        func_card.add_widget(MDLabel(
            text="快速操作",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        ))

        r1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(48))
        r1.add_widget(self._create_action_button("获取状态", lambda x: self.get_robot_status(), (0.3, 0.6, 0.4, 1), size_hint_x=0.34))
        r1.add_widget(self._create_action_button("急停", lambda x: self.emergency_stop(), (0.9, 0.2, 0.2, 1), size_hint_x=0.33))
        r1.add_widget(self._create_action_button("解除急停", lambda x: self.release_emergency_stop(), (0.85, 0.55, 0.2, 1), size_hint_x=0.33))
        func_card.add_widget(r1)

        r2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(48))
        r2.add_widget(self._create_action_button("灯带绿", lambda x: self.set_led(0, 100, 0), (0.2, 0.7, 0.3, 1), size_hint_x=0.33))
        r2.add_widget(self._create_action_button("灯带红", lambda x: self.set_led(100, 0, 0), (0.9, 0.3, 0.3, 1), size_hint_x=0.33))
        r2.add_widget(self._create_action_button("灯带蓝", lambda x: self.set_led(0, 0, 100), (0.2, 0.4, 0.9, 1), size_hint_x=0.33))
        func_card.add_widget(r2)

        r3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(48))
        r3.add_widget(self._create_action_button("扫描 WiFi", lambda x: self.get_wifi_list(), (0.5, 0.5, 0.5, 1)))
        r3.add_widget(self._create_action_button("地图列表", lambda x: self.get_map_list(), (0.5, 0.5, 0.5, 1)))
        func_card.add_widget(r3)

        led_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(56))
        self.led_luminance_input = MDTextField(text="60", hint_text="亮度 0~100", icon_right="brightness-6", mode="rectangle", size_hint_x=0.45)
        led_row.add_widget(self.led_luminance_input)
        led_row.add_widget(self._create_action_button("设置亮度", lambda x: self.set_led_luminance_action(), (0.75, 0.55, 0.2, 1), size_hint_x=0.55))
        func_card.add_widget(led_row)
        box.add_widget(func_card)

    # ================================================================== #
    # 页面 5：WiFi
    # ================================================================== #
    def _build_page_wifi(self):
        box = self._make_page_scroll("wifi")

        wifi_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(0.965, 0.99, 1, 1),
        )
        wifi_card.bind(minimum_height=wifi_card.setter("height"))
        wifi_card.add_widget(MDLabel(
            text="WiFi 管理",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Primary",
        ))
        self.current_wifi_label = MDLabel(text="当前 WiFi: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.network_info_label = MDLabel(text="网络信息: --", theme_text_color="Hint", size_hint_y=None, height=dp(45))
        wifi_card.add_widget(self.current_wifi_label)
        wifi_card.add_widget(self.network_info_label)

        self.wifi_ssid_input = MDTextField(hint_text="WiFi 名称（SSID）", icon_right="wifi", mode="rectangle")
        self.wifi_password_input = MDTextField(hint_text="WiFi 密码（开放网络可留空）", icon_right="lock", mode="rectangle", password=True)
        wifi_card.add_widget(self.wifi_ssid_input)
        wifi_card.add_widget(self.wifi_password_input)

        wr1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        wr1.add_widget(self._create_action_button("当前网络", lambda x: self.get_active_wifi_info(), (0.25, 0.55, 0.85, 1)))
        wr1.add_widget(self._create_action_button("网络信息", lambda x: self.get_network_info_action(), (0.35, 0.55, 0.8, 1)))
        wifi_card.add_widget(wr1)

        wr2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        wr2.add_widget(self._create_action_button("扫描 WiFi", lambda x: self.get_wifi_list(), (0.35, 0.6, 0.45, 1)))
        wr2.add_widget(self._create_action_button("连接 WiFi", lambda x: self.connect_wifi_from_input(), (0.75, 0.55, 0.2, 1)))
        wifi_card.add_widget(wr2)

        wr3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        wr3.add_widget(self._create_action_button("WiFi 详情", lambda x: self.get_wifi_detail_list_action(), (0.55, 0.55, 0.55, 1)))
        wr3.add_widget(self._create_action_button("刷新概览", lambda x: self.refresh_network_overview(), (0.45, 0.5, 0.8, 1)))
        wifi_card.add_widget(wr3)
        box.add_widget(wifi_card)

    # ================================================================== #
    # 页面 6：地图与点位
    # ================================================================== #
    def _build_page_map(self):
        box = self._make_page_scroll("map")

        nav_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(1, 0.99, 0.965, 1),
        )
        nav_card.bind(minimum_height=nav_card.setter("height"))
        nav_card.add_widget(MDLabel(text="地图与点位", font_style="H6", size_hint_y=None, height=dp(30), theme_text_color="Primary"))
        nav_card.add_widget(MDLabel(text="地图切换、点位维护和按坐标导航。", theme_text_color="Secondary", size_hint_y=None, height=dp(22)))

        self.current_map_label = MDLabel(text="当前地图: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        nav_card.add_widget(self.current_map_label)

        self.marker_input = MDTextField(hint_text="点位名称，例如 A001", icon_right="map-marker", mode="rectangle")
        nav_card.add_widget(self.marker_input)

        map_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.map_input = MDTextField(hint_text="地图名称，例如 factory_1f", icon_right="map", mode="rectangle")
        self.floor_input = MDTextField(text="1", hint_text="楼层", icon_right="stairs", mode="rectangle", size_hint_x=0.3)
        map_row.add_widget(self.map_input)
        map_row.add_widget(self.floor_input)
        nav_card.add_widget(map_row)

        pose_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.pose_x_input = MDTextField(hint_text="X", icon_right="axis-x-arrow", mode="rectangle")
        self.pose_y_input = MDTextField(hint_text="Y", icon_right="axis-y-arrow", mode="rectangle")
        self.pose_theta_input = MDTextField(text="0", hint_text="θ", icon_right="angle-acute", mode="rectangle", size_hint_x=0.3)
        pose_row.add_widget(self.pose_x_input)
        pose_row.add_widget(self.pose_y_input)
        pose_row.add_widget(self.pose_theta_input)
        nav_card.add_widget(pose_row)

        nr1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        nr1.add_widget(self._create_action_button("当前地图", lambda x: self.get_current_map_info(), (0.25, 0.55, 0.85, 1)))
        nr1.add_widget(self._create_action_button("地图详情", lambda x: self.get_map_list_info_action(), (0.35, 0.55, 0.8, 1)))
        nav_card.add_widget(nr1)

        nr2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        nr2.add_widget(self._create_action_button("点位简表", lambda x: self.get_markers_list(), (0.35, 0.6, 0.45, 1)))
        nr2.add_widget(self._create_action_button("点位数量", lambda x: self.get_markers_count_action(), (0.3, 0.65, 0.45, 1)))
        nav_card.add_widget(nr2)

        nr3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        nr3.add_widget(self._create_action_button("前往点位", lambda x: self.navigate_to_marker(), (0.75, 0.55, 0.2, 1)))
        nr3.add_widget(self._create_action_button("坐标导航", lambda x: self.navigate_to_pose_action(), (0.6, 0.5, 0.85, 1)))
        nav_card.add_widget(nr3)

        nr4 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        nr4.add_widget(self._create_action_button("当前位置录点", lambda x: self.insert_marker_here(), (0.55, 0.55, 0.55, 1)))
        nr4.add_widget(self._create_action_button("坐标录点", lambda x: self.insert_marker_by_pose_action(), (0.45, 0.5, 0.8, 1)))
        nav_card.add_widget(nr4)

        nr5 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        nr5.add_widget(self._create_action_button("删除点位", lambda x: self.delete_marker_action(), (0.75, 0.3, 0.3, 1)))
        nr5.add_widget(self._create_action_button("切换地图", lambda x: self.set_current_map_from_input(), (0.5, 0.45, 0.8, 1)))
        nav_card.add_widget(nr5)

        nr6 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        nr6.add_widget(self._create_action_button("取消导航", lambda x: self.cancel_navigation_action(), (0.85, 0.3, 0.3, 1), size_hint_x=1))
        nav_card.add_widget(nr6)
        box.add_widget(nav_card)

    # ================================================================== #
    # 页面 7：路径规划
    # ================================================================== #
    def _build_page_plan(self):
        box = self._make_page_scroll("plan")

        plan_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(0.97, 0.98, 1, 1),
        )
        plan_card.bind(minimum_height=plan_card.setter("height"))
        plan_card.add_widget(MDLabel(text="路径规划与定位校准", font_style="H6", size_hint_y=None, height=dp(30), theme_text_color="Primary"))
        self.plan_summary_label = MDLabel(text="规划结果: --", theme_text_color="Hint", size_hint_y=None, height=dp(45))
        plan_card.add_widget(self.plan_summary_label)
        self.plan_hint_label = MDLabel(
            text="默认用当前坐标作为起点，可先探测再规划，也可直接用同一组坐标做定位校准。",
            theme_text_color="Secondary", size_hint_y=None, height=dp(44),
        )
        plan_card.add_widget(self.plan_hint_label)

        target_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.plan_target_x_input = MDTextField(hint_text="目标 X，例如 1.25", icon_right="axis-x-arrow", mode="rectangle")
        self.plan_target_y_input = MDTextField(hint_text="目标 Y，例如 -0.80", icon_right="axis-y-arrow", mode="rectangle")
        self.plan_target_floor_input = MDTextField(text="1", hint_text="楼层", icon_right="stairs", mode="rectangle", size_hint_x=0.3)
        target_row.add_widget(self.plan_target_x_input)
        target_row.add_widget(self.plan_target_y_input)
        target_row.add_widget(self.plan_target_floor_input)
        plan_card.add_widget(target_row)

        pr1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        pr1.add_widget(self._create_action_button("使用当前位置", lambda x: self.fill_current_pose_to_plan_inputs(), (0.25, 0.55, 0.85, 1)))
        pr1.add_widget(self._create_action_button("障碍探测", lambda x: self.distance_probe_action(), (0.35, 0.55, 0.8, 1)))
        plan_card.add_widget(pr1)

        pr2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        pr2.add_widget(self._create_action_button("查可达点", lambda x: self.accessible_point_query_action(), (0.35, 0.6, 0.45, 1)))
        pr2.add_widget(self._create_action_button("路径规划", lambda x: self.make_plan_action(), (0.75, 0.55, 0.2, 1)))
        plan_card.add_widget(pr2)

        plan_card.add_widget(MDLabel(
            text="定位偏了时，可按点位校准，或用地图区的 X/Y/θ 做坐标校准。",
            theme_text_color="Secondary", size_hint_y=None, height=dp(36),
        ))

        pr3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        pr3.add_widget(self._create_action_button("按点位校准", lambda x: self.adjust_position_by_marker_action(), (0.55, 0.55, 0.55, 1)))
        pr3.add_widget(self._create_action_button("按坐标校准", lambda x: self.adjust_position_by_pose_action(), (0.45, 0.5, 0.8, 1)))
        plan_card.add_widget(pr3)
        box.add_widget(plan_card)

    # ================================================================== #
    # 页面 8：系统
    # ================================================================== #
    def _build_page_system(self):
        box = self._make_page_scroll("system")

        system_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(0.985, 0.985, 1, 1),
        )
        system_card.bind(minimum_height=system_card.setter("height"))
        system_card.add_widget(MDLabel(text="系统信息与诊断", font_style="H6", size_hint_y=None, height=dp(30), theme_text_color="Primary"))

        self.robot_info_label = MDLabel(text="机器人信息: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.system_version_label = MDLabel(text="软件版本: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        self.power_summary_label = MDLabel(text="电源状态: --", theme_text_color="Hint", size_hint_y=None, height=dp(45))
        self.diagnosis_summary_label = MDLabel(text="自诊断: --", theme_text_color="Hint", size_hint_y=None, height=dp(26))
        for w in [self.robot_info_label, self.system_version_label, self.power_summary_label, self.diagnosis_summary_label]:
            system_card.add_widget(w)

        sr1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        sr1.add_widget(self._create_action_button("机器人信息", lambda x: self.get_robot_info_action(), (0.25, 0.55, 0.85, 1)))
        sr1.add_widget(self._create_action_button("软件版本", lambda x: self.get_software_version_action(), (0.35, 0.55, 0.8, 1)))
        system_card.add_widget(sr1)

        sr2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        sr2.add_widget(self._create_action_button("检查更新", lambda x: self.check_for_update_action(), (0.35, 0.6, 0.45, 1)))
        sr2.add_widget(self._create_action_button("电源状态", lambda x: self.get_power_status_action(), (0.75, 0.55, 0.2, 1)))
        system_card.add_widget(sr2)

        sr3 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        sr3.add_widget(self._create_action_button("自诊断", lambda x: self.get_diagnosis_result_action(), (0.6, 0.5, 0.85, 1)))
        sr3.add_widget(self._create_action_button("当前路径", lambda x: self.get_planned_path_action(), (0.25, 0.6, 0.7, 1)))
        system_card.add_widget(sr3)

        sr4 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        sr4.add_widget(self._create_action_button("电梯状态", lambda x: self.get_lift_status_action(), (0.5, 0.5, 0.5, 1)))
        sr4.add_widget(self._create_action_button("WiFi 详情", lambda x: self.get_wifi_detail_list_action(), (0.5, 0.5, 0.5, 1)))
        system_card.add_widget(sr4)
        box.add_widget(system_card)

    # ================================================================== #
    # 页面 9：巡游
    # ================================================================== #
    def _build_page_cruise(self):
        box = self._make_page_scroll("cruise")

        cruise_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(1, 0.985, 0.965, 1),
        )
        cruise_card.bind(minimum_height=cruise_card.setter("height"))
        cruise_card.add_widget(MDLabel(text="多目标巡游", font_style="H6", size_hint_y=None, height=dp(30), theme_text_color="Primary"))
        cruise_card.add_widget(MDLabel(
            text="多个点位用英文逗号分隔，例如 A001,A002,A003；count=-1 表示无限循环。",
            theme_text_color="Secondary", size_hint_y=None, height=dp(50),
        ))

        self.cruise_markers_input = MDTextField(hint_text="点位列表，例如 A001,A002,A003", icon_right="map-marker-multiple", mode="rectangle")
        cruise_card.add_widget(self.cruise_markers_input)

        cp_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(70))
        self.cruise_tolerance_input = MDTextField(text="1.0", hint_text="容差(m)", icon_right="ruler", mode="rectangle")
        self.cruise_count_input = MDTextField(text="-1", hint_text="循环次数(-1无限)", icon_right="repeat", mode="rectangle")
        cp_row.add_widget(self.cruise_tolerance_input)
        cp_row.add_widget(self.cruise_count_input)
        cruise_card.add_widget(cp_row)

        cb_row = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        cb_row.add_widget(self._create_action_button("开始巡游", lambda x: self.start_cruise_action(), (0.3, 0.65, 0.45, 1)))
        cb_row.add_widget(self._create_action_button("停止巡游", lambda x: self.cancel_navigation_action(), (0.85, 0.3, 0.3, 1)))
        cruise_card.add_widget(cb_row)
        box.add_widget(cruise_card)

    # ================================================================== #
    # 页面 10：高危操作
    # ================================================================== #
    def _build_page_danger(self):
        box = self._make_page_scroll("danger")

        danger_card = MDCard(
            orientation="vertical",
            padding=dp(15),
            spacing=dp(10),
            size_hint=(1, None),
            elevation=3,
            radius=[18],
            md_bg_color=(1, 0.96, 0.96, 1),
        )
        danger_card.bind(minimum_height=danger_card.setter("height"))
        danger_card.add_widget(MDLabel(
            text="高危操作",
            font_style="H6",
            size_hint_y=None,
            height=dp(30),
            theme_text_color="Error",
        ))
        danger_card.add_widget(MDLabel(
            text="以下操作不可逆，执行前请确认机器人处于安全状态。",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(30),
        ))

        dr1 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        dr1.add_widget(self._create_action_button("重启软件服务", lambda x: self.confirm_restart_service(), (0.75, 0.45, 0.1, 1)))
        dr1.add_widget(self._create_action_button("立即更新软件", lambda x: self.confirm_update_software(), (0.5, 0.3, 0.8, 1)))
        danger_card.add_widget(dr1)

        dr2 = MDBoxLayout(spacing=dp(10), size_hint_y=None, height=dp(45))
        dr2.add_widget(self._create_action_button("重启机器人", lambda x: self.confirm_reboot(), (0.8, 0.35, 0.1, 1)))
        dr2.add_widget(self._create_action_button("关机", lambda x: self.confirm_shutdown(), (0.8, 0.1, 0.1, 1)))
        danger_card.add_widget(dr2)
        box.add_widget(danger_card)

    def _clean_ui_text(self, text):
        """去掉前导 emoji/装饰符，避免 Android 缺字时出现方块。"""
        if text is None:
            return ""
        value = str(text).strip()
        value = re.sub(r"^[^\w\u4e00-\u9fffA-Za-z0-9]+", "", value)
        return value.strip()

    def _set_notice(self, message):
        """更新最近操作提示。"""
        clean_text = self._clean_ui_text(message) or "--"
        if hasattr(self, "notice_label"):
            self.notice_label.text = f"最近操作: {clean_text}"
        self._sync_dashboard_overview()

    def _create_action_button(self, text, on_release, color, size_hint_x=0.5):

        """统一创建按钮，去掉按钮文本中的 emoji 方块。"""
        return MDRaisedButton(
            text=self._clean_ui_text(text),
            size_hint=(size_hint_x, None),
            height=dp(42),
            on_release=on_release,
            md_bg_color=color,
        )

    def _create_scene_button(self, text, on_release, color):
        """创建首页一键工作台按钮。"""
        return MDRaisedButton(
            text=self._clean_ui_text(text),
            size_hint=(1, None),
            height=dp(48),
            on_release=on_release,
            md_bg_color=color,
        )

    def _create_nav_button(self, text, section_key):
        """创建顶部区域跳转按钮（切换 Tab 页）。"""
        return MDRaisedButton(
            text=self._clean_ui_text(text),
            size_hint=(1, None),
            height=dp(38),
            on_release=lambda instance, key=section_key: self._switch_page(key),
            md_bg_color=(0.26, 0.52, 0.84, 1),
        )

    def _create_dashboard_metric_card(self, title, value_attr, default_text):
        """创建仪表盘摘要卡片。"""
        card = MDCard(
            orientation="vertical",
            padding=dp(10),
            spacing=dp(4),
            size_hint=(1, None),
            elevation=1,
            radius=[14],
            md_bg_color=(0.99, 0.995, 1, 1),
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(MDLabel(
            text=title,
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(20),
        ))
        value_label = MDLabel(
            text=default_text,
            theme_text_color="Primary",
            bold=True,
            size_hint_y=None,
            height=dp(40),
        )
        setattr(self, value_attr, value_label)
        card.add_widget(value_label)
        return card

    def _create_dashboard_signal_card(self, title, value_attr, default_text, fill_color):
        """创建首页总控台上的高亮信号卡片。"""
        card = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(4),
            size_hint=(1, None),
            elevation=0,
            radius=[16],
            md_bg_color=fill_color,
        )
        card.bind(minimum_height=card.setter("height"))
        card.add_widget(MDLabel(
            text=title,
            theme_text_color="Custom",
            text_color=(0.88, 0.93, 1, 1),
            size_hint_y=None,
            height=dp(20),
        ))
        value_label = MDLabel(
            text=default_text,
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            bold=True,
            size_hint_y=None,
            height=dp(42),
        )
        setattr(self, value_attr, value_label)
        card.add_widget(value_label)
        return card

    def _style_surface_card(self, card, fill_color, elevation=3, radius=18):
        """统一调整卡片底色和圆角，减少页面拼装感。"""
        if not card:
            return
        try:
            card.md_bg_color = fill_color
        except Exception:
            pass
        try:
            card.elevation = elevation
        except Exception:
            pass
        try:
            card.radius = [radius]
        except Exception:
            pass


    def _register_responsive_grid(self, layout, breakpoints):
        """登记需要按屏幕宽度切换列数的网格。"""
        self.responsive_grids.append({
            "layout": layout,
            "breakpoints": sorted(list(breakpoints), key=lambda item: item[0]),
        })
        return layout

    def _register_responsive_row(self, layout, child_height=52, compact_breakpoint=520):
        """登记窄屏时要改成纵向堆叠的横向行。"""
        for item in self.responsive_rows:
            if item["layout"] is layout:
                return layout

        children = []
        for child in layout.children:
            children.append({
                "widget": child,
                "size_hint_x": child.size_hint_x,
                "size_hint_y": child.size_hint_y,
                "height": getattr(child, "height", None),
            })

        spacing = layout.spacing[0] if isinstance(layout.spacing, (list, tuple)) else layout.spacing
        self.responsive_rows.append({
            "layout": layout,
            "regular_height": layout.height,
            "spacing": spacing or 0,
            "child_height": dp(child_height),
            "compact_breakpoint": compact_breakpoint,
            "children": children,
        })
        return layout

    def _collect_responsive_rows(self, *widgets):
        """扫描现有卡片，把常见双列/三列操作行纳入窄屏自适应。"""
        for widget in widgets:
            self._walk_responsive_rows(widget)

    def _walk_responsive_rows(self, widget):
        if not widget:
            return
        for child in getattr(widget, "children", []):
            if isinstance(child, MDBoxLayout):
                child_count = len(child.children)
                if child.orientation == "horizontal" and child.size_hint_y is None and 2 <= child_count <= 3 and child.height <= dp(74):
                    self._register_responsive_row(child)
            self._walk_responsive_rows(child)

    def _extract_value_part(self, text):
        """把“标题: 内容”提取成摘要内容。"""
        clean_text = self._clean_ui_text(text or "")
        if ":" in clean_text:
            return clean_text.split(":", 1)[1].strip() or "--"
        if "：" in clean_text:
            return clean_text.split("：", 1)[1].strip() or "--"
        return clean_text or "--"

    def _sync_dashboard_overview(self, *_args):
        """把各功能区已有摘要同步到首页仪表盘。"""
        if not hasattr(self, "dashboard_primary_status"):
            return

        status_text = self._clean_ui_text(getattr(getattr(self, "status_label", None), "text", "未连接")) or "未连接"
        power_text = self._extract_value_part(getattr(getattr(self, "power_label", None), "text", "电量: --"))
        map_text = self._extract_value_part(getattr(getattr(self, "current_map_label", None), "text", "当前地图: --"))
        wifi_text = self._extract_value_part(getattr(getattr(self, "current_wifi_label", None), "text", "当前 WiFi: --"))
        move_text = self._extract_value_part(getattr(getattr(self, "move_label", None), "text", "运动状态: --"))
        
        # 姿态：简化显示，只取x,y坐标，去掉θ和括号
        raw_pose_text = getattr(getattr(self, "pose_label", None), "text", "坐标: --")
        pose_match = re.search(r"\(([\d.-]+),\s*([\d.-]+)", raw_pose_text)
        if pose_match:
            pose_text = f"{pose_match.group(1)},{pose_match.group(2)}"
        else:
            pose_text = self._extract_value_part(raw_pose_text)
        
        # 速度：从实时订阅数据直接提取，避免JSON格式
        velocity_payload = getattr(self, "latest_velocity_payload", {})
        if isinstance(velocity_payload, dict) and velocity_payload:
            linear_val = velocity_payload.get("linear")
            angular_val = velocity_payload.get("angular")
            if linear_val is not None and angular_val is not None:
                velocity_text = f"线{linear_val:.2f}|角{angular_val:.2f}"
            elif linear_val is not None:
                velocity_text = f"{linear_val:.2f} m/s"
            elif angular_val is not None:
                velocity_text = f"{angular_val:.2f} rad/s"
            else:
                velocity_text = "--"
        else:
            velocity_text = "等待数据"
        
        human_text = self._extract_value_part(getattr(getattr(self, "human_detection_label", None), "text", "人检测: 暂无数据"))
        notice_text = self._clean_ui_text(getattr(getattr(self, "notice_label", None), "text", "最近操作: --")) or "最近操作: --"

        power_number = None
        match = re.search(r"-?\d+(?:\.\d+)?", power_text)
        if match:
            try:
                power_number = float(match.group(0))
            except (TypeError, ValueError):
                power_number = None

        if status_text != "已连接":
            action_hint = "当前建议：先连接设备并完成状态同步。"
            mode_text = "离线待机"
            next_step_text = "连接设备"
            focus_text = "等待联机"
        elif power_number is not None and power_number <= 20:
            action_hint = "当前建议：电量偏低，优先执行回充。"
            mode_text = "在线联机"
            next_step_text = "立即回充"
            focus_text = "低电量"
        elif map_text in ("--", "None"):
            action_hint = "当前建议：先同步当前地图和点位。"
            mode_text = "在线联机"
            next_step_text = "同步地图"
            focus_text = "地图待同步"
        elif "等待" in velocity_text:
            action_hint = "当前建议：先确认实时订阅是否稳定。"
            mode_text = "在线联机"
            next_step_text = "确认订阅"
            focus_text = "等待实时回传"
        elif move_text not in ("--", "停止", "idle", "Idle", "待命", "空闲"):
            action_hint = f"当前建议：机器人正在{move_text}，注意现场安全。"
            mode_text = "在线联机"
            next_step_text = "关注运动"
            focus_text = move_text
        else:
            action_hint = "当前建议：状态已就绪，可直接进入地图作业。"
            mode_text = "在线联机"
            next_step_text = "开始作业"
            focus_text = pose_text if pose_text != "--" else (map_text if map_text != "--" else "待命")

        self.dashboard_primary_status.text = f"当前状态：{status_text}"
        self.dashboard_notice_value.text = notice_text.replace("最近操作:", "最近操作：")
        self.dashboard_connection_value.text = status_text
        self.dashboard_power_value.text = power_text
        self.dashboard_map_value.text = map_text
        self.dashboard_wifi_value.text = wifi_text
        if hasattr(self, "dashboard_motion_value"):
            self.dashboard_motion_value.text = move_text
        if hasattr(self, "dashboard_pose_value"):
            self.dashboard_pose_value.text = pose_text
        self.dashboard_velocity_value.text = velocity_text
        self.dashboard_human_value.text = human_text
        if hasattr(self, "dashboard_action_hint_label"):
            self.dashboard_action_hint_label.text = action_hint
        if hasattr(self, "dashboard_mode_value"):
            self.dashboard_mode_value.text = mode_text
        if hasattr(self, "dashboard_next_step_value"):
            self.dashboard_next_step_value.text = next_step_text
        if hasattr(self, "dashboard_focus_value"):
            self.dashboard_focus_value.text = focus_text


    def _apply_responsive_layout(self, *_args):
        """按当前屏幕宽度切换仪表盘列数、内容区列数和横向行堆叠方式。"""
        width = getattr(Window, "width", 360) or 360

        for item in self.responsive_grids:
            layout = item["layout"]
            cols = item["breakpoints"][0][1]
            for min_width, candidate in item["breakpoints"]:
                if width >= min_width:
                    cols = candidate
            layout.cols = cols

        for item in self.responsive_rows:
            layout = item["layout"]
            compact = width < item["compact_breakpoint"]
            if compact:
                layout.orientation = "vertical"
                layout.height = max(
                    item["regular_height"],
                    item["child_height"] * len(item["children"]) + item["spacing"] * max(len(item["children"]) - 1, 0)
                )
                for child_meta in item["children"]:
                    child = child_meta["widget"]
                    child.size_hint_x = 1
                    child.size_hint_y = None
                    if child_meta["height"] is None or child_meta["height"] < item["child_height"]:
                        child.height = item["child_height"]
            else:
                layout.orientation = "horizontal"
                layout.height = item["regular_height"]
                for child_meta in item["children"]:
                    child = child_meta["widget"]
                    child.size_hint_x = child_meta["size_hint_x"]
                    child.size_hint_y = child_meta["size_hint_y"]
                    if child_meta["height"] is not None:
                        child.height = child_meta["height"]

        if hasattr(self, "control_pad_grid"):
            if width < 420:
                self.control_pad_grid.row_default_height = dp(54)
                self.control_pad_grid.height = dp(194)
            elif width < 800:
                self.control_pad_grid.row_default_height = dp(60)
                self.control_pad_grid.height = dp(212)
            else:
                self.control_pad_grid.row_default_height = dp(68)
                self.control_pad_grid.height = dp(236)

        Clock.schedule_once(self._refresh_section_card_heights, 0)

    def _scroll_to_top(self):
        """回到首页。"""
        self._switch_page("home")
        self._set_notice("已回到首页")

    def _scroll_to_section(self, section_key):
        """切换到指定功能页（兼容旧调用）。"""
        _PAGE_ALIAS = {
            "connection": "home",
            "status":     "status",
            "control":    "control",
            "profile":    "profile",
            "function":   "function",
            "wifi":       "wifi",
            "map":        "map",
            "plan":       "plan",
            "system":     "system",
            "cruise":     "cruise",
            "danger":     "danger",
        }
        page_key = _PAGE_ALIAS.get(section_key, section_key)
        self._switch_page(page_key)

    def run_readiness_check_action(self):
        """从首页直接发起联机巡检。"""
        self._switch_page("status")
        if not self._ensure_connected():
            return
        self.get_robot_status()
        Clock.schedule_once(lambda dt: self.get_current_map_info(), 0.5)
        Clock.schedule_once(lambda dt: self.refresh_network_overview(), 1.0)
        Clock.schedule_once(lambda dt: self.get_speed_params_action(silent=True), 1.5)
        self._set_notice("已启动联机巡检")

    def open_navigation_workspace_action(self):
        """从首页直接进入地图作业区。"""
        self._switch_page("map")
        if not self._ensure_connected():
            return
        self.get_current_map_info()
        Clock.schedule_once(lambda dt: self.get_markers_list(), 0.5)
        Clock.schedule_once(lambda dt: self.refresh_charge_dock_candidates(silent=True), 1.0)
        self._set_notice("已打开地图作业区")

    def open_network_workspace_action(self):
        """从首页直接进入网络维护区。"""
        self._switch_page("wifi")
        if not self._ensure_connected():
            return
        self.refresh_network_overview()
        Clock.schedule_once(lambda dt: self.get_wifi_detail_list_action(), 0.5)
        self._set_notice("已打开网络维护区")

    def open_safety_workspace_action(self):
        """从首页直接进入安全处置区。"""
        self._switch_page("danger")
        if not self._ensure_connected():
            return
        self.get_robot_status()
        Clock.schedule_once(lambda dt: self.get_power_status_action(), 0.5)
        self._set_notice("已打开安全处置区")

    def _refresh_section_card_heights(self, *_args):

        """根据内容自动收紧卡片高度，减少 Android 端大片空白。"""
        for card in getattr(self, "auto_height_cards", []):
            try:
                target_height = max(card.minimum_height + dp(6), dp(120))
                if abs(card.height - target_height) > 1:
                    card.height = target_height
            except Exception:
                continue
    
    def show_toast(self, message):
        """显示简短提示"""
        self._set_notice(message)
    
    def update_status_display(self):
        """更新连接状态显示"""
        if self.robot and self.robot.connected:
            self.status_label.text = "已连接"
        else:
            self.status_label.text = "未连接"
    
    def toggle_connection(self, instance):
        """切换连接状态"""
        if self.robot and self.robot.connected:
            self.disconnect_robot()
        else:
            self.conn_btn.text = "连接中..."
            self.conn_btn.disabled = True
            threading.Thread(target=self.connect_task, daemon=True).start()
    
    def connect_task(self):
        """连接任务（后台线程）"""
        ip = self.ip_input.text.strip()
        self.robot = Waterdrop2Client(ip=ip, port=31001)
        # 设置回调
        self.robot.status_callback = self.on_robot_status_update
        self.robot.data_callback = self.on_robot_data_update
        self.robot.message_callback = self.on_robot_message
        self.robot.connection_callback = self.on_connection_state_changed
        success = self.robot.connect()
        Clock.schedule_once(lambda dt: self.on_connect_result(success))

    def on_connect_result(self, success):
        """连接结果回调"""
        self.conn_btn.disabled = False
        if success:
            self.conn_btn.text = "断开设备"
            self.conn_btn.md_bg_color = (0.9, 0.2, 0.2, 1)
            self.status_label.text = "已连接"
            self.toolbar.title = "三帝AI智能底盘控制系统（在线）"
            self.auto_charge_triggered = False
            self.auto_charge_lookup_in_progress = False
            self.last_auto_charge_lookup_at = 0.0
            self.latest_velocity_payload = {}
            self.latest_human_detection_payload = {}
            self._update_velocity_subscription_ui({})
            self._update_human_detection_ui({})

            self._set_notice("连接成功，正在同步状态和扩展订阅")
            self._subscribe_live_topics(silent=True)
            self.status_update_event = Clock.schedule_interval(
                lambda dt: self.get_robot_status() if self.robot and self.robot.connected else None,
                5.0
            )
            Clock.schedule_once(lambda dt: self.get_robot_status(), 0.5)
            Clock.schedule_once(lambda dt: self.get_current_map_info(), 1.0)
            Clock.schedule_once(lambda dt: self.get_active_wifi_info(), 1.5)
            Clock.schedule_once(lambda dt: self.get_network_info_action(), 2.0)
            Clock.schedule_once(lambda dt: self.get_speed_params_action(silent=True), 2.4)
            Clock.schedule_once(lambda dt: self.refresh_charge_dock_candidates(silent=True), 2.8)
        else:
            self.conn_btn.text = "连接设备"
            self.status_label.text = "连接失败"
            self.show_dialog("连接失败", "请检查 IP 地址和网络连接！")

    def disconnect_robot(self):
        """断开连接"""
        if self.robot:
            self.robot.disconnect(reason="用户主动断开", notify=False)
        self._apply_disconnected_ui()

    def on_connection_state_changed(self, data):
        """连接状态变化回调"""
        Clock.schedule_once(lambda dt, payload=data: self._handle_connection_state(payload))

    def _handle_connection_state(self, data):
        """处理连接状态变化"""
        if data.get("connected", True):
            return

        reason = data.get("reason") or "与机器人连接已断开"
        self._apply_disconnected_ui(reason)
        self.show_dialog("连接已断开", reason)

    def _apply_disconnected_ui(self, status_text="未连接"):
        """统一重置断开连接后的界面状态"""
        if self.status_update_event:
            self.status_update_event.cancel()
            self.status_update_event = None
        self.robot = None
        self.conn_btn.disabled = False
        self.conn_btn.text = "连接设备"
        self.conn_btn.md_bg_color = (0.2, 0.5, 0.9, 1)
        self.status_label.text = self._clean_ui_text(status_text) or "未连接"
        self.power_label.text = "电量: --"
        self.move_label.text = "运动状态: --"
        self.pose_label.text = "坐标: (--, --)"
        self.current_map_label.text = "当前地图: --"
        self.current_wifi_label.text = "当前 WiFi: --"
        self.network_info_label.text = "网络信息: --"
        self.plan_summary_label.text = "规划结果: --"
        self.robot_info_label.text = "机器人信息: --"
        self.system_version_label.text = "软件版本: --"
        self.power_summary_label.text = "电源状态: --"
        self.diagnosis_summary_label.text = "自诊断: --"
        self.latest_velocity_payload = {}
        self.latest_human_detection_payload = {}
        self._update_velocity_subscription_ui({})
        self._update_human_detection_ui({})
        self.auto_charge_triggered = False
        self.auto_charge_lookup_in_progress = False
        self.marker_cache = []
        self.speed_params = {}
        self._update_drive_profile_label()
        self._refresh_auto_charge_status_line()
        self._set_notice("--")
        self.last_status = {}
        self.toolbar.title = "三帝AI智能底盘控制系统"
        self._sync_dashboard_overview()
    
    def on_robot_status_update(self, data):
        """机器人状态更新回调"""
        Clock.schedule_once(lambda dt, payload=data: self._update_status_ui(payload))

    def on_robot_data_update(self, data):
        """扩展实时订阅回调（速度、人检测等）"""
        Clock.schedule_once(lambda dt, payload=data: self._handle_robot_data_update(payload))

    def on_robot_message(self, data):
        """机器人通用消息回调"""
        Clock.schedule_once(lambda dt, payload=data: self._handle_robot_message(payload))
    
    def _update_status_ui(self, data):
        """更新状态UI"""
        results = data.get("results", {})
        self.last_status = results

        power = self._extract_power_percent(results)
        move_status = results.get("move_status", "--")
        pose = results.get("current_pose", {})

        self.status_label.text = "已连接"
        if power is not None:
            self.power_label.text = f"电量: {power}%"
        self.move_label.text = f"运动状态: {move_status}"
        if pose:
            x = self._safe_float(pose.get("x", 0))
            y = self._safe_float(pose.get("y", 0))
            theta = pose.get("theta")
            if theta is None:
                self.pose_label.text = f"坐标: ({x:.2f}, {y:.2f})"
            else:
                self.pose_label.text = f"坐标: ({x:.2f}, {y:.2f}, θ={self._safe_float(theta):.2f})"
        self._refresh_auto_charge_status_line(results)
        self._maybe_auto_charge(results)
        self._sync_dashboard_overview()

    def _handle_robot_data_update(self, data):

        """处理扩展实时订阅消息。"""
        if not isinstance(data, dict):
            return

        topic = str(data.get("topic") or "").strip()
        results = data.get("results", {})
        normalized = results if isinstance(results, dict) else {"value": results}

        if topic == "robot_velocity":
            self.latest_velocity_payload = normalized
            self._update_velocity_subscription_ui(normalized)
        elif topic == "human_detection":
            self.latest_human_detection_payload = normalized
            self._update_human_detection_ui(normalized)
        elif topic == "robot_status":
            self._update_status_ui({"results": normalized})
        elif topic:
            self._set_notice(f"收到实时数据：{topic}")

        self._sync_dashboard_overview()

    def _update_velocity_subscription_ui(self, payload):

        """更新速度订阅摘要。"""
        if not isinstance(payload, dict) or not payload:
            self.velocity_live_label.text = "实测速: 等待订阅数据"
            self.velocity_live_label.theme_text_color = "Hint"
            return

        vx = self._extract_nested_number(payload, (
            ("vx",), ("linear_x",), ("velocity", "x"), ("linear", "x"), ("twist", "linear", "x")
        ))
        vy = self._extract_nested_number(payload, (
            ("vy",), ("linear_y",), ("velocity", "y"), ("linear", "y"), ("twist", "linear", "y")
        ))
        linear = self._extract_nested_number(payload, (
            ("linear_velocity",), ("linear_speed",), ("speed_linear",), ("speed",), ("v",)
        ))
        angular = self._extract_nested_number(payload, (
            ("angular_velocity",), ("angular_speed",), ("speed_angular",), ("omega",), ("w",), ("vw",),
            ("twist", "angular", "z"), ("angular", "z")
        ))

        if linear is None and vx is not None:
            if vy is None:
                linear = abs(vx)
            else:
                linear = (vx * vx + vy * vy) ** 0.5

        parts = []
        if linear is not None:
            parts.append(f"线速 {linear:.2f} m/s")
        if vx is not None:
            parts.append(f"vx {vx:.2f}")
        if vy is not None:
            parts.append(f"vy {vy:.2f}")
        if angular is not None:
            parts.append(f"角速 {angular:.2f} rad/s")

        if not parts:
            # 尝试提取 linear 和 angular 直接显示，避免JSON格式
            linear_val = payload.get("linear")
            angular_val = payload.get("angular")
            if linear_val is not None or angular_val is not None:
                display_parts = []
                if linear_val is not None:
                    display_parts.append(f"线速 {linear_val:.2f} m/s")
                if angular_val is not None:
                    display_parts.append(f"角速 {angular_val:.2f} rad/s")
                self.velocity_live_label.text = "实测速: " + " | ".join(display_parts)
                self.velocity_live_label.theme_text_color = "Primary"
            else:
                self.velocity_live_label.text = "实测速: 已订阅，等待数据"
                self.velocity_live_label.theme_text_color = "Hint"
            return

        self.velocity_live_label.text = "实测速: " + " | ".join(parts)
        self.velocity_live_label.theme_text_color = "Primary"

    def _update_human_detection_ui(self, payload):
        """更新人检测订阅摘要。"""
        if not isinstance(payload, dict) or not payload:
            self.human_detection_label.text = "人检测: 暂无数据"
            self.human_detection_label.theme_text_color = "Hint"
            self._sync_dashboard_overview()
            return

        targets = self._extract_human_target_list(payload)
        count = self._extract_first_number(payload, ("count", "human_count", "person_count", "detected_count", "target_count"))
        if count is None and targets:
            count = float(len(targets))

        detected = self._extract_first_bool(payload, (
            "human_detected", "person_detected", "detected", "has_human", "has_person", "exist_human"
        ))
        if detected is None:
            detected = bool(targets) or (count is not None and count > 0)

        distance = self._extract_first_number(payload, ("closest_distance", "min_distance", "distance", "nearest_distance"))
        confidence = self._extract_first_number(payload, ("confidence", "score", "probability"))

        if not detected and not targets and (count is None or count <= 0):
            self.human_detection_label.text = "人检测: 未发现人员"
            self.human_detection_label.theme_text_color = "Hint"
            return

        parts = []
        if count is not None:
            parts.append(f"{int(round(count))} 人")
        else:
            parts.append("检测到人员")
        if distance is not None:
            parts.append(f"最近 {distance:.2f} m")
        if confidence is not None:
            parts.append(f"置信度 {confidence:.2f}")

        self.human_detection_label.text = "人检测: " + " | ".join(parts)
        self.human_detection_label.theme_text_color = "Primary"
        self._sync_dashboard_overview()

    def _extract_nested_number(self, payload, candidate_paths):
        """按候选路径提取数值，兼容嵌套字典。"""
        if not isinstance(payload, dict):
            return None
        for path in candidate_paths:
            current = payload
            valid = True
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    valid = False
                    break
                current = current.get(key)
            if valid and current not in (None, ""):
                try:
                    return float(current)
                except (TypeError, ValueError):
                    continue
        return None

    def _extract_first_bool(self, payload, candidate_keys):
        """递归提取第一个可识别布尔值。"""
        if isinstance(payload, dict):
            for key in candidate_keys:
                if key in payload:
                    parsed = self._coerce_bool(payload.get(key))
                    if parsed is not None:
                        return parsed
            for value in payload.values():
                parsed = self._extract_first_bool(value, candidate_keys)
                if parsed is not None:
                    return parsed
        elif isinstance(payload, list):
            for item in payload:
                parsed = self._extract_first_bool(item, candidate_keys)
                if parsed is not None:
                    return parsed
        return None

    def _coerce_bool(self, value):
        """把常见字符串/数字转换为布尔值。"""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("true", "1", "yes", "y", "detected", "found", "on", "有人"):
                return True
            if text in ("false", "0", "no", "n", "none", "off", "无人"):
                return False
        return None

    def _extract_human_target_list(self, payload):
        """尽量从人检测 payload 中提取目标列表。"""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("people", "persons", "humans", "detections", "targets", "boxes", "objects", "list", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []
    
    def _safe_float(self, value, default=0.0):

        """安全转换为浮点数"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _handle_robot_message(self, data):
        """处理机器人返回的通用消息"""
        msg_type = data.get("type")
        if msg_type == "notification":
            self.show_dialog("系统通知", self._format_notification(data))
            return

        if msg_type != "response":
            return

        command = data.get("command", "")
        base_command = self._normalize_command(command)
        status = data.get("status")
        if not self._is_success_status(status):
            if base_command == "/api/get_params":
                self.silent_params_refresh = False
            elif base_command == "/api/markers/query_list":
                self.silent_marker_refresh = False
                self.auto_charge_lookup_in_progress = False
            elif base_command == "/api/move":
                self.auto_charge_triggered = False
                self._refresh_auto_charge_status_line()
            self.show_dialog("指令执行失败", self._format_error_response(data))
            return

        self._handle_success_response(command, data)

    def _is_success_status(self, status):
        """判断接口响应是否成功"""
        if status in (None, ""):
            return True
        return str(status).strip().lower() in ("success", "ok", "true", "0", "200")

    def _normalize_command(self, command):
        """将带查询参数的命令归一化为基础路径"""
        return str(command or "").split("?", 1)[0]

    def _handle_success_response(self, command, data):
        """处理成功响应"""
        results = data.get("results")
        raw_command = str(command or "")
        base_command = self._normalize_command(command)

        if base_command == "/api/wifi/list":
            self.show_dialog("WiFi 列表", self._format_wifi_results(results))
        elif base_command == "/api/wifi/detail_list":
            self.show_dialog("WiFi 详细列表", self._format_wifi_detail_results(results))
        elif base_command == "/api/wifi/get_active_connection":
            active_wifi = self._extract_active_wifi_name(results)
            self.current_wifi_label.text = f"当前 WiFi: {active_wifi}"
            self.show_dialog("当前 WiFi", self._format_active_wifi_results(results))
        elif base_command == "/api/wifi/info":
            summary = self._summarize_network_info(results)
            self.network_info_label.text = f"网络信息: {summary}"
            self.show_dialog("网络信息", self._format_network_info(results))
        elif base_command == "/api/wifi/connect":
            ssid = self.wifi_ssid_input.text.strip() or self._extract_active_wifi_name(results)
            ssid = ssid or "目标 WiFi"
            self.current_wifi_label.text = f"当前 WiFi: 正在切换到 {ssid}"
            self.show_toast(f"已发送连接请求：{ssid}")
            Clock.schedule_once(lambda dt: self.get_active_wifi_info(), 2.5)
            Clock.schedule_once(lambda dt: self.get_network_info_action(), 3.0)
        elif base_command == "/api/robot_info":
            product_id = self._extract_robot_product_id(results)
            self.robot_info_label.text = f"机器人信息: {product_id}"
            self.show_dialog("机器人信息", self._format_robot_info(results))
        elif base_command == "/api/software/get_version":
            version_text = self._extract_version_text(results)
            self.system_version_label.text = f"软件版本: {version_text}"
            self.show_dialog("软件版本", self._format_version_results(results))
        elif base_command == "/api/software/check_for_update":
            summary = self._summarize_update_results(results)
            self.system_version_label.text = f"软件版本: {summary}"
            self.show_dialog("检查更新结果", self._format_update_results(results))
        elif base_command in ("/api/get_power_status", "/api/getpowerstatus"):
            summary = self._summarize_power_status(results)
            self.power_summary_label.text = f"电源状态: {summary}"
            self.show_dialog("电源状态", self._format_power_status(results))
        elif base_command == "/api/get_params":
            summary = self._summarize_speed_params(results)
            self.speed_summary_label.text = f"速度参数: {summary}"
            self._apply_speed_params(results)
            if self.silent_params_refresh:
                self.silent_params_refresh = False
            else:
                self.show_dialog("运行参数", self._format_params(results))
        elif base_command == "/api/set_params":
            self.show_toast("已发送速度参数，正在回读校验")
            Clock.schedule_once(lambda dt: self.get_speed_params_action(silent=True), 0.8)
        elif base_command == "/api/request_data":
            if "topic=robot_velocity" in raw_command and not self.latest_velocity_payload:
                self.velocity_live_label.text = "实测速: 已订阅，等待数据"
                self.velocity_live_label.theme_text_color = "Hint"
            elif "topic=human_detection" in raw_command and not self.latest_human_detection_payload:
                self.human_detection_label.text = "人检测: 已订阅，等待数据"
                self.human_detection_label.theme_text_color = "Hint"
        elif base_command == "/api/diagnosis/get_result":
            summary = self._summarize_diagnosis_results(results)
            self.diagnosis_summary_label.text = f"自诊断: {summary}"
            self.show_dialog("自诊断结果", self._format_diagnosis_results(results))
        elif base_command == "/api/get_planned_path":
            summary = self._summarize_current_path(results)
            self.plan_summary_label.text = f"规划结果: {summary}"
            self.show_dialog("当前全局路径", self._format_current_path_results(results))
        elif base_command == "/api/lift_status":
            self.show_dialog("电梯状态", self._format_lift_status(results))
        elif base_command == "/api/map/list":
            self.show_dialog("地图列表", self._format_map_results(results))
        elif base_command == "/api/map/list_info":
            self.show_dialog("地图详情", self._format_map_results(results))
        elif base_command == "/api/map/get_current_map":
            map_name = self._extract_current_map_name(results)
            self._update_current_map_label(map_name)
            self.show_toast(f"当前地图: {map_name}")
        elif base_command == "/api/markers/query_list":
            self._cache_marker_results(results)
            if self.silent_marker_refresh:
                self.silent_marker_refresh = False
            else:
                self.show_dialog("点位列表", self._format_marker_results(results))
        elif base_command == "/api/markers/query_brief":
            self.show_dialog("点位列表", self._format_marker_results(results))
        elif base_command == "/api/markers/count":
            self.show_dialog("点位数量", self._pretty_text(results, "未收到点位数量"))
        elif base_command in ("/api/markers/insert", "/api/markers/insert_by_pose"):
            marker_name = self.marker_input.text.strip() or "新点位"
            self.show_toast(f"已记录点位：{marker_name}")
            Clock.schedule_once(lambda dt: self.refresh_charge_dock_candidates(silent=True), 0.6)
        elif base_command == "/api/markers/delete":
            marker_name = self.marker_input.text.strip() or "目标点位"
            self.show_toast(f"已删除点位：{marker_name}")
            Clock.schedule_once(lambda dt: self.refresh_charge_dock_candidates(silent=True), 0.6)
        elif base_command == "/api/map/set_current_map":
            map_name = self.map_input.text.strip() or self._extract_current_map_name(results)
            self._update_current_map_label(map_name)
            self.show_toast(f"已切换地图：{map_name}")
            Clock.schedule_once(lambda dt: self.refresh_charge_dock_candidates(silent=True), 1.0)
        elif base_command == "/api/map/distance_probe":
            summary = self._summarize_probe_results(results)
            self.plan_summary_label.text = f"规划结果: {summary}"
            self.show_dialog("障碍探测结果", self._format_probe_results(results))
        elif base_command == "/api/map/accessible_point_query":
            summary = self._summarize_accessible_point(results)
            self.plan_summary_label.text = f"规划结果: {summary}"
            self.show_dialog("可达点结果", self._format_accessible_results(results))
        elif base_command == "/api/make_plan":
            summary = self._summarize_plan_results(results)
            self.plan_summary_label.text = f"规划结果: {summary}"
            self.show_dialog("路径规划结果", self._format_plan_results(results))
        elif base_command == "/api/position_adjust":
            marker_name = self.marker_input.text.strip() or "目标点位"
            self.show_toast(f"已发送按点位校准：{marker_name}")
        elif base_command == "/api/position_adjust_by_pose":
            self.show_toast("已发送按坐标校准指令")
        elif base_command == "/api/LED/set_luminance":
            self.show_toast("已发送灯带亮度设置")
        elif base_command == "/api/estop":
            flag_enabled = "flag=true" in raw_command.lower()
            self.show_toast("已触发软件急停" if flag_enabled else "已解除软件急停")
        elif base_command in ("/api/move/cancel", "/api/cancel_move"):
            self.auto_charge_triggered = False
            self._refresh_auto_charge_status_line()
            self.show_toast("已发送取消导航指令")
        elif base_command == "/api/move":
            if "location=" in raw_command:
                pose = self._parse_pose_inputs()
                if pose is None:
                    target_desc = "目标坐标"
                else:
                    x, y, _ = pose
                    target_desc = f"坐标 ({x:.2f}, {y:.2f})"
            elif "markers=" in raw_command:
                target_desc = "多目标巡游"
            else:
                target_desc = self.marker_input.text.strip() or self.charge_dock_input.text.strip() or "目标点"
            self._set_notice(f"已发送导航指令：{target_desc}")

        self._sync_dashboard_overview()


    def _format_notification(self, data):
        """格式化通知消息"""
        code = data.get("code", "未知")
        description = data.get("description", "无详细描述")
        return f"状态码: {code}\n说明: {description}"

    def _format_error_response(self, data):
        """格式化失败响应"""
        command = data.get("command", "未知指令")
        status = data.get("status", "未知状态")
        description = data.get("description") or data.get("message") or "底盘未返回详细原因"
        return f"指令: {command}\n状态: {status}\n说明: {description}"

    def _extract_list(self, payload):
        """尽量从响应中提取列表数据"""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in (
                "list", "items", "data", "results", "wifi_list", "map_list",
                "marker_list", "markers", "path", "points", "waypoints", "candidates"
            ):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _extract_power_percent(self, payload):
        """尽量提取电量百分比"""
        if isinstance(payload, dict):
            for key in ("power_percent", "battery_percent", "battery_capacity", "percent", "soc"):
                value = payload.get(key)
                if value not in (None, ""):
                    try:
                        return int(round(float(value)))
                    except (TypeError, ValueError):
                        pass
        return None

    def _extract_charging_state(self, payload):
        """尽量提取是否处于充电状态"""
        if isinstance(payload, dict):
            for key in ("charger_connected_notice", "is_charging", "charging", "charger_connected"):
                value = payload.get(key)
                if value is None:
                    continue
                if isinstance(value, bool):
                    return value
                text = str(value).strip().lower()
                if text in ("true", "1", "yes", "charging"):
                    return True
                if text in ("false", "0", "no", "discharging"):
                    return False
            battery_current = payload.get("battery_current") or payload.get("current")
            if battery_current not in (None, ""):
                try:
                    return float(battery_current) > 0
                except (TypeError, ValueError):
                    pass
        return False

    def _extract_marker_items(self, payload):
        """兼容 query_list/query_brief 的不同返回格式，统一抽成点位列表"""
        items = self._extract_list(payload)
        if items:
            return items
        if isinstance(payload, dict):
            normalized = []
            for key, value in payload.items():
                if not isinstance(value, dict):
                    continue
                item = dict(value)
                item.setdefault("name", item.get("marker_name") or key)
                item.setdefault("marker_name", item.get("name") or key)
                pose = item.get("pose")
                if isinstance(pose, dict):
                    position = pose.get("position")
                    if isinstance(position, dict):
                        item.setdefault("x", position.get("x"))
                        item.setdefault("y", position.get("y"))
                    orientation = pose.get("orientation")
                    if isinstance(orientation, dict):
                        item.setdefault("orientation", orientation)
                normalized.append(item)
            if normalized:
                return normalized
        return []

    def _select_charge_dock_marker(self, items):
        """优先选 type=11 的充电桩点位，次选名称关键词匹配。"""
        exact_type_matches = []
        keyword_matches = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("marker_name") or item.get("name") or item.get("marker") or "").strip()
            if not name:
                continue
            marker_type = item.get("key")
            if marker_type is None:
                marker_type = item.get("type")
            try:
                marker_type = int(marker_type) if marker_type is not None else None
            except (TypeError, ValueError):
                marker_type = None
            if marker_type == CHARGE_DOCK_TYPE:
                exact_type_matches.append(name)
                continue
            lowered = name.lower()
            if any(keyword in lowered for keyword in CHARGE_DOCK_KEYWORDS):
                keyword_matches.append(name)
        if exact_type_matches:
            return exact_type_matches[0]
        if keyword_matches:
            return keyword_matches[0]
        return ""

    def _cache_marker_results(self, payload):
        """缓存点位数据并尝试自动识别充电桩"""
        self.auto_charge_lookup_in_progress = False
        items = self._extract_marker_items(payload)
        if items:
            self.marker_cache = items
            detected = self._select_charge_dock_marker(items)
            manual_name = self.charge_dock_input.text.strip()
            if detected and not manual_name:
                self.charge_dock_input.text = detected
                self.charge_dock_marker_name = detected
            elif manual_name:
                self.charge_dock_marker_name = manual_name
            elif detected:
                self.charge_dock_marker_name = detected
        self._refresh_auto_charge_status_line()

    def _get_charge_dock_name(self):
        """获取当前用于回充的充电桩点位名称"""
        manual_name = self.charge_dock_input.text.strip()
        if manual_name:
            self.charge_dock_marker_name = manual_name
            return manual_name
        if self.charge_dock_marker_name:
            return self.charge_dock_marker_name
        detected = self._select_charge_dock_marker(self.marker_cache)
        if detected:
            self.charge_dock_marker_name = detected
            return detected
        return ""

    def _update_drive_profile_label(self):
        """同步显示当前遥控速度配置"""
        summary = f"遥控速度: 直线 {self.linear_speed_limit:.2f} m/s | 角速度 {self.angular_speed_limit:.2f} rad/s"
        if hasattr(self, "drive_profile_label"):
            self.drive_profile_label.text = summary
        if hasattr(self, "speed_summary_label"):
            self.speed_summary_label.text = f"速度参数: 直线 {self.linear_speed_limit:.2f} m/s | 角速度 {self.angular_speed_limit:.2f} rad/s"

    def _summarize_speed_params(self, payload):
        """生成速度参数摘要"""
        if isinstance(payload, dict):
            linear = payload.get("max_speed_linear")
            angular = payload.get("max_speed_angular")
            parts = []
            if linear not in (None, ""):
                parts.append(f"直线 {self._safe_float(linear):.2f} m/s")
            if angular not in (None, ""):
                parts.append(f"角速度 {self._safe_float(angular):.2f} rad/s")
            if parts:
                return " | ".join(parts)
        return "未读取到速度参数"

    def _format_params(self, payload):
        """格式化运行参数，适合弹窗查看"""
        if isinstance(payload, dict) and payload:
            lines = []
            for key in sorted(payload.keys()):
                lines.append(f"{key}: {payload.get(key)}")
            return "\n".join(lines)
        return self._pretty_text(payload, "未收到运行参数")

    def _apply_speed_params(self, payload):
        """把 get_params 结果回填到界面与遥控速度上限"""
        if not isinstance(payload, dict):
            return
        self.speed_params = dict(payload)
        linear = payload.get("max_speed_linear")
        angular = payload.get("max_speed_angular")
        if linear not in (None, ""):
            self.linear_speed_limit = max(0.1, min(1.0, self._safe_float(linear, self.linear_speed_limit)))
            self.linear_speed_input.text = f"{self.linear_speed_limit:.2f}"
        if angular not in (None, ""):
            self.angular_speed_limit = max(0.5, min(3.5, self._safe_float(angular, self.angular_speed_limit)))
            self.angular_speed_input.text = f"{self.angular_speed_limit:.2f}"
        self._update_drive_profile_label()

    def _current_auto_charge_threshold(self):
        """读取自动回充阈值，非法时回退默认值 20。"""
        raw_value = self.auto_charge_threshold_input.text.strip() or "20"
        try:
            value = int(raw_value)
        except ValueError:
            value = 20
        return max(5, min(80, value))

    def _refresh_auto_charge_status_line(self, status_payload=None):
        """刷新自动回充状态摘要"""
        threshold = self._current_auto_charge_threshold()
        dock_name = self._get_charge_dock_name() or "待识别"
        extra = ""
        if isinstance(status_payload, dict):
            move_status = str(status_payload.get("move_status") or "").strip()
            if self._extract_charging_state(status_payload):
                extra = " | 充电中"
            elif move_status in ("dock_to_charging_pile", "leave_charging_pile"):
                extra = f" | {move_status}"
            elif self.auto_charge_triggered:
                extra = " | 低电量回充中"
        elif self.auto_charge_triggered:
            extra = " | 低电量回充中"
        if hasattr(self, "auto_charge_label"):
            self.auto_charge_label.text = f"自动回充: 阈值 {threshold}% | 充电桩 {dock_name}{extra}"

    def _extract_current_map_name(self, payload):

        """尽量从响应中提取当前地图名称"""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, dict):
            for key in ("map_name", "name", "current_map", "map"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return "--"

    def _update_current_map_label(self, map_name):
        """更新当前地图标签"""
        self.current_map_label.text = f"当前地图: {map_name or '--'}"
        self._sync_dashboard_overview()

    def _extract_active_wifi_name(self, payload):
        """尽量从响应中提取当前连接的 WiFi 名称"""
        if isinstance(payload, str):
            return payload.strip() or "--"
        if isinstance(payload, dict):
            for key in ("SSID", "ssid", "name", "current_wifi", "active_wifi"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for key in ("connection", "wifi", "results", "data"):
                value = payload.get(key)
                if isinstance(value, dict):
                    nested_name = self._extract_active_wifi_name(value)
                    if nested_name != "--":
                        return nested_name
        return "--"

    def _summarize_network_info(self, payload):
        """生成一行网络摘要，适合放在界面上"""
        if isinstance(payload, dict):
            wifi_name = self._extract_active_wifi_name(payload)
            ip = payload.get("ip") or payload.get("ip_address") or payload.get("robot_ip")
            gateway = payload.get("gateway") or payload.get("gw")
            summary_parts = []
            if wifi_name != "--":
                summary_parts.append(f"WiFi {wifi_name}")
            if ip:
                summary_parts.append(f"IP {ip}")
            if gateway:
                summary_parts.append(f"网关 {gateway}")
            if summary_parts:
                return " | ".join(summary_parts)
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
        return "--"

    def _format_active_wifi_results(self, payload):
        """格式化当前 WiFi 详情"""
        if isinstance(payload, dict):
            lines = []
            wifi_name = self._extract_active_wifi_name(payload)
            if wifi_name != "--":
                lines.append(f"SSID: {wifi_name}")
            for label, key in (("信号", "signal"), ("IP", "ip"), ("网关", "gateway"), ("MAC", "mac")):
                value = payload.get(key)
                if value not in (None, ""):
                    lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到当前 WiFi 信息")

    def _format_network_info(self, payload):
        """格式化网络信息"""
        if isinstance(payload, dict):
            lines = []
            wifi_name = self._extract_active_wifi_name(payload)
            if wifi_name != "--":
                lines.append(f"当前 WiFi: {wifi_name}")
            field_map = (
                ("机器人 IP", "ip"),
                ("IP 地址", "ip_address"),
                ("子网掩码", "mask"),
                ("网关", "gateway"),
                ("DNS", "dns"),
                ("无线网卡", "wlan"),
                ("MAC 地址", "mac"),
            )
            seen = set()
            for label, key in field_map:
                value = payload.get(key)
                if value not in (None, "") and (label, value) not in seen:
                    seen.add((label, value))
                    lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到网络信息")

    def _extract_first_number(self, payload, candidate_keys):
        """递归提取第一个可用数值"""
        if isinstance(payload, dict):
            for key in candidate_keys:
                value = payload.get(key)
                if isinstance(value, (int, float)):
                    return float(value)
                if isinstance(value, str):
                    try:
                        return float(value)
                    except ValueError:
                        pass
            for value in payload.values():
                result = self._extract_first_number(value, candidate_keys)
                if result is not None:
                    return result
        elif isinstance(payload, list):
            for item in payload:
                result = self._extract_first_number(item, candidate_keys)
                if result is not None:
                    return result
        return None

    def _extract_first_point(self, payload):
        """递归提取第一个坐标点"""
        if isinstance(payload, dict):
            x = payload.get("x")
            y = payload.get("y")
            if x is not None and y is not None:
                return self._safe_float(x), self._safe_float(y)
            for value in payload.values():
                point = self._extract_first_point(value)
                if point is not None:
                    return point
        elif isinstance(payload, list):
            for item in payload:
                point = self._extract_first_point(item)
                if point is not None:
                    return point
        return None

    def _summarize_probe_results(self, payload):
        """生成障碍探测摘要"""
        distance = self._extract_first_number(payload, ("distance", "min_distance", "obstacle_distance", "value"))
        if distance is not None:
            return f"最近障碍约 {distance:.2f} m"
        return "已收到障碍探测结果"

    def _format_probe_results(self, payload):
        """格式化障碍探测结果"""
        distance = self._extract_first_number(payload, ("distance", "min_distance", "obstacle_distance", "value"))
        if distance is not None:
            lines = [f"最近障碍距离: {distance:.2f} m"]
            if isinstance(payload, dict):
                point = self._extract_first_point(payload)
                if point is not None:
                    lines.append(f"对应点位: ({point[0]:.2f}, {point[1]:.2f})")
            return "\n".join(lines)
        return self._pretty_text(payload, "未收到障碍探测结果")

    def _summarize_accessible_point(self, payload):
        """生成可达点摘要"""
        point = self._extract_first_point(payload)
        if point is not None:
            return f"最近可达点 ({point[0]:.2f}, {point[1]:.2f})"
        return "已收到可达点查询结果"

    def _format_accessible_results(self, payload):
        """格式化可达点结果"""
        point = self._extract_first_point(payload)
        if point is not None:
            return f"推荐可达点: ({point[0]:.2f}, {point[1]:.2f})\n\n{self._pretty_text(payload, '')}".strip()
        return self._pretty_text(payload, "未收到可达点结果")

    def _summarize_plan_results(self, payload):
        """生成路径规划摘要"""
        path_points = self._extract_list(payload)
        if path_points:
            return f"规划成功，路径点 {len(path_points)} 个"
        distance = self._extract_first_number(payload, ("distance", "path_length", "total_distance", "length"))
        if distance is not None:
            return f"规划成功，路径长度约 {distance:.2f} m"
        return "已收到路径规划结果"

    def _format_plan_results(self, payload):
        """格式化路径规划结果"""
        items = self._extract_list(payload)
        if items:
            preview = []
            for index, item in enumerate(items[:10], start=1):
                if isinstance(item, dict):
                    x = item.get("x")
                    y = item.get("y")
                    if x is not None and y is not None:
                        preview.append(f"{index}. ({self._safe_float(x):.2f}, {self._safe_float(y):.2f})")
                    else:
                        preview.append(f"{index}. {json.dumps(item, ensure_ascii=False)}")
                else:
                    preview.append(f"{index}. {item}")
            if len(items) > 10:
                preview.append(f"... 共 {len(items)} 个路径点")
            return "\n".join(preview)
        return self._pretty_text(payload, "未收到路径规划结果")

    def _pretty_text(self, payload, empty_text="暂无数据"):
        """将任意结果转成可展示的文本"""
        if payload in (None, "", [], {}):
            return empty_text
        if isinstance(payload, str):
            return payload
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _format_wifi_results(self, payload):
        """格式化 WiFi 列表"""
        items = self._extract_list(payload)
        if not items:
            return self._pretty_text(payload, "未收到 WiFi 列表数据")

        lines = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                ssid = item.get("SSID") or item.get("ssid") or item.get("name") or f"WiFi {index}"
                signal = item.get("signal") or item.get("signal_level") or item.get("level")
                security = item.get("security") or item.get("encryption") or item.get("auth")
                extras = []
                if signal is not None:
                    extras.append(f"信号: {signal}")
                if security:
                    extras.append(f"加密: {security}")
                if extras:
                    lines.append(f"{index}. {ssid} ({'，'.join(extras)})")
                else:
                    lines.append(f"{index}. {ssid}")
            else:
                lines.append(f"{index}. {item}")
        return "\n".join(lines)

    def _format_map_results(self, payload):
        """格式化地图列表"""
        items = self._extract_list(payload)
        if not items:
            return self._pretty_text(payload, "未收到地图列表数据")

        lines = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                map_name = item.get("map_name") or item.get("name") or item.get("title") or f"地图 {index}"
                floor = item.get("floor") or item.get("floor_id")
                version = item.get("version")
                extras = []
                if floor is not None:
                    extras.append(f"楼层: {floor}")
                if version is not None:
                    extras.append(f"版本: {version}")
                if extras:
                    lines.append(f"{index}. {map_name} ({'，'.join(extras)})")
                else:
                    lines.append(f"{index}. {map_name}")
            else:
                lines.append(f"{index}. {item}")
        return "\n".join(lines)

    def _format_marker_results(self, payload):
        """格式化点位列表"""
        items = self._extract_marker_items(payload)
        if not items:
            return self._pretty_text(payload, "未收到点位列表数据")

        lines = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                marker_name = item.get("name") or item.get("marker") or item.get("marker_name") or f"点位 {index}"
                x = item.get("x")
                y = item.get("y")
                floor = item.get("floor")
                marker_type = item.get("key") if item.get("key") is not None else item.get("type")
                extras = []
                if x is not None and y is not None:
                    extras.append(f"坐标: ({self._safe_float(x):.2f}, {self._safe_float(y):.2f})")
                if floor is not None:
                    extras.append(f"楼层: {floor}")
                if marker_type is not None:
                    type_text = "充电桩" if str(marker_type) == str(CHARGE_DOCK_TYPE) else f"类型 {marker_type}"
                    extras.append(type_text)
                if extras:
                    lines.append(f"{index}. {marker_name} ({'，'.join(extras)})")
                else:
                    lines.append(f"{index}. {marker_name}")
            else:
                lines.append(f"{index}. {item}")
        return "\n".join(lines)


    def _ensure_connected(self):
        """检查机器人是否已连接"""
        if self.robot and self.robot.connected:
            return True
        self.show_toast("请先连接机器人")
        return False

    def _parse_floor_input(self):
        """解析楼层输入"""
        value = self.floor_input.text.strip() or "1"
        try:
            return int(value)
        except ValueError:
            self.show_dialog("输入有误", "楼层必须是整数，例如 1 或 2。")
            return None

    def _parse_float_input(self, raw_value, field_name):
        """解析浮点输入"""
        value = raw_value.strip()
        if not value:
            self.show_dialog("缺少坐标", f"请输入{field_name}。")
            return None
        try:
            return float(value)
        except ValueError:
            self.show_dialog("输入有误", f"{field_name} 必须是数字，例如 1.25 或 -0.80。")
            return None

    def _parse_optional_float_input(self, raw_value, field_name, min_value=None, max_value=None, default=None):
        """解析可选浮点输入，为空时返回默认值"""
        value = raw_value.strip()
        if not value:
            return default
        try:
            result = float(value)
        except ValueError:
            self.show_dialog("输入有误", f"{field_name} 必须是数字。")
            return None
        if min_value is not None and result < min_value:
            self.show_dialog("输入有误", f"{field_name} 不能小于 {min_value}。")
            return None
        if max_value is not None and result > max_value:
            self.show_dialog("输入有误", f"{field_name} 不能大于 {max_value}。")
            return None
        return result

    def _parse_optional_int_input(self, raw_value, field_name, min_value=None, max_value=None, default=None):
        """解析可选整数输入，为空时返回默认值"""
        value = raw_value.strip()
        if not value:
            return default
        try:
            result = int(value)
        except ValueError:
            self.show_dialog("输入有误", f"{field_name} 必须是整数。")
            return None
        if min_value is not None and result < min_value:
            self.show_dialog("输入有误", f"{field_name} 不能小于 {min_value}。")
            return None
        if max_value is not None and result > max_value:
            self.show_dialog("输入有误", f"{field_name} 不能大于 {max_value}。")
            return None
        return result

    def _parse_speed_settings(self):
        """解析速度设置输入"""
        linear = self._parse_optional_float_input(
            self.linear_speed_input.text,
            "直线速度",
            min_value=0.1,
            max_value=1.0,
            default=self.linear_speed_limit,
        )
        if linear is None:
            return None
        angular = self._parse_optional_float_input(
            self.angular_speed_input.text,
            "角速度",
            min_value=0.5,
            max_value=3.5,
            default=self.angular_speed_limit,
        )
        if angular is None:
            return None
        return linear, angular

    def _get_navigation_options(self):
        """读取高级导航参数设置"""
        distance_tolerance = self._parse_optional_float_input(
            self.nav_distance_tolerance_input.text,
            "距离容差",
            min_value=0.0,
            default=0.35,
        )
        if distance_tolerance is None:
            return None
        theta_tolerance = self._parse_optional_float_input(
            self.nav_theta_tolerance_input.text,
            "角度容差",
            min_value=0.0,
            default=0.35,
        )
        if theta_tolerance is None:
            return None
        occupied_tolerance = self._parse_optional_float_input(
            self.nav_occupied_tolerance_input.text,
            "让步停靠距离",
            min_value=0.1,
            default=0.45,
        )
        if occupied_tolerance is None:
            return None
        max_continuous_retries = self._parse_optional_int_input(
            self.nav_retry_input.text,
            "最大连续重试次数",
            min_value=0,
            default=30,
        )
        if max_continuous_retries is None:
            return None
        angle_offset = self._parse_optional_float_input(
            self.nav_angle_offset_input.text,
            "角度偏移",
            min_value=-3.14,
            max_value=3.14,
            default=0.0,
        )
        if angle_offset is None:
            return None
        yaw_goal_reverse_allowed = self._parse_optional_int_input(
            self.nav_reverse_allowed_input.text,
            "双向停靠参数",
            min_value=-1,
            max_value=1,
            default=-1,
        )
        if yaw_goal_reverse_allowed is None:
            return None
        return {
            "distance_tolerance": distance_tolerance,
            "theta_tolerance": theta_tolerance,
            "occupied_tolerance": occupied_tolerance,
            "max_continuous_retries": max_continuous_retries,
            "angle_offset": angle_offset,
            "yaw_goal_reverse_allowed": yaw_goal_reverse_allowed,
        }

    def _parse_plan_target(self):
        """解析路径规划目标点输入"""
        target_x = self._parse_float_input(self.plan_target_x_input.text, "目标 X")
        if target_x is None:
            return None

        target_y = self._parse_float_input(self.plan_target_y_input.text, "目标 Y")
        if target_y is None:
            return None

        floor_text = self.plan_target_floor_input.text.strip() or self.floor_input.text.strip() or "1"
        try:
            floor = int(floor_text)
        except ValueError:
            self.show_dialog("输入有误", "目标楼层必须是整数，例如 1 或 2。")
            return None

        return target_x, target_y, floor

    def _parse_pose_inputs(self):
        """解析地图区输入的 X/Y/θ 目标位姿。"""
        pose_x = self._parse_float_input(self.pose_x_input.text, "X 坐标")
        if pose_x is None:
            return None

        pose_y = self._parse_float_input(self.pose_y_input.text, "Y 坐标")
        if pose_y is None:
            return None

        theta_text = self.pose_theta_input.text.strip() or "0"
        try:
            theta = float(theta_text)
        except ValueError:
            self.show_dialog("输入有误", "θ 必须是数字，例如 0、1.57 或 -3.14。")
            return None

        return pose_x, pose_y, theta

    def _get_current_pose(self):
        """获取最近一次状态中的当前位置"""
        pose = self.last_status.get("current_pose", {}) if isinstance(self.last_status, dict) else {}
        if not isinstance(pose, dict):
            pose = {}

        x = pose.get("x")
        y = pose.get("y")
        if x is None or y is None:
            self.show_dialog("缺少当前位置", "还没有拿到机器人当前坐标，请先点一次“获取状态”再做路径规划。")
            return None

        return self._safe_float(x), self._safe_float(y)


    def _send_robot_command(self, sender, pending_message=None, status_text=None):
        """统一发送机器人指令并处理失败反馈"""
        if not self._ensure_connected():
            return False

        try:
            success = sender()
        except Exception as exc:
            self.show_dialog("发送失败", f"发送指令时出现异常：{exc}")
            return False

        if not success:
            self._apply_disconnected_ui("❌ 指令发送失败")
            self.show_dialog("发送失败", "指令未成功发出，连接可能已经断开。")
            return False

        if status_text:
            self._set_notice(status_text)
        if pending_message:
            self.show_toast(pending_message)
        return True

    def send_joy_control(self, linear, angular):
        """发送遥控指令（按钮输入为系数，实际速度由速度设置决定）"""
        actual_linear = max(-self.linear_speed_limit, min(self.linear_speed_limit, linear * self.linear_speed_limit))
        actual_angular = max(-self.angular_speed_limit, min(self.angular_speed_limit, angular * self.angular_speed_limit))
        status_text = None
        if actual_linear != 0 or actual_angular != 0:
            status_text = f"遥控速度 v={actual_linear:.2f} m/s, w={actual_angular:.2f} rad/s"
        self._send_robot_command(
            lambda: self.robot.move_direct(actual_linear, actual_angular),
            status_text=status_text,
        )

    def _start_joy_control(self, linear, angular):
        """开始连续遥控（按住按钮时调用）"""
        self._joy_control_linear = linear
        self._joy_control_angular = angular
        self._joy_control_active = True
        # 立即发送一次
        self.send_joy_control(linear, angular)
        # 启动定时器，每100ms重复发送，确保底盘持续运动
        if self._joy_control_event:
            self._joy_control_event.cancel()
        self._joy_control_event = Clock.schedule_interval(
            lambda dt: self._joy_control_tick(), 0.1
        )

    def _joy_control_tick(self):
        """定时发送遥控指令"""
        if self._joy_control_active and self.robot and self.robot.connected:
            self.send_joy_control(self._joy_control_linear, self._joy_control_angular)
        else:
            if self._joy_control_event:
                self._joy_control_event.cancel()
                self._joy_control_event = None

    def _stop_joy_control(self):
        """停止连续遥控（松开按钮时调用）"""
        self._joy_control_active = False
        if self._joy_control_event:
            self._joy_control_event.cancel()
            self._joy_control_event = None
        # 发送停止指令
        self.send_joy_control(0.0, 0.0)

    def get_robot_status(self):
        """获取机器人状态"""
        self._send_robot_command(
            lambda: self.robot.get_status(),
            pending_message="📊 正在获取状态...",
        )

    def _subscribe_live_topics(self, silent=False):
        """统一订阅实时 topic。"""
        if not self.robot or not self.robot.connected:
            if not silent:
                self.show_toast("请先连接机器人")
            return False

        failed_topics = []
        for topic, frequency in LIVE_SUBSCRIPTION_TOPICS:
            try:
                success = self.robot.subscribe_data(topic=topic, frequency=frequency)
            except Exception as exc:
                failed_topics.append(f"{topic}（{exc}）")
                continue
            if not success:
                failed_topics.append(topic)

        if failed_topics:
            self._apply_disconnected_ui("实时订阅发送失败")
            if not silent:
                self.show_dialog("实时订阅失败", "以下 topic 发送失败：\n" + "\n".join(failed_topics))
            return False

        if not silent:
            self._set_notice("已重订阅 robot_status / robot_velocity / human_detection")
        return True

    def resubscribe_live_topics_action(self):
        """手动重新订阅速度和人检测实时数据。"""
        if self._subscribe_live_topics(silent=False):
            self.show_toast("已重新发送实时订阅请求")

    def get_speed_params_action(self, silent=False):
        """读取当前速度参数"""
        self.silent_params_refresh = silent
        self._send_robot_command(
            lambda: self.robot.get_params(),
            pending_message=None if silent else "正在读取速度参数...",
        )

    def apply_speed_settings_action(self):
        """应用速度设置，同时更新遥控速度上限和导航速度参数"""
        parsed = self._parse_speed_settings()
        if parsed is None:
            return
        linear, angular = parsed
        self.linear_speed_limit = linear
        self.angular_speed_limit = angular
        self._update_drive_profile_label()
        self._send_robot_command(
            lambda: self.robot.set_params(max_speed_linear=linear, max_speed_angular=angular),
            pending_message=f"已下发速度参数：直线 {linear:.2f}，角速度 {angular:.2f}",
            status_text="正在同步速度参数",
        )

    def emergency_stop(self):
        """急停"""
        self.auto_charge_triggered = False
        self._send_robot_command(
            lambda: self.robot.set_estop(True),
            pending_message="🛑 已触发急停！",
        )

    def release_emergency_stop(self):
        """解除软件急停"""
        self._send_robot_command(
            lambda: self.robot.set_estop(False),
            pending_message="已发送解除急停指令",
            status_text="正在解除软件急停",
        )

    def refresh_charge_dock_candidates(self, silent=False):
        """刷新充电桩点位缓存"""
        if not self._ensure_connected():
            return
        self.silent_marker_refresh = silent
        self.auto_charge_lookup_in_progress = True
        self.last_auto_charge_lookup_at = time.time()
        pending_message = None if silent else "正在识别充电桩点位..."
        self._send_robot_command(
            lambda: self.robot.get_markers_list(),
            pending_message=pending_message,
            status_text="正在刷新点位缓存",
        )

    def navigate_to_charge_dock_action(self):
        """立即前往充电桩"""
        dock_name = self._get_charge_dock_name()
        if not dock_name:
            self.show_dialog("未识别到充电桩", "请先点“识别充电桩”，或手动填写充电桩点位名称。")
            return
        nav_options = self._get_navigation_options()
        if nav_options is None:
            return
        self.auto_charge_triggered = True
        self._refresh_auto_charge_status_line()
        self._send_robot_command(
            lambda: self.robot.move_to_marker(dock_name, **nav_options),
            pending_message=f"正在前往充电桩：{dock_name}",
            status_text=f"自动回充 -> {dock_name}",
        )

    def _maybe_auto_charge(self, status_payload):
        """低电量时自动前往充电桩"""
        if not isinstance(status_payload, dict) or not self.robot or not self.robot.connected:
            return
        power = self._extract_power_percent(status_payload)
        if power is None:
            return
        threshold = self._current_auto_charge_threshold()
        charging = self._extract_charging_state(status_payload)
        move_status = str(status_payload.get("move_status") or "").strip().lower()
        if charging:
            self.auto_charge_triggered = False
            self._refresh_auto_charge_status_line(status_payload)
            return
        if power > threshold + 5:
            self.auto_charge_triggered = False
        if power > threshold or self.auto_charge_triggered:
            return
        if move_status in ("dock_to_charging_pile", "leave_charging_pile"):
            self.auto_charge_triggered = True
            return
        dock_name = self._get_charge_dock_name()
        if not dock_name:
            if not self.auto_charge_lookup_in_progress and (time.time() - self.last_auto_charge_lookup_at) > 15:
                self.refresh_charge_dock_candidates(silent=True)
            return
        nav_options = self._get_navigation_options()
        if nav_options is None:
            return
        self.auto_charge_triggered = True
        self._refresh_auto_charge_status_line(status_payload)
        self._send_robot_command(
            lambda: self.robot.move_to_marker(dock_name, **nav_options),
            pending_message=f"电量低于 {threshold}% ，已自动前往充电桩：{dock_name}",
            status_text=f"低电量自动回充 -> {dock_name}",
        )

    def set_led(self, r, g, b):

        """设置灯带颜色"""
        self._send_robot_command(
            lambda: self.robot.set_led_color(r, g, b),
            pending_message=f"灯带已设置 RGB({r},{g},{b})",
        )

    def set_led_luminance_action(self):
        """设置灯带亮度"""
        raw_value = self.led_luminance_input.text.strip() or "60"
        try:
            value = int(raw_value)
        except ValueError:
            self.show_dialog("输入有误", "亮度必须是 0~100 的整数。")
            return
        if not 0 <= value <= 100:
            self.show_dialog("输入有误", "亮度必须在 0~100 之间。")
            return

        self._send_robot_command(
            lambda: self.robot.set_led_luminance(value),
            pending_message=f"已发送灯带亮度: {value}",
        )

    def get_wifi_list(self):
        """获取WiFi列表"""
        self._send_robot_command(
            lambda: self.robot.get_wifi_list(),
            pending_message="📶 正在获取WiFi列表...",
        )

    def get_active_wifi_info(self):
        """获取当前连接的 WiFi"""
        self._send_robot_command(
            lambda: self.robot.get_active_wifi(),
            pending_message="📡 正在获取当前网络...",
        )

    def get_network_info_action(self):
        """获取网络信息"""
        self._send_robot_command(
            lambda: self.robot.get_network_info(),
            pending_message="正在获取网络信息...",
        )

    def refresh_network_overview(self):
        """连续刷新当前 WiFi 与网络摘要。"""
        if not self._ensure_connected():
            return
        self.get_active_wifi_info()
        Clock.schedule_once(lambda dt: self.get_network_info_action(), 0.5)

    def connect_wifi_from_input(self):
        """根据输入的 SSID 和密码连接 WiFi"""
        ssid = self.wifi_ssid_input.text.strip()
        password = self.wifi_password_input.text
        if not ssid:
            self.show_dialog("缺少 WiFi 名称", "请输入要连接的 WiFi 名称（SSID）。")
            return

        self._send_robot_command(
            lambda: self.robot.connect_wifi(ssid, password),
            pending_message=f"📶 正在连接 WiFi：{ssid}",
            status_text=f"📶 正在切换 WiFi: {ssid}",
        )

    def fill_current_pose_to_plan_inputs(self):
        """将当前坐标写入路径规划与地图坐标输入框，便于调试"""
        pose = self._get_current_pose()
        if pose is None:
            return

        x, y = pose
        self.plan_target_x_input.text = f"{x:.2f}"
        self.plan_target_y_input.text = f"{y:.2f}"
        self.pose_x_input.text = f"{x:.2f}"
        self.pose_y_input.text = f"{y:.2f}"
        if not self.plan_target_floor_input.text.strip():
            self.plan_target_floor_input.text = self.floor_input.text.strip() or "1"
        if not self.pose_theta_input.text.strip():
            self.pose_theta_input.text = "0"
        self.show_toast("已填入当前位置，可在此基础上微调目标坐标")

    def distance_probe_action(self):
        """查询目标点附近障碍距离"""
        target = self._parse_plan_target()
        if target is None:
            return

        target_x, target_y, _ = target
        self._send_robot_command(
            lambda: self.robot.distance_probe(target_x, target_y),
            pending_message=f"📏 正在探测目标点 ({target_x:.2f}, {target_y:.2f}) 周边障碍...",
            status_text="📏 正在进行障碍探测",
        )

    def accessible_point_query_action(self):
        """查询目标点附近可达点"""
        target = self._parse_plan_target()
        if target is None:
            return

        target_x, target_y, _ = target
        self._send_robot_command(
            lambda: self.robot.accessible_point_query(target_x, target_y),
            pending_message=f"✅ 正在查询 ({target_x:.2f}, {target_y:.2f}) 附近可达点...",
            status_text="✅ 正在查询可达点",
        )

    def make_plan_action(self):
        """基于当前位置到目标点进行路径规划"""
        target = self._parse_plan_target()
        if target is None:
            return

        current_pose = self._get_current_pose()
        if current_pose is None:
            return

        start_x, start_y = current_pose
        goal_x, goal_y, floor = target
        self._send_robot_command(
            lambda: self.robot.make_plan(start_x, start_y, floor, goal_x, goal_y, floor),
            pending_message=(
                f"🧭 正在规划路径：({start_x:.2f}, {start_y:.2f}) -> ({goal_x:.2f}, {goal_y:.2f})"
            ),
            status_text="🧭 正在规划路径",
        )

    def get_current_map_info(self):
        """获取当前地图"""
        self._send_robot_command(
            lambda: self.robot.get_current_map(),
            pending_message="📍 正在获取当前地图...",
        )

    def get_markers_list(self):
        """获取点位摘要列表"""
        self._send_robot_command(
            lambda: self.robot.get_markers_brief(),
            pending_message="正在获取点位列表...",
        )

    def get_markers_count_action(self):
        """获取点位数量"""
        self._send_robot_command(
            lambda: self.robot.get_markers_count(),
            pending_message="正在获取点位数量...",
        )

    def navigate_to_marker(self):
        """导航到指定点位"""
        marker_name = self.marker_input.text.strip()
        if not marker_name:
            self.show_dialog("缺少点位名称", "请输入要前往的点位名称，例如 A001。")
            return

        self._send_robot_command(
            lambda: self.robot.move_to_marker(marker_name),
            pending_message=f"正在导航到点位：{marker_name}",
            status_text=f"正在前往: {marker_name}",
        )

    def navigate_to_pose_action(self):
        """按照地图区输入的坐标导航"""
        pose = self._parse_pose_inputs()
        if pose is None:
            return

        x, y, theta = pose
        self._send_robot_command(
            lambda: self.robot.move_to_location(x, y, theta),
            pending_message=f"正在导航到坐标 ({x:.2f}, {y:.2f}, θ={theta:.2f})",
            status_text=f"正在前往坐标 ({x:.2f}, {y:.2f})",
        )

    def insert_marker_here(self):
        """记录当前位置为点位"""
        marker_name = self.marker_input.text.strip()
        if not marker_name:
            self.show_dialog("缺少点位名称", "请输入要保存的点位名称后再记录当前位置。")
            return

        self._send_robot_command(
            lambda: self.robot.insert_marker_here(marker_name),
            pending_message=f"正在记录点位：{marker_name}",
        )

    def insert_marker_by_pose_action(self):
        """按输入坐标直接记录点位"""
        marker_name = self.marker_input.text.strip()
        if not marker_name:
            self.show_dialog("缺少点位名称", "请输入点位名称后再执行坐标录点。")
            return

        pose = self._parse_pose_inputs()
        if pose is None:
            return
        floor = self._parse_floor_input()
        if floor is None:
            return

        x, y, theta = pose
        self._send_robot_command(
            lambda: self.robot.insert_marker_by_pose(marker_name, x, y, theta, floor),
            pending_message=f"正在按坐标记录点位：{marker_name}",
        )

    def delete_marker_action(self):
        """删除指定点位"""
        marker_name = self.marker_input.text.strip()
        if not marker_name:
            self.show_dialog("缺少点位名称", "请输入要删除的点位名称。")
            return

        self._send_robot_command(
            lambda: self.robot.delete_marker(marker_name),
            pending_message=f"正在删除点位：{marker_name}",
        )

    def set_current_map_from_input(self):
        """根据输入切换地图"""
        map_name = self.map_input.text.strip()
        if not map_name:
            self.show_dialog("缺少地图名称", "请输入要切换的地图名称。")
            return

        floor = self._parse_floor_input()
        if floor is None:
            return

        self._send_robot_command(
            lambda: self.robot.set_current_map(map_name, floor=floor),
            pending_message=f"🔄 正在切换到地图：{map_name}（楼层 {floor}）",
        )

    def cancel_navigation_action(self):
        """取消当前导航"""
        self._send_robot_command(
            lambda: self.robot.cancel_navigation(),
            pending_message="正在取消导航...",
        )

    def get_map_list(self):
        """获取地图列表"""
        self._send_robot_command(
            lambda: self.robot.get_map_list(),
            pending_message="正在获取地图列表...",
        )

    def get_map_list_info_action(self):
        """获取地图详情列表"""
        self._send_robot_command(
            lambda: self.robot.get_map_list_info(),
            pending_message="正在获取地图详情...",
        )

    def adjust_position_by_marker_action(self):
        """按点位名称校准机器人位置"""
        marker_name = self.marker_input.text.strip()
        if not marker_name:
            self.show_dialog("缺少点位名称", "请输入要用于定位校准的点位名称。")
            return

        self._send_robot_command(
            lambda: self.robot.adjust_position_by_marker(marker_name),
            pending_message=f"正在按点位校准：{marker_name}",
        )

    def adjust_position_by_pose_action(self):
        """按输入坐标校准机器人位置"""
        pose = self._parse_pose_inputs()
        if pose is None:
            return

        x, y, theta = pose
        self._send_robot_command(
            lambda: self.robot.adjust_position_by_pose(x, y, theta),
            pending_message=f"正在按坐标校准：({x:.2f}, {y:.2f}, θ={theta:.2f})",
        )

    # ========== 系统信息与诊断动作方法 ==========

    def get_robot_info_action(self):
        """获取机器人基本信息"""
        self._send_robot_command(
            lambda: self.robot.get_robot_info(),
            pending_message="ℹ️ 正在获取机器人信息...",
        )

    def get_software_version_action(self):
        """获取软件版本"""
        self._send_robot_command(
            lambda: self.robot.get_software_version(),
            pending_message="🧾 正在获取软件版本...",
        )

    def check_for_update_action(self):
        """检查软件更新"""
        self._send_robot_command(
            lambda: self.robot.check_for_update(),
            pending_message="🔄 正在检查更新...",
        )

    def get_power_status_action(self):
        """获取电源详细状态"""
        self._send_robot_command(
            lambda: self.robot.get_power_status(),
            pending_message="🔋 正在获取电源状态...",
        )

    def get_diagnosis_result_action(self):
        """获取自诊断结果"""
        self._send_robot_command(
            lambda: self.robot.get_diagnosis_result(),
            pending_message="🩺 正在执行自诊断...",
        )

    def get_planned_path_action(self):
        """获取当前规划路径"""
        self._send_robot_command(
            lambda: self.robot.get_planned_path(),
            pending_message="🗺️ 正在获取当前规划路径...",
        )

    def get_lift_status_action(self):
        """获取电梯状态"""
        self._send_robot_command(
            lambda: self.robot.get_lift_status(),
            pending_message="🛗 正在获取电梯状态...",
        )

    def get_wifi_detail_list_action(self):
        """获取 WiFi 详细列表"""
        self._send_robot_command(
            lambda: self.robot.get_wifi_detail_list(),
            pending_message="📶 正在获取 WiFi 详情...",
        )

    # ========== 格式化辅助方法 ==========

    def _extract_robot_product_id(self, payload):
        """从机器人信息中提取产品 ID / 序列号"""
        if isinstance(payload, dict):
            for key in ("product_id", "serial", "serial_number", "robot_id", "id", "name"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
        return "--"

    def _format_robot_info(self, payload):
        """格式化机器人信息"""
        if isinstance(payload, dict):
            lines = []
            field_map = (
                ("产品 ID", "product_id"),
                ("序列号", "serial_number"),
                ("序列号", "serial"),
                ("机器人 ID", "robot_id"),
                ("型号", "model"),
                ("硬件版本", "hardware_version"),
                ("固件版本", "firmware_version"),
            )
            seen_keys = set()
            for label, key in field_map:
                if key in seen_keys:
                    continue
                value = payload.get(key)
                if value not in (None, ""):
                    lines.append(f"{label}: {value}")
                    seen_keys.add(key)
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到机器人信息")

    def _extract_version_text(self, payload):
        """从软件版本信息中提取版本号字符串"""
        if isinstance(payload, dict):
            for key in ("version", "app_version", "software_version", "ver"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(payload, str) and payload.strip():
            return payload.strip()
        return "--"

    def _format_version_results(self, payload):
        """格式化版本信息"""
        if isinstance(payload, dict):
            lines = []
            for label, key in (
                ("版本号", "version"),
                ("应用版本", "app_version"),
                ("软件版本", "software_version"),
                ("发布日期", "release_date"),
                ("构建号", "build"),
                ("更新说明", "description"),
            ):
                value = payload.get(key)
                if value not in (None, ""):
                    lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到版本信息")

    def _summarize_update_results(self, payload):
        """生成更新检查摘要"""
        if isinstance(payload, dict):
            has_update = payload.get("has_update") or payload.get("update_available")
            if has_update is not None:
                return "有新版本可用" if has_update else "已是最新版本"
            version = self._extract_version_text(payload)
            if version != "--":
                return f"版本 {version}"
        return "已收到更新检查结果"

    def _format_update_results(self, payload):
        """格式化更新检查结果"""
        if isinstance(payload, dict):
            lines = []
            has_update = payload.get("has_update") or payload.get("update_available")
            if has_update is not None:
                lines.append(f"是否有新版本: {'是' if has_update else '否'}")
            for label, key in (
                ("当前版本", "current_version"),
                ("最新版本", "latest_version"),
                ("新版本", "new_version"),
                ("更新说明", "description"),
                ("下载地址", "url"),
            ):
                value = payload.get(key)
                if value not in (None, ""):
                    lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到更新检查结果")

    def _summarize_power_status(self, payload):
        """生成电源状态摘要"""
        if isinstance(payload, dict):
            percent = payload.get("battery_percent") or payload.get("percent") or payload.get("soc")
            voltage = payload.get("voltage") or payload.get("battery_voltage")
            charging = payload.get("charging") or payload.get("is_charging")
            parts = []
            if percent is not None:
                parts.append(f"电量 {percent}%")
            if voltage is not None:
                try:
                    parts.append(f"电压 {float(voltage):.1f}V")
                except (TypeError, ValueError):
                    parts.append(f"电压 {voltage}")
            if charging is not None:
                parts.append("充电中" if charging else "放电中")
            if parts:
                return " | ".join(parts)
        return "已收到电源状态"

    def _format_power_status(self, payload):
        """格式化电源状态"""
        if isinstance(payload, dict):
            lines = []
            field_map = (
                ("电量百分比", "battery_percent"),
                ("电量", "percent"),
                ("SOC", "soc"),
                ("电压(V)", "voltage"),
                ("电池电压", "battery_voltage"),
                ("电流(A)", "current"),
                ("是否充电", "is_charging"),
                ("充电状态", "charging"),
                ("充电器连接", "charger_connected"),
                ("电池温度", "temperature"),
            )
            for label, key in field_map:
                value = payload.get(key)
                if value not in (None, ""):
                    if isinstance(value, bool):
                        value = "是" if value else "否"
                    lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到电源状态数据")

    def _summarize_diagnosis_results(self, payload):
        """生成自诊断摘要"""
        if isinstance(payload, list):
            ok_count = sum(
                1 for item in payload
                if isinstance(item, dict) and str(item.get("status", "")).lower() in ("ok", "normal", "pass", "true", "1", "success")
            )
            return f"共 {len(payload)} 项，{ok_count} 项正常"
        if isinstance(payload, dict):
            status = payload.get("status") or payload.get("result")
            if status is not None:
                return f"诊断结果: {status}"
        return "已收到自诊断结果"

    def _format_diagnosis_results(self, payload):
        """格式化自诊断结果"""
        items = self._extract_list(payload)
        if items:
            lines = []
            for index, item in enumerate(items, start=1):
                if isinstance(item, dict):
                    name = item.get("name") or item.get("module") or f"项目 {index}"
                    status = item.get("status") or item.get("result") or "未知"
                    description = item.get("description") or item.get("message") or ""
                    icon = "✅" if str(status).lower() in ("ok", "normal", "pass", "true", "1", "success") else "❌"
                    line = f"{icon} {name}: {status}"
                    if description:
                        line += f" — {description}"
                    lines.append(line)
                else:
                    lines.append(f"{index}. {item}")
            return "\n".join(lines)
        return self._pretty_text(payload, "未收到自诊断数据")

    def _summarize_current_path(self, payload):
        """生成当前路径摘要"""
        items = self._extract_list(payload)
        if items:
            return f"当前路径共 {len(items)} 个路径点"
        distance = self._extract_first_number(payload, ("distance", "length", "total_distance", "path_length"))
        if distance is not None:
            return f"当前路径长约 {distance:.2f} m"
        if payload not in (None, "", [], {}):
            return "已收到当前路径数据"
        return "当前无规划路径"

    def _format_current_path_results(self, payload):
        """格式化当前全局路径"""
        items = self._extract_list(payload)
        if items:
            lines = []
            for index, item in enumerate(items[:15], start=1):
                if isinstance(item, dict):
                    x = item.get("x")
                    y = item.get("y")
                    if x is not None and y is not None:
                        lines.append(f"{index}. ({self._safe_float(x):.2f}, {self._safe_float(y):.2f})")
                    else:
                        lines.append(f"{index}. {json.dumps(item, ensure_ascii=False)}")
                else:
                    lines.append(f"{index}. {item}")
            if len(items) > 15:
                lines.append(f"... 共 {len(items)} 个路径点")
            return "\n".join(lines)
        return self._pretty_text(payload, "当前无规划路径数据")

    def _format_lift_status(self, payload):
        """格式化电梯状态"""
        if isinstance(payload, dict):
            lines = []
            field_map = (
                ("电梯 ID", "lift_id"),
                ("楼层", "floor"),
                ("当前楼层", "current_floor"),
                ("状态", "status"),
                ("门状态", "door_status"),
                ("方向", "direction"),
                ("是否可用", "available"),
            )
            for label, key in field_map:
                value = payload.get(key)
                if value not in (None, ""):
                    if isinstance(value, bool):
                        value = "是" if value else "否"
                    lines.append(f"{label}: {value}")
            if lines:
                return "\n".join(lines)
        return self._pretty_text(payload, "未收到电梯状态数据")

    def _format_wifi_detail_results(self, payload):
        """格式化 WiFi 详细列表"""
        items = self._extract_list(payload)
        if not items:
            return self._pretty_text(payload, "未收到 WiFi 详细列表")

        lines = []
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                ssid = item.get("SSID") or item.get("ssid") or item.get("name") or f"WiFi {index}"
                signal = item.get("signal") or item.get("signal_level") or item.get("level")
                security = item.get("security") or item.get("encryption") or item.get("auth")
                frequency = item.get("frequency") or item.get("freq")
                bssid = item.get("BSSID") or item.get("bssid") or item.get("mac")
                extras = []
                if signal is not None:
                    extras.append(f"信号: {signal}")
                if security:
                    extras.append(f"加密: {security}")
                if frequency:
                    extras.append(f"频段: {frequency}")
                if bssid:
                    extras.append(f"BSSID: {bssid}")
                header = f"{index}. {ssid}"
                if extras:
                    lines.append(f"{header}\n   {'  '.join(extras)}")
                else:
                    lines.append(header)
            else:
                lines.append(f"{index}. {item}")
        return "\n".join(lines)

    # ========== 多目标巡游 ==========

    def start_cruise_action(self):
        """开始多目标巡游"""
        raw = self.cruise_markers_input.text.strip()
        if not raw:
            self.show_dialog("缺少点位", "请输入至少一个点位名称，多个点位用英文逗号分隔。")
            return

        markers = [m.strip() for m in raw.split(",") if m.strip()]
        if not markers:
            self.show_dialog("点位格式错误", "无法解析点位列表，请用英文逗号分隔各点位名称。")
            return

        try:
            tolerance = float(self.cruise_tolerance_input.text.strip() or "1.0")
        except ValueError:
            tolerance = 1.0

        try:
            count = int(self.cruise_count_input.text.strip() or "-1")
        except ValueError:
            count = -1

        self._send_robot_command(
            lambda: self.robot.move_to_multiple_markers(markers, distance_tolerance=tolerance, count=count),
            pending_message=f"🔁 开始巡游，共 {len(markers)} 个点位（循环 {'∞' if count == -1 else count} 次）",
            status_text=f"🔁 巡游中：{', '.join(markers[:3])}{'...' if len(markers) > 3 else ''}",
        )

    # ========== 高危操作（二次确认）==========

    def _show_confirm_dialog(self, title, text, on_confirm):
        """显示带确认/取消的对话框"""
        if self.dialog:
            self.dialog.dismiss()
        self.dialog = MDDialog(
            title=self._clean_ui_text(title),
            text=self._clean_ui_text(text),
            buttons=[
                MDRaisedButton(
                    text="取消",
                    md_bg_color=(0.5, 0.5, 0.5, 1),
                    on_release=lambda x: self.dialog.dismiss()
                ),
                MDRaisedButton(
                    text="确认执行",
                    md_bg_color=(0.85, 0.2, 0.2, 1),
                    on_release=lambda x: self._execute_confirmed(on_confirm)
                ),
            ]
        )
        self.dialog.open()

    def _execute_confirmed(self, on_confirm):
        """关闭确认对话框并执行操作"""
        if self.dialog:
            self.dialog.dismiss()
        on_confirm()

    def confirm_restart_service(self):
        """二次确认后重启软件服务"""
        self._show_confirm_dialog(
            "⚠️ 重启软件服务",
            "此操作将重启底盘软件服务，机器人会短暂停止响应，是否继续？",
            on_confirm=self._do_restart_service
        )

    def _do_restart_service(self):
        self._send_robot_command(
            lambda: self.robot.restart_software_service(),
            pending_message="🔄 已发送重启软件服务指令",
        )

    def confirm_update_software(self):
        """二次确认后立即执行软件更新"""
        self._show_confirm_dialog(
            "⚠️ 立即更新软件",
            "此操作将开始更新底盘软件，更新期间机器人将不可用，完成后可能自动重启，是否继续？",
            on_confirm=self._do_update_software
        )

    def _do_update_software(self):
        self._send_robot_command(
            lambda: self.robot.update_software(),
            pending_message="⬆️ 已发送软件更新指令，请耐心等待...",
        )

    def confirm_reboot(self):
        """二次确认后重启机器人"""
        self._show_confirm_dialog(
            "⚠️ 重启机器人",
            "此操作将重启整个机器人系统，是否继续？",
            on_confirm=self._do_reboot
        )

    def _do_reboot(self):
        self._send_robot_command(
            lambda: self.robot.shutdown_or_reboot(reboot=True),
            pending_message="🔃 已发送重启指令，机器人将重启...",
        )

    def confirm_shutdown(self):
        """二次确认后关机"""
        self._show_confirm_dialog(
            "⚠️ 关机",
            "此操作将关闭机器人电源，关机后需要手动开机，是否继续？",
            on_confirm=self._do_shutdown
        )

    def _do_shutdown(self):
        self._send_robot_command(
            lambda: self.robot.shutdown_or_reboot(reboot=False),
            pending_message="⏻ 已发送关机指令，机器人即将关机...",
        )

    def show_dialog(self, title, text):
        """显示对话框"""
        if self.dialog:
            self.dialog.dismiss()
        self.dialog = MDDialog(
            title=self._clean_ui_text(title),
            text=text,
            buttons=[
                MDRaisedButton(
                    text="确定",
                    on_release=lambda x: self.dialog.dismiss()
                )
            ]
        )
        self.dialog.open()


if __name__ == '__main__':
    try:
        if platform not in ("android", "ios"):
            Window.size = (360, 640)
        RobotControllerApp().run()
    except Exception as e:
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(f"应用崩溃:\n{traceback.format_exc()}")
        print(f"应用崩溃: {e}")
        traceback.print_exc()
