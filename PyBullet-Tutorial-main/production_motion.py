"""Faster production motion with measured grasp alignment and paced physics."""

import math
import time

import pybullet as p

import conveyor_kitting as conveyor

BELT_SPEED = 0.50
HAND_OFFSET = 0.105
MAX_JOINT_SPEED = 2.4


def create_conveyor():
    conveyor.create_static_box(conveyor.BELT_HALF_EXTENTS, conveyor.BELT_CENTER, [0.12, 0.16, 0.20, 1])
    start_y = conveyor.BELT_CENTER[1] - conveyor.BELT_HALF_EXTENTS[1]
    rail_end_y = conveyor.PICKUP_Y - 0.14
    half_length = (rail_end_y - start_y) / 2
    rail_y = (rail_end_y + start_y) / 2
    for sign in (-1, 1):
        conveyor.create_static_box(
            [0.015, half_length, 0.035],
            [conveyor.BELT_CENTER[0] + sign*conveyor.BELT_HALF_EXTENTS[0], rail_y, conveyor.BELT_TOP_Z+0.035],
            [0.65, 0.68, 0.72, 1],
        )
    # Leave the pickup area open so rotated fingers cannot strike the rails.
    visual = p.createVisualShape(p.GEOM_BOX, halfExtents=[0.17, 0.015, 0.003], rgbaColor=[1, 0.78, 0.05, 1])
    p.createMultiBody(baseMass=0, baseVisualShapeIndex=visual, basePosition=[conveyor.BELT_CENTER[0], conveyor.PICKUP_Y, conveyor.BELT_TOP_Z+0.004])


class RealtimeStepper:
    """Keep physics at 240 Hz, sleeping once per four steps without accumulating drift."""

    def __init__(self, refresh, realtime=True):
        self.refresh = refresh
        self.realtime = realtime
        self.deadline = time.perf_counter()
        self.steps = 0

    def __call__(self):
        if not p.isConnected():
            raise KeyboardInterrupt
        self.refresh()
        p.stepSimulation()
        self.steps += 1
        self.deadline += conveyor.TIME_STEP
        if self.realtime and self.steps % 4 == 0:
            now = time.perf_counter()
            if self.deadline > now:
                time.sleep(self.deadline - now)
            elif now - self.deadline > 0.10:
                # Avoid a burst of accelerated physics after a window is dragged.
                self.deadline = now


def move_cube_to_station(cube, station_y, station_name):
    started = time.perf_counter()
    while p.isConnected():
        position, _ = p.getBasePositionAndOrientation(cube)
        remaining = station_y - position[1]
        if remaining <= 0.001:
            break
        velocity = min(BELT_SPEED, remaining / conveyor.TIME_STEP)
        p.resetBaseVelocity(cube, linearVelocity=[0, velocity, 0], angularVelocity=[0, 0, 0])
        conveyor.step_simulation()
    position, orientation = p.getBasePositionAndOrientation(cube)
    p.resetBasePositionAndOrientation(
        cube,
        [position[0], station_y, conveyor.BELT_TOP_Z + conveyor.CUBE_HALF_SIZE],
        orientation,
    )
    p.resetBaseVelocity(cube, linearVelocity=[0, 0, 0], angularVelocity=[0, 0, 0])
    conveyor.wait_steps(24)
    position, _ = p.getBasePositionAndOrientation(cube)
    print(f"Conveyor travel: {time.perf_counter()-started:.2f}s | {station_name}: {position[0]:.3f}, {position[1]:.3f}")
    return list(position)


def move_cube_to_pickup_station(cube):
    return move_cube_to_station(cube, conveyor.PICKUP_Y, "Pickup")


def drive_joints(robot, joints, targets, minimum_duration=0.30):
    start = [p.getJointState(robot, joint)[0] for joint in joints]
    # The peak velocity of quintic interpolation is 1.875 times its average.
    duration = max(minimum_duration, 1.875 * max(abs(a-b) for a, b in zip(start, targets)) / MAX_JOINT_SPEED)
    steps = max(1, int(duration / conveyor.TIME_STEP))
    for step in range(1, steps + 1):
        t = step / steps
        blend = 10*t**3 - 15*t**4 + 6*t**5
        p.setJointMotorControlArray(
            robot, joints, p.POSITION_CONTROL,
            targetPositions=[a+(b-a)*blend for a, b in zip(start, targets)],
            forces=[250.0]*len(joints), positionGains=[0.24]*len(joints),
            velocityGains=[1.0]*len(joints),
        )
        conveyor.step_simulation()
    if not conveyor.settle_joint_targets(robot, joints, targets, timeout=0.65, tolerance=0.003):
        raise RuntimeError("Robot could not settle at the requested pose; product held.")


def move_hand(robot, joints, eef, position, orientation, minimum_duration=0.30):
    lowers, uppers, ranges = conveyor.read_limits(robot, joints)
    for attempt in range(3):
        solution = p.calculateInverseKinematics(
            robot, eef, position, orientation,
            lowerLimits=lowers, upperLimits=uppers, jointRanges=ranges,
            restPoses=[p.getJointState(robot, j)[0] for j in joints],
            maxNumIterations=500, residualThreshold=1e-6,
        )
        drive_joints(robot, joints[:7], list(solution[:7]), minimum_duration if attempt == 0 else 0.16)
        state = p.getLinkState(robot, eef, computeForwardKinematics=True)
        position_error = math.dist(state[4], position)
        orientation_dot = min(1.0, abs(sum(a*b for a, b in zip(state[5], orientation))))
        if position_error <= 0.003 and 2*math.acos(orientation_dot) <= 0.035:
            return
    raise RuntimeError(f"Hand missed its target by {position_error*1000:.1f} mm; product held.")


