import unittest

import numpy as np
from PIL import Image, ImageDraw

from workbench.alignment import align, source_boxes, transform_boxes


class AlignmentTests(unittest.TestCase):
    def tool(self):
        image = Image.new("L", (600, 500), 230)
        draw = ImageDraw.Draw(image)
        draw.polygon([(200, 170), (370, 170), (330, 330), (200, 330)], fill=45)
        draw.ellipse((260, 220, 300, 260), fill=180)
        return image

    def test_rotated_translated_tool_aligns_to_reference(self):
        reference, _ = align(self.tool())
        changed = self.tool().rotate(65, fillcolor=230).transform((600, 500), Image.Transform.AFFINE, (1, 0, -30, 0, 1, 15), fillcolor=230)
        result, metadata = align(changed, reference)
        self.assertGreater(metadata["similarity"], 0.97)
        self.assertLess(np.abs(np.asarray(result, dtype=float) - np.asarray(reference, dtype=float)).mean(), 8)

    def test_original_coordinates_round_trip_without_rotation(self):
        _, metadata = align(self.tool())
        boxes = [{"x": 220, "y": 180, "width": 30, "height": 20, "label": "划痕"}]
        returned = source_boxes(transform_boxes(boxes, metadata["matrix"], 512), metadata)
        for key in ("x", "y", "width", "height"):
            self.assertAlmostEqual(boxes[0][key], returned[0][key], places=5)

    def test_empty_multiple_and_clipped_images_are_rejected(self):
        with self.assertRaises(ValueError):
            align(Image.new("L", (600, 500), 230))
        image = self.tool()
        ImageDraw.Draw(image).rectangle((430, 180, 570, 320), fill=45)
        with self.assertRaisesRegex(ValueError, "多个"):
            align(image)
        with self.assertRaisesRegex(ValueError, "边界"):
            align(self.tool().crop((240, 0, 600, 500)))
