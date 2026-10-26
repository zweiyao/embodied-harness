"""Native Cartesian target checks with fake hardware; no robot connection."""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request


@pytest.fixture
def motion(monkeypatch):
    package = ModuleType('tested_native_collector')
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package.__name__, package)
    spec = importlib.util.spec_from_file_location(
        package.__name__ + '.supervised_motion',
        Path(os.environ['FLEXIV_HOME_SOURCE']) / 'supervised_motion.py',
    )
    sm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sm)
    monkeypatch.setattr(sm.time, 'monotonic', lambda: 100.)
    state = dict(fault=False, operational=True, control_initialized=True,
                 mode='Mode.NRT_CARTESIAN_MOTION_FORCE',
                 joint_position=[0.]*7, joint_velocity=[0.]*7,
                 tcp_pose=[.4, 0., .2, 1., 0., 0., 0.],
                 gripper_is_moving=False, gripper_width_m=.02)
    sent, stopped, legacy, grip = [], [], [], []
    robot = SimpleNamespace(
        get_live_state=lambda: state,
        _workspace_min=np.array([0., -.8, -.49]),
        _workspace_max=np.array([1., .8, 1.]),
        _robot=SimpleNamespace(
            SendCartesianMotionForce=lambda target, **kw: sent.append((target, kw)),
            Stop=lambda: stopped.append('robot')),
        _gripper=SimpleNamespace(
            Stop=lambda: stopped.append('gripper'),
            Move=lambda *args: grip.append(args),
            params=lambda: SimpleNamespace(min_width=0., max_width=.1,
                                           min_force=5., max_force=40.,
                                           min_vel=.005, max_vel=.02)),
        send_action=lambda action, **kw: legacy.append((action, kw)),
    )
    cameras = {name: SimpleNamespace(_capture_slot=SimpleNamespace(
        _timestamp=SimpleNamespace(value=100.))) for name in ('left', 'right')}
    bridge = SimpleNamespace(
        authorize=lambda token: None, allow_motion=True, driver=lambda: robot,
        active=True, token='owner', collector=SimpleNamespace(
            config={}, camera_mgr=SimpleNamespace(cameras=cameras), app=FastAPI()))
    m = sm.SupervisedMotion(bridge)
    m.armed, m.expires, m.owner = True, 200., 'owner'
    m.home = SimpleNamespace(owner='owner', pending=None)
    m.state, m.robot, m.sent, m.stopped, m.legacy = state, robot, sent, stopped, legacy
    m.grip = grip
    m.module = sm
    driver = ModuleType('robots.flexiv.driver')
    driver._quaternion_to_rot6d = lambda *q: [1., 0., 0., 0., 1., 0.]
    monkeypatch.setitem(sys.modules, 'robots.flexiv.driver', driver)
    return m


def target(motion, distance=.05, angle_deg=10.):
    result = np.array(motion.state['tcp_pose'])
    result[0] += distance
    half = np.deg2rad(angle_deg)/2
    result[3:] = [np.cos(half), 0., 0., np.sin(half)]
    return result


def test_native_sends_full_target_once_with_explicit_limits(motion):
    goal = target(motion)
    result = motion.pose_step('owner', goal, native=True)
    assert result['native_trajectory'] is True and result['reached'] is None
    assert len(motion.sent) == 1 and motion.legacy == []
    np.testing.assert_allclose(motion.sent[0][0], goal)
    assert motion.sent[0][1] == dict(max_linear_vel=.02, max_angular_vel=.15,
                                    max_linear_acc=.1, max_angular_acc=.5)
    assert motion.command_deadline == 135.
    motion.feedback('owner')
    assert len(motion.sent) == 1 and motion.command_deadline == 135.


@pytest.mark.parametrize('failure', ['distance', 'rotation', 'workspace', 'moving',
                                    'unarmed', 'pending', 'quaternion'])
