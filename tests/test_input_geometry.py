import unittest

from app.input_geometry import client_entry_position, work_area_geometry, scaled_toast_geometry


class InputGeometryTests(unittest.TestCase):
    def test_client_entry_is_inset_from_its_return_edge(self):
        self.assertEqual(client_entry_position("right", 1920, 1080, 0.5), (96, 540))
        self.assertEqual(client_entry_position("left", 1920, 1080, 0.5), (1823, 540))
        self.assertEqual(client_entry_position("top", 1920, 1080, 0.5), (960, 983))
        self.assertEqual(client_entry_position("bottom", 1920, 1080, 0.5), (960, 96))

    def test_overlay_geometry_uses_work_area_instead_of_fullscreen(self):
        self.assertEqual(work_area_geometry((0, 0, 1920, 1040)), "1920x1040+0+0")
        self.assertEqual(work_area_geometry((-1920, 20, 0, 1080)), "1920x1060-1920+20")

    def test_toast_geometry_scales_physical_work_area_to_tk_coordinates(self):
        self.assertEqual(
            scaled_toast_geometry((0, 0, 1920, 1040), (1920, 1080), (1536, 864), 360, 104),
            "360x104+1160+712",
        )


if __name__ == "__main__":
    unittest.main()
