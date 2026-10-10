import math
import random
import time

import pybullet as p
import pybullet_data

from industrial_kitting import (
    close_gripper,
    get_joint_index_by_name,
    get_joint_indices_by_type,
    open_gripper,
    read_limits,
)


TIME_STEP = 1.0 / 240.0
BELT_SPEED = 0.18
ROBOT_SPEED_MULTIPLIER = 1.8
BELT_CENTER = [0.55, -0.68, 0.06]
BELT_HALF_EXTENTS = [0.20, 0.60, 0.06]
BELT_TOP_Z = BELT_CENTER[2] + BELT_HALF_EXTENTS[2]
CUBE_HALF_SIZE = 0.025
CUBE_SPAWN_Y = -1.15
PICKUP_Y = -0.16
PANDA_HOME = [0.0, -0.55, 0.0, -2.15, 0.0, 1.65, 0.80]
CAMERA_UPDATE_INTERVAL = 24
CAMERA_STEP_COUNTER = 0
PRODUCT_COLORS = {
    "RED": [0.92, 0.06, 0.04, 1.0],
    "GREEN": [0.05, 0.72, 0.14, 1.0],
    "BLUE": [0.05, 0.28, 0.95, 1.0],
}
BOX_CENTERS = {
    "RED": [0.26, 0.29],
    "GREEN": [0.50, 0.46],
    "BLUE": [0.71, 0.22],
}
BOX_SLOT_OFFSETS = [
    [-0.027, -0.027],
    [0.027, -0.027],
    [-0.027, 0.027],
    [0.027, 0.027],
]
BOX_DROP_SLOTS = {
    color_name: [
        [center[0] + offset[0], center[1] + offset[1]]
        for offset in BOX_SLOT_OFFSETS
    ]
    for color_name, center in BOX_CENTERS.items()
}
BOX_CAPACITY = len(BOX_SLOT_OFFSETS)


def render_camera_panels():
    """Render the RGB, depth, and segmentation views shown in the GUI panels."""
    view_matrix = p.computeViewMatrix(
        cameraEyePosition=[1.45, -1.65, 1.35],
        cameraTargetPosition=[0.48, -0.38, 0.12],
        cameraUpVector=[0.0, 0.0, 1.0],
    )
    projection_matrix = p.computeProjectionMatrixFOV(
        fov=58.0,
        aspect=4.0 / 3.0,
        nearVal=0.05,
        farVal=5.0,
    )
    p.getCameraImage(
        width=240,
        height=180,
        viewMatrix=view_matrix,
        projectionMatrix=projection_matrix,
        shadow=1,
        renderer=p.ER_BULLET_HARDWARE_OPENGL,
    )


def step_simulation():
    """Advance physics and refresh the three synthetic-camera panels."""
    global CAMERA_STEP_COUNTER

    p.stepSimulation()
    CAMERA_STEP_COUNTER += 1
    if CAMERA_STEP_COUNTER % CAMERA_UPDATE_INTERVAL == 0:
        render_camera_panels()
    time.sleep(TIME_STEP)


def wait_steps(number_of_steps):
    for _ in range(number_of_steps):
        step_simulation()


def create_static_box(half_extents, position, color):
    collision = p.createCollisionShape(p.GEOM_BOX, halfExtents=half_extents)
    visual = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=half_extents,
        rgbaColor=color,
    )
    return p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=collision,
        baseVisualShapeIndex=visual,
        basePosition=position,
    )


def create_conveyor():
    create_static_box(BELT_HALF_EXTENTS, BELT_CENTER, [0.12, 0.16, 0.20, 1.0])

    # Side rails keep incoming products on the belt.
    rail_z = BELT_TOP_Z + 0.035
    create_static_box(
        [0.015, BELT_HALF_EXTENTS[1], 0.035],
        [BELT_CENTER[0] - BELT_HALF_EXTENTS[0], BELT_CENTER[1], rail_z],
        [0.65, 0.68, 0.72, 1.0],
    )
    create_static_box(
        [0.015, BELT_HALF_EXTENTS[1], 0.035],
        [BELT_CENTER[0] + BELT_HALF_EXTENTS[0], BELT_CENTER[1], rail_z],
        [0.65, 0.68, 0.72, 1.0],
    )

    # Yellow strip represents the pickup sensor/stopping line.
    pickup_visual = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=[0.17, 0.015, 0.003],
        rgbaColor=[1.0, 0.78, 0.05, 1.0],
    )
    p.createMultiBody(
        baseMass=0,
        baseVisualShapeIndex=pickup_visual,
        basePosition=[BELT_CENTER[0], PICKUP_Y, BELT_TOP_Z + 0.004],
    )
    p.addUserDebugText(
        "PICKUP STATION",
        [BELT_CENTER[0] - 0.18, PICKUP_Y, BELT_TOP_Z + 0.09],
        textColorRGB=[1.0, 0.85, 0.0],
        textSize=1.2,
    )


