"""Plain Python functions for roshanavi's function nodes (関数ノード) - no ROS inside.

A function node calls one of these with the value of each received message and
sends back what it returns. Nothing here imports rclpy: the functions are normal
Python, easy to test with pytest, and roshanavi does the ROS part.

    shout(text)          文字列 -> 文字列     "hello" -> "HELLO!"
    only_long(text)      文字列 -> 文字列     returns None for short texts (nothing is sent)
    invert(image)        画像 -> 画像         numpy H x W x 3 (RGB) -> the negative image
    add(a, b)            数値 x 2 -> 数値     several inputs: the latest value of each
    wave(t)              (周期) -> 数値       called on a timer with the elapsed seconds

Try it: roshanavi -> 「＋ 関数ノードを作る」 -> module roshanavi_examples.logic,
function shout, input /chatter, output /shouted. Edit this file and save: the node
reloads the function by itself.
"""

import math

import numpy as np


def shout(text: str) -> str:
    """Upper-case the text and add "!"."""
    return text.upper() + '!'


def only_long(text: str) -> str:
    """Pass texts of 10 characters or more; return None (= send nothing) otherwise."""
    if len(text) < 10:
        return None
    return text


def invert(image: np.ndarray) -> np.ndarray:
    """The negative of an RGB (or gray) image: 255 - every pixel value."""
    return 255 - image


def add(a: float, b: float) -> float:
    """Sum of the latest values of two topics."""
    return a + b


def wave(t: float) -> float:
    """A sine wave of 0.5 Hz: a stand-in for a sensor that is not there yet."""
    return math.sin(2 * math.pi * 0.5 * t)
