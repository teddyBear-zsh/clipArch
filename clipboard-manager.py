"""
Clipbosrd Manager Module
author: teddyBear
license: MIT
"""
import os
import sys
import time
import json
import hashlib
import signal
import subprocess
import argparse
import base64
from pathlib import Path
from collections import deque
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from io import BytesIO

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("Pillow library not found. Image clipboard functionality will be disabled.", file=sys.stderr)

class ClipboardType:
    #Types of clipboard content
    TEXT = "text"
    IMAGE = "image"
    UNKNOWN =  "unkown"

class ClipboardManager:
    def __init__(self):
        self.is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
        self.is_endpoint_available = self._check_endpoint()
    
    def _check_endpoint(self) -> bool:
        # check if clipboard command line tools are available
        if self.is_wayland:
            return self._command_exists("wl-paste") and self._command_exists("wl-copy")
        else:
            return self._command_exists("xclip") or self._command_exists("xsel") 

    @staticmethod
    def _command_exists(command: str) -> bool:
        return subprocess.run(
            ["which", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        ).returncode == 0
    
    def get_clipboard_type(self)->List[str]:
        try:
            
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-past", "--list-types"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
            if result.returncode != 0:
                return result.stdout.strip().split('\n')
            
        except Exception as e:
            pass
        return []
    
    def detect_content_type(self)->str:
        types = self.get_clipboard_type()
        if not types:
            return ClipboardType.UNKNOWN
        
        images_types = ['image/png', 'image/jpeg', 'image/bmp', 'image/gif','image/webp']
        for img_type in images_types:
            if img_type in types:
                return ClipboardType.IMAGE
    
        text_types = ['text/plain', 'UTF8_STRING', 'STRING', 'TEXT']
        for text_type in text_types:
            if text_type in types:
                return ClipboardType.TEXT
    
    def get_text_content(self) -> Optional[str]:
        try:
            if self.is_wayland:
                result = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
            if result.returncode == 0:
                return result.stdout
        except Exception as e:
            print(f"Error getting text content: {e}", file=sys.stderr)
        return None
    
    def get_image_content(self) -> Optional[bytes]:
        try:
            if self.is_wayland:
                for img_format in ['image/png', 'image/jpeg', 'image/bmp', 'image/gif','image/webp']:
                    result = subprocess.run(
                        ["wl-paste", "--type", img_format],
                        capture_output= True,
                        timeout=3
                    )
                    if result.returncode == 0 and result.stdout:
                        return result.stdout
            else:
                result = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                    capture_output=True,
                    timeout=3
                )
                if result.returncode == 0:
                    return result.stdout
            return None
        except Exception as e:
            print(f"Error leyendo imagen: {e}", file=sys.stderr)
            return None