def create_painting_station():
    station_y = -1.12
    station_color = [0.025, 0.025, 0.035, 1.0]

    # The front is left open so each painted cube emerges onto the conveyor.
    create_static_box(
        [0.025, 0.13, 0.12],
        [BELT_CENTER[0] - 0.19, station_y, BELT_TOP_Z + 0.12],
        station_color,
    )
    create_static_box(
        [0.025, 0.13, 0.12],
        [BELT_CENTER[0] + 0.19, station_y, BELT_TOP_Z + 0.12],
        station_color,
    )
    create_static_box(
        [0.19, 0.025, 0.12],
        [BELT_CENTER[0], station_y - 0.13, BELT_TOP_Z + 0.12],
        station_color,
    )
    create_static_box(
        [0.215, 0.15, 0.025],
        [BELT_CENTER[0], station_y, BELT_TOP_Z + 0.25],
        station_color,
    )
    p.addUserDebugText(
        "PAINTING STATION",
        [BELT_CENTER[0] - 0.18, station_y, BELT_TOP_Z + 0.31],
        textColorRGB=[0.95, 0.95, 0.95],
        textSize=1.2,
    )


def create_sorting_box(color_name, center, box_color):
    center_x, center_y = center
    inner_half_x = 0.075
    inner_half_y = 0.075
    wall_thickness = 0.015
    wall_height = 0.09
    translucent_color = [*box_color[:3], 0.82]

    create_static_box(
        [inner_half_x + wall_thickness, inner_half_y + wall_thickness, 0.015],
        [center_x, center_y, 0.015],
        translucent_color,
    )
    create_static_box(
        [wall_thickness, inner_half_y, wall_height],
        [center_x - inner_half_x - wall_thickness, center_y, wall_height],
        translucent_color,
    )
    create_static_box(
        [wall_thickness, inner_half_y, wall_height],
        [center_x + inner_half_x + wall_thickness, center_y, wall_height],
        translucent_color,
    )
    create_static_box(
        [inner_half_x, wall_thickness, wall_height],
        [center_x, center_y - inner_half_y - wall_thickness, wall_height],
        translucent_color,
    )
    create_static_box(
        [inner_half_x, wall_thickness, wall_height],
        [center_x, center_y + inner_half_y + wall_thickness, wall_height],
        translucent_color,
    )
    p.addUserDebugText(
        f"{color_name} BOX",
        [center_x - 0.07, center_y, 0.23],
        textColorRGB=box_color[:3],
        textSize=1.0,
    )


def create_sorting_boxes():
    for color_name, center in BOX_CENTERS.items():
        create_sorting_box(color_name, center, PRODUCT_COLORS[color_name])


def load_panda():
    panda = p.loadURDF(
        "assets/franka_panda/panda.urdf",
        [0, 0, 0],
        useFixedBase=True,
    )
    for joint, target in enumerate(PANDA_HOME):
        p.resetJointState(panda, joint, target)
        p.setJointMotorControl2(
            panda,
            joint,
            p.POSITION_CONTROL,
            targetPosition=target,
            force=200,
        )
    for finger_joint in (9, 10):
        p.resetJointState(panda, finger_joint, 0.04)
    return panda


