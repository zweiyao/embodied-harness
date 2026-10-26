"""Collector integration checks with fake hardware; never connects to a robot."""
import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException

spec = importlib.util.spec_from_file_location(
    'tested_joint_home', Path(os.environ['FLEXIV_HOME_SOURCE']) / 'joint_home.py'
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def home(monkeypatch):
    modes = SimpleNamespace(NRT_PRIMITIVE_EXECUTION='primitive',
                            NRT_CARTESIAN_MOTION_FORCE='cartesian')
    monkeypatch.setitem(sys.modules, 'flexivrdk', SimpleNamespace(Mode=modes, JPos=list))
    state = {'joint_position': [0.0]*7, 'joint_velocity': [0.0]*7,
             'mode': 'Mode.NRT_CARTESIAN_MOTION_FORCE', 'tcp_pose': [0.0]*7}
    commands, audits = [], []
    native = SimpleNamespace(
        SwitchMode=lambda mode: commands.append(('mode', mode)),
        ExecutePrimitive=lambda name, args: commands.append((name, args)),
        primitive_states=lambda: {'reachedTarget': False},
    )
    robot = SimpleNamespace(_robot=native, config={'start_vel_scale': 30})
    motion = SimpleNamespace(ready=lambda token, **kw: (robot, state, None),
                             audit=lambda name, **kw: audits.append(name),
                             pending_pose=None, command_deadline=0.)
    h = module.JointHome(motion)
    h.goal = np.ones(7)*.1
    h.target = lambda robot, state: (h.goal, {})
    h.preview = lambda: {'path_retains_required_margin': True}
    h.state, h.robot, h.commands, h.audits = state, robot, commands, audits
    return h


def start(home):
    assert home.step('owner')['motion'] == 'MoveJ'
    home.state['mode'] = 'Mode.NRT_PRIMITIVE_EXECUTION'


@pytest.mark.parametrize('flag_type', [bool, int, np.int32])
def test_submit_once_then_require_measured_arrival(home, flag_type):
    start(home)
    home.robot._robot.primitive_states = lambda: {'reachedTarget': flag_type(0)}
    for _ in range(3):
        assert not home.step('owner')['reached']
    home.robot._robot.primitive_states = lambda: {'reachedTarget': flag_type(1)}
    assert not home.step('owner')['reached']  # API flag alone is insufficient.
    home.state['joint_position'] = home.goal.tolist()
    home.state['joint_velocity'] = [.01]*7
    assert not home.step('owner')['reached']
    home.state['joint_velocity'] = [0.0]*7
    assert home.step('owner')['reached']
    sent = [x for x in home.commands if x[0] == 'MoveJ']
    assert len(sent) == 1
    np.testing.assert_allclose(sent[0][1]['target'], np.rad2deg(home.goal))
    assert sent[0][1]['jntVelScale'] == 30
    assert home.motion.command_deadline == 0
    assert home.commands[-1] == ('mode', 'cartesian')
    # Fake driver exposes no gripper; the entire path must leave it untouched.


@pytest.mark.parametrize('failure', ['gate', 'path', 'velocity', 'scale'])
def test_preflight_failure_sends_no_motion(home, failure):
    if failure == 'gate':
        def blocked(*args, **kwargs):
            raise HTTPException(409, 'operator not armed')
        home.motion.ready = blocked
    elif failure == 'path':
        home.preview = lambda: {'path_retains_required_margin': False}
    elif failure == 'velocity':
        home.state['joint_velocity'] = [.01]*7
    else:
        home.robot.config['start_vel_scale'] = 100
    with pytest.raises(HTTPException):
        home.step('owner')
    assert home.commands == []


@pytest.mark.parametrize('failure', ['reference', 'mode', 'feedback', 'unavailable'])
def test_poll_failure_does_not_resend(home, failure):
    start(home)
    if failure == 'reference':
        home.goal = np.ones(7)*.2
    elif failure == 'mode':
        home.state['mode'] = 'Mode.IDLE'
    elif failure == 'feedback':
        home.robot._robot.primitive_states = lambda: {'reachedTarget': 'false'}
    else:
        home.robot._robot.primitive_states = lambda: {}
    with pytest.raises((HTTPException, KeyError)):
        home.step('owner')
    assert len([x for x in home.commands if x[0] == 'MoveJ']) == 1


@pytest.mark.parametrize('value', [-1, 2, 0.0, 1.0, '0', '1', None, [1]])
def test_invalid_primitive_flags_fail_closed(home, value):
    start(home)
    home.state['joint_position'] = home.goal.tolist()
    home.robot._robot.primitive_states = lambda: {'reachedTarget': value}
    with pytest.raises(HTTPException):
        home.step('owner')
    assert len([x for x in home.commands if x[0] == 'MoveJ']) == 1


@pytest.mark.parametrize('expired', [False, True])
def test_real_gate_limits_primitive_mode_to_owned_home(monkeypatch, expired):
    path = Path(os.environ['FLEXIV_HOME_SOURCE']) / 'supervised_motion.py'
    spec = importlib.util.spec_from_file_location('tested_supervised_motion', path)
    sm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sm)
    monkeypatch.setattr(sm.time, 'monotonic', lambda: 100.)
    stopped = []
    state = {'fault': False, 'operational': True, 'control_initialized': True,
             'mode': 'Mode.NRT_PRIMITIVE_EXECUTION', 'joint_position': [0.]*7,
             'joint_velocity': [0.]*7, 'tcp_pose': [.4, 0., .2, 1., 0., 0., 0.],
             'gripper_is_moving': False}
    robot = SimpleNamespace(get_live_state=lambda: state,
                            _workspace_min=np.array([0., -.8, -.49]),
                            _workspace_max=np.array([1., .8, 1.]),
                            _robot=SimpleNamespace(Stop=lambda: stopped.append('robot')),
                            _gripper=None)
    cameras = {k: SimpleNamespace(_capture_slot=SimpleNamespace(_timestamp=SimpleNamespace(value=100.)))
               for k in ('left', 'right')}
    bridge = SimpleNamespace(authorize=lambda token: None, allow_motion=True,
                             driver=lambda: robot, active=True, token='owner',
                             collector=SimpleNamespace(config={}, camera_mgr=SimpleNamespace(cameras=cameras)))
    motion = sm.SupervisedMotion(bridge)
    motion.armed, motion.expires = True, 200.
    motion.command_deadline = 99. if expired else 150.
    motion.home = SimpleNamespace(owner='owner', pending=np.ones(7))
    if expired:
        with pytest.raises(HTTPException):
            motion.ready('owner', home=True)
        assert stopped == ['robot'] and not motion.armed
    else:
        assert motion.ready('owner', home=True)[0] is robot
        with pytest.raises(HTTPException):
            motion.ready('owner', home=False)
        with pytest.raises(HTTPException):
            motion.ready('other', home=True)
