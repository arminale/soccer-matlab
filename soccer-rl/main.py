import tensorflow as tf
import numpy as np
import pybullet as p
import matplotlib as plt
from time import sleep


# wrapper class for measurement values of a joint
class JointMeasurement:
    def __init__(self):
        self.orientation = (0, 0, 0)
        self.velocity = (0, 0, 0)
        self.position = (0, 0, 0)


# Encapsulates a trajectory, its total length, and current state.
# Caller is responsible for checking to see if the animation is done and resetting when appropriate.
class Animation:
    def __init__(self, path):
        self.loadTrajectoryCSV(path)
        self.currentTimer = 0
        self.length = len(self.trajectory)

    # loads joint positions for a trajectory from a CSV file into a 2-D list where each one of the inner lists
    # is a list of positions for each joint at a single instance of time
    def loadTrajectoryCSV(self, path):
        self.trajectory = []
        with open(path, 'r') as inFile:
            for line in inFile:
                self.trajectory.append(list(map(float, line.split(','))))

    # returns joint positions at current time of trajectory
    def run(self):
        if (self.currentTimer < self.length):
            rval = self.trajectory[self.currentTimer]
            self.currentTimer += 1
            return rval
        else:
            raise IndexError("Attempted to run a finished animation.")

    def isDone(self):
        return self.currentTimer == self.length

    def reset(self):
        self.currentTimer = 0

# Encapsulates robot state. Do not directly assign to state parameters. Use the predefined values instead
class RobotState:

    # motor states
    ACTIVE = "ACTIVE"
    DEACTIVE = "DEACTIVE"

    # balance stats
    STABLE = "STABLE"
    TILTED_BACK = "TILTED_BACK"
    TILTED_FORWARD = "TILTED_FORWARD"

    def __init__(self):
        self.motorState = self.DEACTIVE
        self.balanceState = self.STABLE

    def __str__(self):
        return "balance: " + self.balanceState + "\nmotor: " + self.motorState


class Robot:

    # maximum pitch beyond which the robot is to be considered tilted
    MAX_ALLOWED_PITCH = 0.785398163

    def __init__(self):

        # initialize robot
        self.body = p.loadURDF("../soccer_description/models/soccerbot/model.xacro")
        self.state = RobotState()
        self.imu = -1
        self.imuMeasurements = JointMeasurement()
        self.joints = []
        self.motors = []

        # create a list of joints and find the IMU
        for i in range(p.getNumJoints(self.body)):
            self.joints.append(i)
            jointInfo = p.getJointInfo(self.body, i)
            if jointInfo[1].decode('ascii') == "torso_imu":
                self.imu = jointInfo[0]

        if self.imu == -1:
            raise AttributeError("Could not find robot's imu sensor from joint list")

        # rearrange joint order to match the order of positions found in the csv files. See:
        # https://docs.google.com/spreadsheets/d/1KgIYwm3fNen8yjLEa-FEWq-GnRUnBjyg4z64nZ2uBv8/edit#gid=775054312
        self.motors = self.joints[2:14] + self.joints[17:21] + self.joints[14:16] + self.joints[0:2]

        # initialize animations
        self.getupBackAnimation = Animation("./trajectories/getupback.csv")
        self.getupFrontAnimation = Animation("./trajectories/getupfront.csv")
        self.readyAnimation = Animation("./trajectories/ready.csv")
        self.standingAnimation = Animation("./trajectories/standing.csv")
        self.activeAnimation = None

    # Get IMU measurements from simulation and convert to usable format
    def updateImuMeasurments(self):

        imu_info = p.getLinkState(self.body, self.imu, computeLinkVelocity=1)
        self.imuMeasurements.position = imu_info[0]
        self.imuMeasurements.orientation = p.getEulerFromQuaternion(imu_info[1])
        self.imuMeasurements.velocity = imu_info[6]

    # Interpret IMU measurements to determine if the robot is tilted. updates state accordingly
    def updateBalanceState(self):
        self.updateImuMeasurments()
        pitch = self.imuMeasurements.orientation[1]

        if pitch >= self.MAX_ALLOWED_PITCH:
            self.state.balanceState = self.state.TILTED_FORWARD
        elif pitch <= (-1.0) * self.MAX_ALLOWED_PITCH:
            self.state.balanceState = self.state.TILTED_BACK
        else:
            self.state.balanceState = self.state.STABLE

    # Receives a list of positions and applies it motors
    def runAnimation(self, motorPositions):
        p.setJointMotorControlArray(self.body, self.motors, controlMode=p.POSITION_CONTROL,
                                    targetPositions=motorPositions)

    # Attempts to keep the robot standing up by running animations based on state.
    # Animations will only run when the robot is relatively stationary i.e. this will allow the robot to fully
    # fall and then try to get it to stand up again
    def stabilize(self):
        if self.state.motorState == self.state.DEACTIVE:
            self.updateBalanceState()
            if sum(self.imuMeasurements.velocity) < 0.05:
                if self.state.balanceState == self.state.TILTED_BACK:
                    self.activeAnimation = self.getupBackAnimation
                    self.state.motorState = self.state.ACTIVE

                elif self.state.balanceState == self.state.TILTED_FORWARD:
                    self.activeAnimation = self.getupFrontAnimation
                    self.state.motorState = self.state.ACTIVE

        elif self.state.motorState == self.state.ACTIVE:
            self.runAnimation(self.activeAnimation.run())

            # Whenever an animation is done,
            #   if the robot is balanced,
            #       run the ready animation in the next iteration to keep it balanced
            #       stop animations after running ready
            #   else
            #       just stop the animation and check balance in the next iteration
            if self.activeAnimation.isDone():
                self.activeAnimation.reset()
                if self.state.balanceState == self.state.STABLE and self.activeAnimation != self.readyAnimation:
                        self.activeAnimation = self.readyAnimation
                else:
                    self.activeAnimation.reset()
                    self.activeAnimation = None
                    self.state.motorState = self.state.DEACTIVE


# creates a ramp using a plane at location path with basePosition = position and baseOrientation = orientation
# where orientation is in yaw, pitch, roll
class Ramp:

    def __init__(self, path, position, orientation):
        self.orientation = orientation
        self.position = position
        self.path = path
        self.plane = p.loadURDF(self.path, basePosition=self.position,
                                baseOrientation=p.getQuaternionFromEuler(self.orientation))
    
    def setOrientation(self, orientation):
        p.removeBody(self.plane)
        self.__init__(self.path, self.position, orientation)

    def setPosition(self, position):
        p.removeBody(self.plane)
        self.__init__(self.path, position, self.orientation)


if __name__ == '__main__':

    # demo 

    # Pybullet Setup
    p.connect(p.GUI)
    ramp = Ramp("pybullet/gym/pybullet_data/plane.urdf", (0, 0, 0), (0, 0, 0))
    myrobot = Robot()
    p.setGravity(0, 0, -10)

    # Step through simulation
    while(1):
        sleep(0.01)
        pos, orn = p.getBasePositionAndOrientation(myrobot.body)
        myrobot.stabilize()
        p.stepSimulation()