def settle_joint_targets(
    panda,
    joint_indices,
    target_positions,
    timeout=1.5,
    tolerance=0.0025,
):
    """Hold a waypoint until the simulated joints physically reach it."""
    consecutive_stable_steps = 0
    max_steps = max(1, int(timeout / TIME_STEP))

    for _ in range(max_steps):
        p.setJointMotorControlArray(
            panda,
            joint_indices,
            p.POSITION_CONTROL,
            targetPositions=target_positions,
            forces=[300.0] * len(joint_indices),
            positionGains=[0.28] * len(joint_indices),
            velocityGains=[1.0] * len(joint_indices),
        )
        step_simulation()

        errors = [
            abs(p.getJointState(panda, joint)[0] - target)
            for joint, target in zip(joint_indices, target_positions)
        ]
        if max(errors, default=0.0) <= tolerance:
            consecutive_stable_steps += 1
            if consecutive_stable_steps >= 12:
                return True
        else:
            consecutive_stable_steps = 0

    return False


def move_joints_smooth(panda, joint_indices, target_positions, duration=2.5):
    """Move to a known joint pose with eased velocity and acceleration."""
    start_positions = [
        p.getJointState(panda, joint)[0] for joint in joint_indices
    ]
    total_steps = max(1, int(duration / (TIME_STEP * ROBOT_SPEED_MULTIPLIER)))

    for step in range(1, total_steps + 1):
        progress = step / total_steps
        blend = 10 * progress**3 - 15 * progress**4 + 6 * progress**5
        joint_targets = [
            start + (target - start) * blend
            for start, target in zip(start_positions, target_positions)
        ]
        p.setJointMotorControlArray(
            panda,
            joint_indices,
            p.POSITION_CONTROL,
            targetPositions=joint_targets,
            forces=[250.0] * len(joint_indices),
            positionGains=[0.18] * len(joint_indices),
            velocityGains=[1.0] * len(joint_indices),
        )
        step_simulation()

    settle_joint_targets(panda, joint_indices, target_positions)


def move_arm_smooth(
    panda,
    arm_joints,
    eef,
    target_position,
    target_orientation,
    lowers,
    uppers,
    ranges,
    duration=3.0,
):
    """Move through an eased joint trajectory with zero end velocity."""
    controlled_joints = arm_joints[:-2]
    start_positions = [
        p.getJointState(panda, joint)[0] for joint in controlled_joints
    ]
    rest_positions = [p.getJointState(panda, joint)[0] for joint in arm_joints]

    ik_solution = p.calculateInverseKinematics(
        panda,
        eef,
        target_position,
        target_orientation,
        lowerLimits=lowers,
        upperLimits=uppers,
        jointRanges=ranges,
        restPoses=rest_positions,
        maxNumIterations=150,
        residualThreshold=1e-5,
    )
    target_positions = list(ik_solution[: len(controlled_joints)])
    total_steps = max(1, int(duration / (TIME_STEP * ROBOT_SPEED_MULTIPLIER)))

    for step in range(1, total_steps + 1):
        progress = step / total_steps
        # Quintic smoothstep: smooth velocity and acceleration at both ends.
        blend = 10 * progress**3 - 15 * progress**4 + 6 * progress**5
        joint_targets = [
            start + (target - start) * blend
            for start, target in zip(start_positions, target_positions)
        ]
        p.setJointMotorControlArray(
            panda,
            controlled_joints,
            p.POSITION_CONTROL,
            targetPositions=joint_targets,
            forces=[250.0] * len(controlled_joints),
            positionGains=[0.18] * len(controlled_joints),
            velocityGains=[1.0] * len(controlled_joints),
        )
        step_simulation()

    reached_target = settle_joint_targets(
        panda,
        controlled_joints,
        target_positions,
    )
    if not reached_target:
        print("Warning: robot reached the waypoint with a small residual joint error.")


def spawn_random_cube(cycle_number):
    random_x = random.uniform(0.43, 0.67)
    random_yaw = random.uniform(-math.pi, math.pi)
    color_name = random.choice(tuple(PRODUCT_COLORS))
    cube_z = BELT_TOP_Z + CUBE_HALF_SIZE + 0.005
    cube = p.loadURDF(
        "assets/cubes/5cm_red_cube.urdf",
        [random_x, CUBE_SPAWN_Y, cube_z],
        p.getQuaternionFromEuler([0, 0, random_yaw]),
        useFixedBase=False,
    )
    p.changeVisualShape(cube, -1, rgbaColor=PRODUCT_COLORS[color_name])
    p.changeDynamics(cube, -1, lateralFriction=0.25, restitution=0.0)
    print(
        f"\n=== PRODUCTION CYCLE {cycle_number} ===\n"
        f"Painting station released a {color_name} cube at random x={random_x:.3f} m, "
        f"yaw={math.degrees(random_yaw):.1f} degrees."
    )
    return cube, color_name


