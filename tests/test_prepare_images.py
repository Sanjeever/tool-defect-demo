from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from prepare_images import prepare_directory, prepare_image


class PrepareImagesTests(unittest.TestCase):
    def test_long_tool_keeps_both_ends(self):
        image = Image.new("RGB", (100, 20), "white")
        image.paste("red", (0, 0, 10, 20))
        image.paste("blue", (90, 0, 100, 20))
        result = prepare_image(image, None, 100)
        self.assertEqual(result.size, (100, 100))
        self.assertEqual(result.getpixel((0, 50)), (255, 0, 0))
        self.assertEqual(result.getpixel((99, 50)), (0, 0, 255))
        self.assertEqual(result.getpixel((50, 0)), (0, 0, 0))

    def test_roi_uses_exclusive_right_and_bottom(self):
        image = Image.new("RGB", (20, 20), "white")
        image.paste("red", (5, 5, 15, 15))
        result = prepare_image(image, (5, 5, 15, 15), 10)
        self.assertEqual(result.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(result.getpixel((9, 9)), (255, 0, 0))

    def test_invalid_roi_is_rejected_instead_of_padding(self):
        image = Image.new("L", (20, 20))
        for roi in ((-1, 0, 20, 20), (0, 0, 21, 20), (10, 0, 5, 20)):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                prepare_image(image, roi, 20)

    def test_grayscale_becomes_three_identical_channels(self):
        result = prepare_image(Image.new("L", (10, 10), 128), None, 10)
        self.assertEqual(result.mode, "RGB")
        self.assertEqual(result.getpixel((5, 5)), (128, 128, 128))

    def test_directory_preserves_splits_and_does_not_overwrite(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "raw/train/good"
            source.mkdir(parents=True)
            Image.new("L", (80, 20)).save(source / "刀具.png")
            output = root / "prepared"
            count = prepare_directory(root / "raw", output, None, 256)
            self.assertEqual(count, 1)
            with Image.open(output / "train/good/刀具.png") as image:
                self.assertEqual(image.size, (256, 256))
            with self.assertRaises(FileExistsError):
                prepare_directory(root / "raw", output, None, 256)

    def test_nested_output_and_name_collisions_are_rejected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "raw"
            source.mkdir()
            Image.new("RGB", (10, 10)).save(source / "tool.jpg")
            Image.new("RGB", (10, 10)).save(source / "tool.png")
            with self.assertRaises(ValueError):
                prepare_directory(source, source / "prepared", None, 256)
            with self.assertRaises(ValueError):
                prepare_directory(source, root / "prepared", None, 256)
            self.assertFalse((root / "prepared").exists())


if __name__ == "__main__":
    unittest.main()
