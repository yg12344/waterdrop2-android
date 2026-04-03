# -*- coding: utf-8 -*-
"""
Android特定配置
用于处理Android平台的特殊需求
"""

def init_android():
    """Android平台初始化"""
    try:
        from android import AndroidConfig
        # Android特定配置
        pass
    except ImportError:
        pass

def request_permissions():
    """请求Android权限"""
    try:
        from android.permissions import request_permissions, PERMISSION_INTERNET
        request_permissions([PERMISSION_INTERNET])
    except ImportError:
        pass