def move_cube_to_pickup_station(cube):
    print("Conveyor running...")
    while p.isConnected():
        position, orientation = p.getBasePositionAndOrientation(cube)
        if position[1] >= PICKUP_Y:
            break

        p.resetBaseVelocity(cube, linearVelocity=[0.0, BELT_SPEED, 0.0])
        step_simulation()

    position, orientation = p.getBasePositionAndOrientation(cube)
    stopped_position = [position[0], PICKUP_Y, BELT_TOP_Z + CUBE_HALF_SIZE]
    p.resetBasePositionAndOrientation(cube, stopped_position, orientation)
    p.resetBaseVelocity(cube, linearVelocity=[0.0, 0.0, 0.0])

    for _ in range(60):
        step_simulation()

    final_position, _ = p.getBasePositionAndOrientation(cube)
    print(
        "Pickup sensor triggered. Conveyor stopped at "
        f"x={final_position[0]:.3f}, y={final_position[1]:.3f}."
    )
    return list(final_position)


def pick_cube_and_place_in_box(
    panda,
    cube,
    cube_position,
    box_slot,
    color_name,
):
    arm_joints, _ = get_joint_indices_by_type(panda)
    link_names = [
        p.getJointInfo(panda, joint)[12].decode("utf-8")
        for joint in range(p.getNumJoints(panda))
    ]
    eef = link_names.index("panda_hand")
    finger_1 = get_joint_index_by_name(panda, "panda_finger_joint1")
    finger_2 = get_joint_index_by_name(panda, "panda_finger_joint2")
    lowers, uppers, ranges = read_limits(panda, arm_joints)

    # Disable the default arm motors before sending our IK targets.
    for joint in arm_joints:
        p.setJointMotorControl2(panda, joint, p.VELOCITY_CONTROL, force=0.0)

    down_orientation = p.getQuaternionFromEuler([math.pi, 0, 0])
    pick_x, pick_y = cube_position[:2]

    pregrasp = [pick_x, pick_y, 0.38]
    grasp = [pick_x, pick_y, BELT_TOP_Z + CUBE_HALF_SIZE + 0.105]
    lift = [pick_x, pick_y, 0.43]
    above_box = [box_slot[0], box_slot[1], 0.46]
    drop_in_box = [box_slot[0], box_slot[1], 0.34]

    print("Robot opening gripper and approaching the product...")
    open_gripper(panda, finger_1, finger_2, width_each=0.04, force=200)
    wait_steps(60)

    move_arm_smooth(
        panda,
        arm_joints,
        eef,
        pregrasp,
        down_orientation,
        lowers,
        uppers,
        ranges,
        duration=3.2,
    )
    move_arm_smooth(
        panda,
        arm_joints,
        eef,
        grasp,
        down_orientation,
        lowers,
        uppers,
        ranges,
        duration=2.4,
    )

    print("Robot closing gripper...")
    close_gripper(panda, finger_1, finger_2, force=250)
    wait_steps(90)

    # Center the product in the gripper before creating the simulated grasp.
    # This prevents small IK errors from becoming pickup or drop errors.
    hand_position, hand_orientation = p.getLinkState(panda, eef)[4:6]
    actual_cube_position, actual_cube_orientation = p.getBasePositionAndOrientation(cube)
    centered_cube_position, _ = p.multiplyTransforms(
        hand_position,
        hand_orientation,
        [0.0, 0.0, 0.105],
        [0.0, 0.0, 0.0, 1.0],
    )
    p.resetBasePositionAndOrientation(
        cube,
        centered_cube_position,
        actual_cube_orientation,
    )
    p.resetBaseVelocity(cube, linearVelocity=[0, 0, 0], angularVelocity=[0, 0, 0])
    actual_cube_position, actual_cube_orientation = p.getBasePositionAndOrientation(cube)

    inverse_hand_position, inverse_hand_orientation = p.invertTransform(
        hand_position,
        hand_orientation,
    )
    relative_position, relative_orientation = p.multiplyTransforms(
        inverse_hand_position,
        inverse_hand_orientation,
        actual_cube_position,
        actual_cube_orientation,
    )

    # A fixed grasp constraint makes the simulated industrial grip reliable.
    grasp_constraint = p.createConstraint(
        parentBodyUniqueId=panda,
        parentLinkIndex=eef,
        childBodyUniqueId=cube,
        childLinkIndex=-1,
        jointType=p.JOINT_FIXED,
        jointAxis=[0, 0, 0],
        parentFramePosition=relative_position,
        childFramePosition=[0, 0, 0],
        parentFrameOrientation=relative_orientation,
        childFrameOrientation=[0, 0, 0, 1],
    )
    p.changeConstraint(grasp_constraint, maxForce=300)

    print(f"Product picked. Moving to the {color_name} sorting box...")
    move_arm_smooth(
        panda,
        arm_joints,
        eef,
        lift,
        down_orientation,
        lowers,
        uppers,
        ranges,
        duration=2.6,
    )
    move_arm_smooth(
        panda,
        arm_joints,
        eef,
        above_box,
        down_orientation,
        lowers,
        uppers,
        ranges,
        duration=3.4,
    )
    move_arm_smooth(
        panda,
        arm_joints,
        eef,
        drop_in_box,
        down_orientation,
        lowers,
        uppers,
        ranges,
        duration=2.2,
    )

    print(f"Releasing product into the {color_name} sorting box...")
    open_gripper(panda, finger_1, finger_2, width_each=0.04, force=120)
    p.removeConstraint(grasp_constraint)
    p.resetBaseVelocity(cube, linearVelocity=[0, 0, 0], angularVelocity=[0, 0, 0])
    wait_steps(240)

    move_arm_smooth(
        panda,
        arm_joints,
        eef,
        above_box,
        down_orientation,
        lowers,
        uppers,
        ranges,
        duration=2.5,
    )
    print("Returning robot to the cycle-ready home pose...")
    move_joints_smooth(
        panda,
        arm_joints[:-2],
        PANDA_HOME,
        duration=2.8,
    )
    open_gripper(panda, finger_1, finger_2, width_each=0.04, force=120)
    wait_steps(60)
    print(f"{color_name} product sorted. Robot ready for the next cycle.")


