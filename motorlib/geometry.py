import math

def circleArea(d):
    return ((d / 2) ** 2) * math.pi

def circleDiameterFromArea(a):
    return 2*((a / math.pi) ** 0.5)

def tubeArea(d, h):
    return d * math.pi * h

def cylinderArea(d, h):
    return (2 * circleArea(d)) + (tubeArea(d, h))

def cylinderVolume(d, h):
    return h * circleArea(d)
