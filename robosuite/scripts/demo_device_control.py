"""Teleoperate robot with keyboard or SpaceMouse.

Keyboard:
    We use the keyboard to control the end-effector of the robot.
    The keyboard provides 6-DoF control commands through various keys.
    The commands are mapped to joint velocities through an inverse kinematics
    solver from Bullet physics.

    Note:
        To run this script with Mac OS X, you must run it with root access.

SpaceMouse:

    We use the SpaceMouse 3D mouse to control the end-effector of the robot.
    The mouse provides 6-DoF control commands. The commands are mapped to joint
    velocities through an inverse kinematics solver from Bullet physics.

    The two side buttons of SpaceMouse are used for controlling the grippers.

    SpaceMouse Wireless from 3Dconnexion: https://www.3dconnexion.com/spacemouse_wireless/en/
    We used the SpaceMouse Wireless in our experiments. The paper below used the same device
    to collect human demonstrations for imitation learning.

    Reinforcement and Imitation Learning for Diverse Visuomotor Skills
    Yuke Zhu, Ziyu Wang, Josh Merel, Andrei Rusu, Tom Erez, Serkan Cabi, Saran Tunyasuvunakool,
    János Kramár, Raia Hadsell, Nando de Freitas, Nicolas Heess
    RSS 2018

    Note:
        This current implementation only supports Mac OS X (Linux support can be added).
        Download and install the driver before running the script:
            https://www.3dconnexion.com/service/drivers.html

Example:
    $ python demo_device_control.py --environment SawyerPickPlaceCan

"""

import argparse
import numpy as np
import sys
import os
import json

import robosuite
import robosuite.utils.transform_utils as T
from robosuite.wrappers import IKWrapper


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", type=str, default="SawyerLift")
    parser.add_argument("--controller", type=str, default="ik", help="Choice of controller. Can be 'ik' or 'osc'")
    parser.add_argument("--device", type=str, default="spacemouse")
    args = parser.parse_args()

    # Import controller config for EE IK or OSC (pos/ori)
    controller_config = None
    controller_path = None
    if args.controller == 'ik':
        controller_path = os.path.join(os.path.dirname(__file__), '..', 'controllers/config/ee_ik.json')
    elif args.controller == 'osc':
        controller_path = os.path.join(os.path.dirname(__file__), '..', 'controllers/config/ee_pos_ori.json')
    else:
        print("Error: Unsupported controller specified. Must be either 'ik' or 'osc'!")
        raise ValueError
    try:
        with open(controller_path) as f:
            controller_config = json.load(f)
            if args.controller == 'osc':
                controller_config["max_action"] = 1
                controller_config["min_action"] = -1
                controller_config["control_delta"] = False
                # Must have a cumulative dpos since we are controlling absolute pos and ori values
                cumulative_dpos = 0
    except FileNotFoundError:
        print("Error opening default controller filepath at: {}. "
              "Please check filepath and try again.".format(controller_path))

    env = robosuite.make(
        args.environment,
        has_renderer=True,
        ignore_done=True,
        use_camera_obs=False,
        gripper_visualization=True,
        reward_shaping=True,
        control_freq=100,
        controller_config=controller_config
    )

    np.set_printoptions(formatter={'float': lambda x: "{0:0.3f}".format(x)})

    # initialize device
    if args.device == "keyboard":
        from robosuite.devices import Keyboard

        device = Keyboard()
        env.viewer.add_keypress_callback("any", device.on_press)
        env.viewer.add_keyup_callback("any", device.on_release)
        env.viewer.add_keyrepeat_callback("any", device.on_press)
    elif args.device == "spacemouse":
        from robosuite.devices import SpaceMouse

        device = SpaceMouse()
    else:
        raise Exception(
            "Invalid device choice: choose either 'keyboard' or 'spacemouse'."
        )

    while True:
        obs = env.reset()
        env.viewer.set_camera(camera_id=2)
        env.render()

        # rotate the gripper so we can see it easily
        if env.mujoco_robot.name == 'sawyer':
            # TODO: Confirm that this is no longer necessary
            pass
            #env.set_robot_joint_positions([0, -1.18, 0.00, 2.18, 0.00, 0.57, 1.5708])
        elif env.mujoco_robot.name == 'panda':
            env.set_robot_joint_positions([0, np.pi / 16.0, 0.00, -np.pi / 2.0 - np.pi / 3.0, 0.00, np.pi - 0.2, -np.pi/4])
        else:
            print("Error: Script supported for Sawyer and Panda robots only!")
            sys.exit()

        device.start_control()
        while True:
            state = device.get_controller_state()
            # Note: Devices output rotation with x and z flipped to account for robots starting with gripper facing down
            #       Also note that the outputted rotation is an absolute rotation, while outputted dpos is delta pos
            dpos, rotation, grasp, reset = (
                state["dpos"],
                state["rotation"],
                state["grasp"],
                state["reset"],
            )
            if reset:
                break

            # convert into a suitable end effector action for the environment
            current = env._right_hand_orn

            # relative rotation of desired from current
            drotation = current.T.dot(rotation)

            if args.controller == 'ik':
                # IK expects quat, so convert to quat
                drotation = T.mat2quat(drotation)
            elif args.controller == 'osc':
                # OSC expects euler, so convert to euler
                drotation = T.mat2euler(drotation)

                # Since the input rotation is absolute (relative to initial), input pos must also be absolute
                # So increment cumulative dpos (scaled down) and use that as input
                cumulative_dpos += dpos * 0.1
                dpos = cumulative_dpos

            # map 0 to -1 (open) and 1 to 0 (closed halfway)
            grasp = grasp - 1.

            action = np.concatenate([dpos, drotation, [grasp]])
            obs, reward, done, info = env.step(action)
            env.render()