def main():
    p.connect(p.GUI)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setTimeStep(TIME_STEP)
    p.setGravity(0, 0, -9.81)
    p.loadURDF("plane.urdf")

    p.resetDebugVisualizerCamera(
        cameraDistance=2.10,
        cameraYaw=48,
        cameraPitch=-48,
        cameraTargetPosition=[0.48, -0.32, 0.10],
    )

    create_conveyor()
    create_painting_station()
    create_sorting_boxes()
    panda = load_panda()
    render_camera_panels()

    try:
        cycle_number = 1
        packed_cubes = {color_name: [] for color_name in PRODUCT_COLORS}

        while p.isConnected():
            cube, color_name = spawn_random_cube(cycle_number)
            cube_position = move_cube_to_pickup_station(cube)
            print("Conveyor paused: product is waiting for the robot.")

            slot_index = len(packed_cubes[color_name])
            pick_cube_and_place_in_box(
                panda,
                cube,
                cube_position,
                BOX_DROP_SLOTS[color_name][slot_index],
                color_name,
            )
            packed_cubes[color_name].append(cube)
            print(
                f"{color_name} box count: "
                f"{len(packed_cubes[color_name])}/{BOX_CAPACITY}"
            )

            if len(packed_cubes[color_name]) == BOX_CAPACITY:
                print(
                    f"{color_name} box full. "
                    "Dispatching it and loading an empty box..."
                )
                wait_steps(240)
                for packed_cube in packed_cubes[color_name]:
                    p.removeBody(packed_cube)
                packed_cubes[color_name].clear()
                print(f"Empty {color_name} sorting box ready.")

            cycle_number += 1
            print("Starting the next production cycle...")
            wait_steps(120)
    except KeyboardInterrupt:
        print("\nSimulation stopped cleanly.")
    finally:
        if p.isConnected():
            p.disconnect()


if __name__ == "__main__":
    main()
