from . import grain
from . import grainTypes
from . import nozzle
from . import propellant
from . import geometry
from . import units
from . import simulationResult, simAlert, simAlertLevel, simAlertType
from . import endBurningGrain
from . import propertyCollection, floatProperty, intProperty

import math
import numpy as np

class MotorConfig(propertyCollection):
    def __init__(self):
        super().__init__()
        # Limits
        self.props['maxPressure'] = floatProperty('Maximum Allowed Pressure', 'Pa', 0, 7e7)
        self.props['maxMassFlux'] = floatProperty('Maximum Allowed Mass Flux', 'kg/(m^2*s)', 0, 1e4)
        self.props['minPortThroat'] = floatProperty('Minimum Allowed Port/Throat Ratio', '', 1, 4)
        # Simulation
        self.props['burnoutWebThres'] = floatProperty('Web Burnout Threshold', 'm', 2.54e-5, 3.175e-3)
        self.props['burnoutThrustThres'] = floatProperty('Thrust Burnout Threshold', '%', 0.01, 10)
        self.props['timestep'] = floatProperty('Simulation Timestep', 's', 0.0001, 0.1)
        self.props['ambPressure'] = floatProperty('Ambient Pressure', 'Pa', 0.0001, 102000)
        self.props['mapDim'] = intProperty('Grain Map Dimension', '', 250, 2000)

