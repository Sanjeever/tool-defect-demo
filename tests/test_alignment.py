import unittest

import numpy as np
from PIL import Image, ImageDraw

from workbench.alignment import align, locate, source_boxes, transform_boxes


class AlignmentTests(unittest.TestCase):
    def tool(self):
        image = Image.new("L", (600, 500), 230)
        draw = ImageDraw.Draw(image)
        draw.polygon([(200, 170), (370, 170), (330, 330), (200, 330)], fill=45)
        draw.ellipse((260, 220, 300, 260), fill=180)
        return image

    def test_rotation_matching_keeps_actual_model_input_orientation(self):
        reference, _ = align(self.tool())
        changed = self.tool().rotate(65, fillcolor=230).transform((600, 500), Image.Transform.AFFINE, (1, 0, -30, 0, 1, 15), fillcolor=230)
        result, metadata = align(changed, reference)
        self.assertGreater(metadata["similarity"], 0.97)
        self.assertLess(abs((metadata["recognition_angle"] + 65 + 180) % 360 - 180), 3)
        self.assertEqual(metadata["angle"], 0)
        np.testing.assert_array_equal(np.asarray(result), np.asarray(locate(changed)[0]))

    def test_symmetric_damaged_tool_does_not_follow_reference_rotation(self):
        image = Image.new("L", (600, 500), 230)
        draw = ImageDraw.Draw(image)
        draw.polygon([(150, 120), (450, 120), (300, 380)], fill=45)
        draw.ellipse((260, 185, 340, 265), fill=180)
        reference, _ = align(image)
        draw.polygon([(140, 110), (220, 110), (140, 230)], fill=230)
        box = {"x": 150, "y": 120, "width": 70, "height": 100, "label": "缺角"}
        first, first_metadata = align(image, reference)
        second, second_metadata = align(image, reference.rotate(120, fillcolor=230))
        np.testing.assert_array_equal(np.asarray(first), np.asarray(second))
        self.assertEqual(first_metadata["matrix"], second_metadata["matrix"])
        transformed = transform_boxes([box], first_metadata["matrix"], 512)
        returned = source_boxes(transformed, first_metadata)[0]
        for key in ("x", "y", "width", "height"):
            self.assertAlmostEqual(returned[key], box[key], places=5)

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

    def test_padding_predictions_are_removed_but_invalid_annotations_fail(self):
        box = {"x": 0, "y": 0, "width": 10, "height": 10, "label": "划痕", "confidence": 0.8}
        metadata = {"matrix": [[1, 0, 100], [0, 1, 100]], "source_size": [200, 200]}
        self.assertEqual(source_boxes([box], metadata), [])
        with self.assertRaises(ValueError):
            transform_boxes([box], [[1, 0, -100], [0, 1, -100]], 512)
