def client_entry_position(direction, width, height, ratio, margin=96):
    horizontal = max(margin, min(width - margin - 1, int(width * ratio)))
    vertical = max(margin, min(height - margin - 1, int(height * ratio)))
    if direction == "right":
        return margin, vertical
    if direction == "left":
        return width - margin - 1, vertical
    if direction == "top":
        return horizontal, height - margin - 1
    if direction == "bottom":
        return horizontal, margin
    raise ValueError(f"unsupported direction: {direction}")


def work_area_geometry(rect):
    left, top, right, bottom = rect
    return f"{right - left}x{bottom - top}{left:+d}{top:+d}"


def scaled_toast_geometry(work_area, physical_screen, tk_screen, width, height, margin=16):
    left, top, right, bottom = work_area
    physical_width, physical_height = physical_screen
    tk_width, tk_height = tk_screen
    scale_x = tk_width / physical_width
    scale_y = tk_height / physical_height
    scaled_right = round(right * scale_x)
    scaled_bottom = round(bottom * scale_y)
    x = scaled_right - width - margin
    y = scaled_bottom - height - margin
    return f"{width}x{height}{x:+d}{y:+d}"


def windows_work_area():
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
        raise ctypes.WinError()
    return rect.left, rect.top, rect.right, rect.bottom