class motor():
    def __init__(self, propDict = None):
        self.grains = []
        self.propellant = None
        self.nozzle = nozzle.nozzle()
        self.config = MotorConfig()

        if propDict is not None:
            self.applyDict(propDict)

    def getDict(self):
        motorData = {}
        motorData['nozzle'] = self.nozzle.getProperties()
        if self.propellant is not None:
            motorData['propellant'] = self.propellant.getProperties()
        else:
            motorData['propellant'] = None
        motorData['grains'] = [{'type': grain.geomName, 'properties': grain.getProperties()} for grain in self.grains]
        motorData['config'] = self.config.getProperties()
        return motorData

    def applyDict(self, dictionary):
        self.nozzle.setProperties(dictionary['nozzle'])
        if dictionary['propellant'] is not None:
            self.propellant = propellant(dictionary['propellant'])
        else:
            self.propellant = None
        self.grains = []
        for entry in dictionary['grains']:
            self.grains.append(grainTypes[entry['type']]())
            self.grains[-1].setProperties(entry['properties'])
        self.config.setProperties(dictionary['config'])

    def calcKN(self, r, burnoutWebThres = 0.00001):
        surfArea = sum([gr.getSurfaceAreaAtRegression(reg) * int(gr.isWebLeft(reg, burnoutWebThres)) for gr, reg in zip(self.grains, r)])
        nozz = self.nozzle.getThroatArea()
        return surfArea / nozz

    def calcIdealPressure(self, r, kn = None, burnoutWebThres = 0.00001):
        k = self.propellant.getProperty('k')
        t = self.propellant.getProperty('t')
        m = self.propellant.getProperty('m')
        p = self.propellant.getProperty('density')
        a = self.propellant.getProperty('a')
        n = self.propellant.getProperty('n')
        if kn is None:
            kn = self.calcKN(r, burnoutWebThres)
        num = kn * p * a
        exponent = 1/(1 - n)
        denom = ((k/((8314/m)*t))*((2/(k+1))**((k+1)/(k-1))))**0.5
        return (num/denom) ** exponent

    def calcForce(self, r, casePressure = None, ambientPressure = 101325, burnoutWebThres = 0.00001):
        k = self.propellant.getProperty('k')
        t_a = self.nozzle.getThroatArea()
        e_a = self.nozzle.getExitArea()

        p_a = ambientPressure
        if casePressure is None:
            p_c = self.calcIdealPressure(r, None, burnoutWebThres)
        else:
            p_c = casePressure

        if p_c == 0:
            return 0
 
        p_e = self.nozzle.getExitPressure(k, p_c)

        t1 = (2*(k**2))/(k-1)
        t2 = (2/(k+1))**((k+1)/(k-1))
        t3 = 1 - ((p_e/p_c) ** ((k-1)/k))

        sr = (t1 * t2 * t3) ** 0.5

        f = self.nozzle.props['efficiency'].getValue() * t_a * p_c * sr + (p_e - p_a) * e_a
        if np.isnan(f) or f < 0:
            f = 0

        return f

    def runSimulation(self, callback = None):
        ambientPressure = self.config.getProperty('ambPressure')
        burnoutWebThres = self.config.getProperty('burnoutWebThres')
        burnoutThrustThres = self.config.getProperty('burnoutThrustThres')
        ts = self.config.getProperty('timestep')

        simRes = simulationResult(self)

        # Check for geometry errors
        if len(self.grains) == 0:
            simRes.addAlert(simAlert(simAlertLevel.ERROR, simAlertType.CONSTRAINT, 'Motor must have at least one propellant grain', 'Motor'))
        for gid, grain in enumerate(self.grains):
            if type(grain) is endBurningGrain and gid != 0: # Endburners have to be at the foward end
                simRes.addAlert(simAlert(simAlertLevel.ERROR, simAlertType.CONSTRAINT, 'End burning grains must be the forward-most grain in the motor', 'Grain ' + str(gid + 1)))
            for alert in grain.getGeometryErrors():
                alert.location = 'Grain ' + str(gid + 1)
                simRes.addAlert(alert)
        for alert in self.nozzle.getGeometryErrors():
            simRes.addAlert(alert)

        # Make sure the motor has a propellant set
        if self.propellant is None:
            alert = simAlert(simAlertLevel.ERROR, simAlertType.CONSTRAINT, 'Motor must have a propellant set', 'Motor')
            simRes.addAlert(alert)

        # If any errors occurred, stop simulation and return an empty sim with errors
        if len(simRes.getAlertsByLevel(simAlertLevel.ERROR)) > 0:
            return simRes

        # Pull the required numbers from the propellant
        density = self.propellant.getProperty('density')
        ballA = self.propellant.getProperty('a')
        ballN = self.propellant.getProperty('n')

        # Generate coremaps for perforated grains
        for grain in self.grains:
            grain.simulationSetup(self.config)

        # Setup initial values
        perGrainReg = [0 for grain in self.grains]

        # At t=0, the motor hasn't yet ignited
        simRes.channels['time'].addData(0)
        simRes.channels['kn'].addData(0)
        simRes.channels['pressure'].addData(0)
        simRes.channels['force'].addData(0)
        simRes.channels['mass'].addData([grain.getVolumeAtRegression(0) * density for grain in self.grains])
        simRes.channels['massFlow'].addData([0 for grain in self.grains])
        simRes.channels['massFlux'].addData([0 for grain in self.grains])

        # At t = ts, the motor has ignited
        simRes.channels['time'].addData(ts)
        simRes.channels['kn'].addData(self.calcKN(perGrainReg, burnoutWebThres))
        simRes.channels['pressure'].addData(self.calcIdealPressure(perGrainReg, None, burnoutWebThres))
        simRes.channels['force'].addData(self.calcForce(perGrainReg, None, ambientPressure, burnoutWebThres))
        simRes.channels['mass'].addData([grain.getVolumeAtRegression(0) * density for grain in self.grains])
        simRes.channels['massFlow'].addData([0 for grain in self.grains])
        simRes.channels['massFlux'].addData([0 for grain in self.grains])

        # Check port/throat ratio and add a warning if it is large enough
        aftPort = self.grains[-1].getPortArea(0)
        if aftPort is not None:
            minAllowed = self.config.getProperty('minPortThroat')
            ratio = aftPort / geometry.circleArea(self.nozzle.props['throat'].getValue())
            if ratio < minAllowed:
                desc = 'Initial port/throat ratio of ' + str(round(ratio, 3)) + ' was less than ' + str(minAllowed)
                simRes.addAlert(simAlert(simAlertLevel.WARNING, simAlertType.CONSTRAINT, desc, 'N/A'))

        # Perform timesteps
        while simRes.channels['force'].getLast() > burnoutThrustThres * 0.01 * simRes.channels['force'].getMax(): # 0.01 to convert to a percentage
            # Calculate regression
            mf = 0
            perGrainMass = [0 for grain in self.grains]
            perGrainMassFlow = [0 for grain in self.grains]
            perGrainMassFlux = [0 for grain in self.grains]
            for gid, grain in enumerate(self.grains):
                if grain.getWebLeft(perGrainReg[gid]) > burnoutWebThres:
                    reg = ts * ballA * (simRes.channels['pressure'].getLast()**ballN) # Calculate regression at the current pressure
                    perGrainMassFlux[gid] = grain.getPeakMassFlux(mf, ts, perGrainReg[gid], reg, density) # Find the mass flux through the grain based on the mass flow fed into from grains above it
                    perGrainMass[gid] = grain.getVolumeAtRegression(perGrainReg[gid]) * density # Find the mass of the grain after regression
                    mf += (simRes.channels['mass'].getLast()[gid] - perGrainMass[gid]) / ts # Add the change in grain mass to the mass flow
                    perGrainReg[gid] += reg # Apply the regression
                perGrainMassFlow[gid] = mf

            simRes.channels['mass'].addData(perGrainMass)
            simRes.channels['massFlow'].addData(perGrainMassFlow)
            simRes.channels['massFlux'].addData(perGrainMassFlux)

            # Calculate KN
            simRes.channels['kn'].addData(self.calcKN(perGrainReg, burnoutWebThres))

            # Calculate Pressure
            simRes.channels['pressure'].addData(self.calcIdealPressure(perGrainReg, simRes.channels['kn'].getLast(), burnoutWebThres))

            # Calculate force
            simRes.channels['force'].addData(self.calcForce(perGrainReg, simRes.channels['pressure'].getLast(), ambientPressure, burnoutWebThres))

            simRes.channels['time'].addData(simRes.channels['time'].getLast() + ts)

            if callback is not None:
                progress = max([g.getWebLeft(r) / g.getWebLeft(0) for g,r in zip(self.grains, perGrainReg)]) # Grain with the largest percentage of its web left
                if callback(1 - progress): # If the callback returns true, it is time to cancel
                    return simRes

        simRes.success = True

        if simRes.getPeakMassFlux() > self.config.getProperty('maxMassFlux'):
            desc = 'Peak mass flux exceeded configured limit'
            alert = simAlert(simAlertLevel.WARNING, simAlertType.CONSTRAINT, desc, 'Motor')
            simRes.addAlert(alert)

        if simRes.getMaxPressure() > self.config.getProperty('maxPressure'):
            desc = 'Max pressure exceeded configured limit'
            alert = simAlert(simAlertLevel.WARNING, simAlertType.CONSTRAINT, desc, 'Motor')
            simRes.addAlert(alert)

        return simRes