def test_rejected_target_sends_nothing(motion, failure):
    goal = target(motion, .01, 0.)
    if failure == 'distance':
        goal = target(motion, .051, 0.)
    elif failure == 'rotation':
        goal = target(motion, .01, 10.1)
    elif failure == 'workspace':
        motion.state['tcp_pose'][0] = .995
        goal = target(motion, .002, 0.)
    elif failure == 'moving':
        motion.state['joint_velocity'][0] = .02
    elif failure == 'unarmed':
        motion.armed = False
    elif failure == 'pending':
        motion.pending_pose = target(motion, .02, 0.)
    elif failure == 'quaternion':
        goal[3:] = 0.
    with pytest.raises(HTTPException):
        motion.pose_step('owner', goal, native=True)
    assert motion.sent == [] and motion.legacy == []


def test_legacy_step_retains_one_mm_range(motion):
    with pytest.raises(HTTPException):
        motion.pose_step('owner', target(motion, .0011, 0.))
    result = motion.pose_step('owner', target(motion, .001, 0.))
    assert result['native_trajectory'] is False
    assert motion.sent == [] and len(motion.legacy) == 1
    assert motion.legacy[0][1] == dict(strict=True, max_linear_vel=.005,
                                      max_angular_vel=.03)


def test_lost_hardware_feedback_halts(motion):
    def unavailable():
        raise RuntimeError('feedback unavailable')
    motion.robot.get_live_state = unavailable
    with pytest.raises(RuntimeError, match='feedback unavailable'):
        motion.watchdog()
    assert not motion.armed and motion.stopped == ['robot', 'gripper']


@pytest.mark.parametrize('expired', ['authorization', 'command', 'lease'])
def test_expiry_stops_before_trying_failed_feedback(motion, expired):
    reads = []
    def unavailable():
        reads.append(True)
        raise RuntimeError('feedback unavailable')
    motion.robot.get_live_state = unavailable
    if expired == 'authorization':
        motion.expires = 99.
    elif expired == 'command':
        motion.command_deadline = 99.
    else:
        motion.bridge.active = False
    motion.watchdog()
    assert not motion.armed and motion.stopped == ['robot', 'gripper']
    assert reads == []


@pytest.mark.parametrize('failure', ['camera', 'workspace', 'joint_limit', 'nan',
                                    'velocity_nan', 'velocity_shape', 'quaternion'])
def test_motion_watchdog_stops_on_invalid_feedback(motion, failure):
    motion.command_deadline = 135.
    if failure == 'camera':
        motion.bridge.collector.camera_mgr.cameras['left']._capture_slot._timestamp.value = 99.
    elif failure == 'workspace':
        motion.state['tcp_pose'][0] = 1.01
    elif failure == 'joint_limit':
        motion.state['joint_position'][0] = 2.79
    elif failure == 'velocity_nan':
        motion.state['joint_velocity'][3] = float('nan')
    elif failure == 'velocity_shape':
        motion.state['joint_velocity'] = [0.]*6
    elif failure == 'quaternion':
        motion.state['tcp_pose'][3:] = [0., 0., 0., 0.]
    else:
        motion.state['tcp_pose'][0] = float('nan')
    motion.watchdog()
    assert not motion.armed and motion.stopped == ['robot', 'gripper']


def test_watchdog_accepts_camera_captured_during_hardware_read(motion, monkeypatch):
    clock = [100.]
    monkeypatch.setattr(motion.module.time, 'monotonic', lambda: clock[0])
    motion.command_deadline = 135.
    def hardware_read():
        clock[0] = 100.02
        for camera in motion.bridge.collector.camera_mgr.cameras.values():
            camera._capture_slot._timestamp.value = clock[0]
        return motion.state
    motion.robot.get_live_state = hardware_read
    motion.watchdog()
    assert motion.armed and motion.command_deadline == 135.
    assert motion.stopped == []


def test_feedback_preserves_home_deadline_but_acknowledges_settled_pose(motion):
    motion.command_deadline = 135.
    motion.pending_pose = np.array(motion.state['tcp_pose'])
    motion.home.pending = np.array(motion.state['joint_position'])
    motion.feedback('owner')
    assert motion.command_deadline == 135.
    motion.home.pending = None
    motion.state['joint_velocity'][0] = .01
    motion.feedback('owner')
    assert motion.command_deadline == 135.
    motion.state['joint_velocity'][0] = 0.
    motion.feedback('owner')
    assert motion.command_deadline == 0.
    assert motion.pending_pose is None
    motion.gripper_step('owner', .025)
    assert motion.grip == [(.025, .01, 20.)]


