import sys
import os
import matplotlib
import yaml
import warnings

import motorlib.motor
from uilib.fileIO import loadFile, fileTypes

class colors:
    OK = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def color(string, name):
    return str(name) + string + str(colors.ENDC)

def formatPercent(percent):
    if percent < 1 / 100:
        c = colors.OK
    elif percent < 5 / 100:
        c = colors.WARNING
    else:
        c = colors.FAIL
    return color(str(round(percent * 100, 3)) + '%', c)

def runSim(path):
    print('Loading motor from ' + path)
    res = loadFile(path, fileTypes.MOTOR)
    if res is not None:
        motor = motorlib.motor.Motor(res)
        print('Simulating burn...')
        return motor.runSimulation()
    else:
        print('Error loading motor for test!')

def compareStat(title, a, b):
    error = abs(a - b) / b
    dispError = formatPercent(error)
    print('\t\t' + title + ': ' + str(round(a, 3)) + ' vs ' + str(round(b, 3)) + ' (' + dispError + ')')
    return error

def compareStats(simRes, stats):
    print('\tBasic stats:')
    btError = compareStat('Burn Time', simRes.getBurnTime(), stats['burnTime'])
    ispError = compareStat('ISP', simRes.getISP(), stats['isp'])
    propmassError = compareStat('Propellant Mass', simRes.getPropellantMass(), stats['propMass'])
    score = 1 - ((1 - btError) * (1 - ispError) * (1 - propmassError))
    dispScore = formatPercent(score)
    print('\tOverall error: ' + dispScore)
    return score

def compareAlerts(simRes, pastAlerts):
    allMatched = True
    for alert in simRes.alerts:
        if alert.description not in pastAlerts:
            print('\tSimulation produced unexpected alert: ' + color(alert.description, colors.WARNING))
            allMatched = False
    for alert in pastAlerts:
        if alert not in [a.description for a in simRes.alerts]:
            print('\tSimulation was missing expected alert: ' + color(alert, colors.WARNING))

    if allMatched:
        print('\tSimulation alerts matched.')

def runTests(path):
    print('-' * 50)
    with open(path, 'r') as readLocation:
        fileData = yaml.load(readLocation)
        print("Running tests for '" + fileData['name'] + "'")
        simRes = runSim(fileData['motor'])
        if 'real' in fileData['data'].keys():
            print('Compared to real data:')
            compareStats(simRes, fileData['data']['real']['stats'])
        if 'regression' in fileData['data'].keys():
            for version in fileData['data']['regression']:
                print('Compared to results from ' + str(version['version']) + ':')
                compareStats(simRes, version['stats'])
                compareAlerts(simRes, version['alerts'])
    print('-' * 50)

warnings.filterwarnings('ignore') # Todo: get rid of this
os.system('color')
if len(sys.argv) > 1:
    runTests(sys.argv[1])
else:
    with open('data/tests.yaml', 'r') as readLocation:
        fileData = yaml.load(readLocation)
        for category in fileData.keys():
            print("Running tests from category '" + category + "'")
            for test in fileData[category]:
                runTests(test)
