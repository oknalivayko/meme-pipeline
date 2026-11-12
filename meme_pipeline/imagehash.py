"""Perceptual difference hash for catching reposted images.

The same meme is reposted by many channels as a different file: re-encoded,
resized, slightly cropped, with another watermark. Byte hashes miss that.
dHash shrinks the image to (n+1) x n grayscale pixels and stores one bit per
pixel: is it brighter than its right neighbour. Small edits flip only a few of
the n*n bits, so the Hamming distance between two hashes measures visual
similarity.
"""
from pathlib import Path

from PIL import Image


def dhash(image: Image.Image | str | Path, size: int = 16) -> int:
    if not isinstance(image, Image.Image):
        with Image.open(image) as im:
            return dhash(im.copy(), size)
    pixels = image.convert("L").resize((size + 1, size), Image.LANCZOS).tobytes()
    value = 0
    for row in range(size):
        offset = row * (size + 1)
        for col in range(size):
            value = (value << 1) | (pixels[offset + col] > pixels[offset + col + 1])
    return value


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class HashIndex:
    def __init__(self, threshold: int):
        self.threshold = threshold
        self.items: dict[int, int] = {}

    def add(self, key: int, value: int) -> None:
        self.items[key] = value

    def find(self, value: int) -> int | None:
        """Key of the closest stored hash within the threshold, if any."""
        best_key, best_distance = None, self.threshold + 1
        for key, stored in self.items.items():
            distance = hamming(value, stored)
            if distance < best_distance:
                best_key, best_distance = key, distance
        return best_key
