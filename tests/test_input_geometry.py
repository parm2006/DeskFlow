import unittest

from app.input_geometry import (
    client_entry_position,
    work_area_geometry,
    toast_rect_in_work_area,
    windows_toplevel_handle,
    configure_windows_window_api,
)


class InputGeometryTests(unittest.TestCase):
    def test_client_entry_is_visually_at_edge_without_triggering_return(self):
        positions = {
            "right": client_entry_position("right", 1920, 1080, 0.5),
            "left": client_entry_position("left", 1920, 1080, 0.5),
            "top": client_entry_position("top", 1920, 1080, 0.5),
            "bottom": client_entry_position("bottom", 1920, 1080, 0.5),
        }

        self.assertEqual(positions["right"], (1, 540))
        self.assertEqual(positions["left"], (1917, 540))
        self.assertEqual(positions["top"], (960, 1077))
        self.assertEqual(positions["bottom"], (960, 1))
        self.assertGreater(positions["right"][0], 0)
        self.assertLess(positions["left"][0], 1920 - 2)
        self.assertLess(positions["top"][1], 1080 - 2)
        self.assertGreater(positions["bottom"][1], 0)

    def test_overlay_geometry_uses_work_area_instead_of_fullscreen(self):
        self.assertEqual(work_area_geometry((0, 0, 1920, 1040)), "1920x1040+0+0")
        self.assertEqual(work_area_geometry((-1920, 20, 0, 1080)), "1920x1060-1920+20")

    def test_toast_rectangle_stays_inside_monitor_work_area_at_common_dpi(self):
        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi):
                scale = dpi / 96
                width = round(360 * scale)
                height = round(104 * scale)
                rect = toast_rect_in_work_area((0, 0, 1920, 1040), (width, height), dpi)
                left, top, right, bottom = rect
                self.assertGreaterEqual(left, 0)
                self.assertGreaterEqual(top, 0)
                self.assertLessEqual(right, 1920)
                self.assertLessEqual(bottom, 1040)
                self.assertEqual(right - left, width)
                self.assertEqual(bottom - top, height)

    def test_toast_rectangle_supports_negative_monitor_coordinates(self):
        self.assertEqual(
            toast_rect_in_work_area((-1920, 20, 0, 1080), (360, 104), 96),
            (-376, 960, -16, 1064),
        )

    def test_oversized_toast_is_clamped_to_the_available_work_area(self):
        self.assertEqual(
            toast_rect_in_work_area((100, 50, 500, 250), (600, 300), 96),
            (100, 50, 500, 250),
        )

    def test_native_positioning_resolves_the_toast_toplevel_not_the_root_window(self):
        calls = []

        def get_ancestor(hwnd, flag):
            calls.append((hwnd, flag))
            return 222

        self.assertEqual(windows_toplevel_handle(111, get_ancestor), 222)
        self.assertEqual(calls, [(111, 2)])

    def test_native_window_api_uses_pointer_sized_handle_signatures(self):
        class Function:
            argtypes = None
            restype = None

        class Api:
            GetAncestor = Function()
            MonitorFromWindow = Function()
            GetMonitorInfoW = Function()
            GetWindowRect = Function()
            GetDpiForWindow = Function()
            SetWindowPos = Function()

        configure_windows_window_api(Api)

        self.assertIsNotNone(Api.GetAncestor.argtypes)
        self.assertIsNotNone(Api.GetAncestor.restype)
        self.assertIsNotNone(Api.SetWindowPos.argtypes)
        self.assertIsNotNone(Api.SetWindowPos.restype)


if __name__ == "__main__":
    unittest.main()