def set_gripper(robot, fingers, width):
    for joint in fingers:
        p.setJointMotorControl2(
            robot, joint, p.POSITION_CONTROL, targetPosition=width,
            positionGain=0.25, velocityGain=1.0, force=60,
        )


def pick_cube_and_place_in_box(robot, cube, cube_position, slot, destination):
    started = time.perf_counter()
    joints, _ = conveyor.get_joint_indices_by_type(robot)
    names = [p.getJointInfo(robot, j)[12].decode() for j in range(p.getNumJoints(robot))]
    eef = names.index("panda_hand")
    fingers = [conveyor.get_joint_index_by_name(robot, name) for name in ("panda_finger_joint1", "panda_finger_joint2")]
    constraint = None
    collisions_disabled = False
    try:
        position, rotation = p.getBasePositionAndOrientation(cube)
        yaw = p.getEulerFromQuaternion(rotation)[2]
        # A square cube repeats every quarter-turn; use the nearest grip angle.
        yaw = (yaw + math.pi/4) % (math.pi/2) - math.pi/4
        grip_rotation = p.getQuaternionFromEuler([math.pi, 0, yaw])
        drop_rotation = p.getQuaternionFromEuler([math.pi, 0, 0])
        set_gripper(robot, fingers, 0.04)
        conveyor.wait_steps(24)
        move_hand(robot, joints, eef, [position[0], position[1], 0.36], grip_rotation)

        # Re-read the live cube pose rather than using a stale conveyor reading.
        for _ in range(3):
            position, _ = p.getBasePositionAndOrientation(cube)
            move_hand(robot, joints, eef, [position[0], position[1], position[2]+HAND_OFFSET], grip_rotation, 0.32)
            state = p.getLinkState(robot, eef, computeForwardKinematics=True)
            grip_center, _ = p.multiplyTransforms(state[4], state[5], [0, 0, HAND_OFFSET], [0, 0, 0, 1])
            actual, _ = p.getBasePositionAndOrientation(cube)
            error = math.dist(grip_center, actual)
            if error <= 0.004:
                break
        else:
            raise RuntimeError(f"Pickup alignment error {error*1000:.1f} mm; product held.")

        set_gripper(robot, fingers, 0.024)
        conveyor.wait_steps(40)
        state = p.getLinkState(robot, eef, computeForwardKinematics=True)
        actual, rotation = p.getBasePositionAndOrientation(cube)
        grip_center, _ = p.multiplyTransforms(state[4], state[5], [0, 0, HAND_OFFSET], [0, 0, 0, 1])
        error = math.dist(grip_center, actual)
        if error > 0.008:
            raise RuntimeError(f"Cube moved during gripping ({error*1000:.1f} mm); product held.")
        print(f"Measured pickup alignment: {error*1000:.1f} mm")

        # Preserve the measured transform: no teleporting the cube into the hand.
        inverse = p.invertTransform(state[4], state[5])
        relative = p.multiplyTransforms(*inverse, actual, rotation)
        for link in range(-1, p.getNumJoints(robot)):
            p.setCollisionFilterPair(robot, cube, link, -1, 0)
        collisions_disabled = True
        constraint = p.createConstraint(
            robot, eef, cube, -1, p.JOINT_FIXED, [0, 0, 0],
            relative[0], [0, 0, 0], parentFrameOrientation=relative[1],
            childFrameOrientation=[0, 0, 0, 1],
        )
        p.changeConstraint(constraint, maxForce=300)
        move_hand(robot, joints, eef, [actual[0], actual[1], 0.42], grip_rotation)
        move_hand(robot, joints, eef, [slot[0], slot[1], 0.44], drop_rotation)
        move_hand(robot, joints, eef, [slot[0], slot[1], 0.34], drop_rotation)
        set_gripper(robot, fingers, 0.04)
        conveyor.wait_steps(24)
        p.removeConstraint(constraint)
        constraint = None
        p.resetBaseVelocity(cube, linearVelocity=[0, 0, 0], angularVelocity=[0, 0, 0])
        conveyor.wait_steps(70)
        for link in range(-1, p.getNumJoints(robot)):
            p.setCollisionFilterPair(robot, cube, link, -1, 1)
        collisions_disabled = False
        move_hand(robot, joints, eef, [slot[0], slot[1], 0.44], drop_rotation)
        drive_joints(robot, joints[:7], conveyor.PANDA_HOME)
        placed, _ = p.getBasePositionAndOrientation(cube)
        if math.dist(placed[:2], slot) > 0.02 or not 0.04 <= placed[2] <= 0.09:
            raise RuntimeError("Placement verification failed; stop and inspect the box.")
        print(f"{destination} placed | Robot motion: {time.perf_counter()-started:.2f}s")
    finally:
        # On a failed move, retain a carried product until the operator exits.
        if collisions_disabled and constraint is None:
            for link in range(-1, p.getNumJoints(robot)):
                p.setCollisionFilterPair(robot, cube, link, -1, 1)