def test_pending_cartesian_completion_blocks_gripper_deadline_replacement(motion):
    # At the target but not yet acknowledged as settled, ready() alone permits
    # this pose. The explicit pending guard must keep the arm deadline intact.
    motion.pending_pose = np.array(motion.state['tcp_pose'])
    motion.command_deadline = 135.
    with pytest.raises(HTTPException, match='arm motion completion'):
        motion.gripper_step('owner', .025)
    assert motion.grip == [] and motion.command_deadline == 135.


@pytest.mark.parametrize('failure', ['step_range', 'velocity_cap', 'force_cap'])
def test_gripper_limits_remain_enforced(motion, failure):
    width = .026 if failure == 'step_range' else .025
    if failure != 'step_range':
        params = motion.robot._gripper.params()
        if failure == 'velocity_cap':
            params.min_vel = .03
            params.max_vel = .04
        else:
            params.max_force = 10.
        motion.robot._gripper.params = lambda: params
    with pytest.raises(HTTPException):
        motion.gripper_step('owner', width)
    assert motion.grip == []


def test_repeated_feedback_does_not_extend_fixed_deadline(motion, monkeypatch):
    motion.pose_step('owner', target(motion, .01, 0.), native=True)
    for now in (101., 110., 134.):
        monkeypatch.setattr(motion.module.time, 'monotonic', lambda: now)
        for camera in motion.bridge.collector.camera_mgr.cameras.values():
            camera._capture_slot._timestamp.value = now
        motion.feedback('owner')
        assert motion.command_deadline == 135. and motion.armed
    monkeypatch.setattr(motion.module.time, 'monotonic', lambda: 136.)
    motion.feedback('owner')
    assert not motion.armed and motion.stopped == ['robot', 'gripper']


def test_native_route_halts_when_sdk_submission_raises(motion, monkeypatch):
    fake_home = ModuleType('tested_native_collector.joint_home')
    fake_home.JointHome = lambda m: SimpleNamespace(owner=None, pending=None)
    monkeypatch.setitem(sys.modules, fake_home.__name__, fake_home)
    installed = motion.module.install_supervised_motion(motion.bridge)
    installed.armed, installed.expires, installed.owner = True, 200., 'owner'
    def failed_send(*args, **kw):
        raise RuntimeError('SDK submission failed')
    motion.robot._robot.SendCartesianMotionForce = failed_send
    endpoint = next(route.endpoint for route in motion.bridge.collector.app.routes
                    if route.path == '/rpent/supervised/pose-target')
    request = Request({'type': 'http', 'headers': [(b'x-rpent-session', b'owner')]})
    command = motion.module.PoseStep(pose=target(motion, .01, 0.).tolist())
    with pytest.raises(RuntimeError, match='SDK submission failed'):
        asyncio.run(endpoint(command, request))
    assert not installed.armed and installed.command_deadline == 0.
    assert motion.stopped == ['robot', 'gripper']


@pytest.mark.parametrize('pending', ['pose', 'home', 'none'])
def test_gripper_hold_preserves_active_arm_deadline(motion, monkeypatch, pending):
    fake_home = ModuleType('tested_native_collector.joint_home')
    fake_home.JointHome = lambda m: SimpleNamespace(owner=None, pending=None)
    monkeypatch.setitem(sys.modules, fake_home.__name__, fake_home)
    installed = motion.module.install_supervised_motion(motion.bridge)
    installed.armed, installed.expires, installed.owner = True, 200., 'owner'
    installed.command_deadline = 135.
    if pending == 'pose':
        installed.pending_pose = target(motion, .01, 0.)
    elif pending == 'home':
        installed.home.pending = np.ones(7)*.1
    endpoint = next(route.endpoint for route in motion.bridge.collector.app.routes
                    if route.path == '/rpent/supervised/gripper-hold')
    request = Request({'type': 'http', 'headers': [(b'x-rpent-session', b'owner')]})
    assert asyncio.run(endpoint(request))['held'] is True
    assert installed.command_deadline == (0. if pending == 'none' else 135.)
    assert installed.armed and motion.stopped == ['gripper']
