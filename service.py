from argparse import ArgumentParser, Namespace
import logging
import os
import re
import signal
from subprocess import getstatusoutput
import sys
import time
from types import FrameType

LOG_PATH = os.path.expanduser('~/.local/share/wacom_ff/service.log')
if not os.path.isdir(os.path.dirname(LOG_PATH)):
    os.makedirs(os.path.dirname(LOG_PATH))
logging.basicConfig(filename=LOG_PATH, filemode='a', style='{',
                    format=('[{levelname:^8}] {asctime} | {module}:{lineno} in {funcName!r}: '
                            '{message}'))
logger = logging.getLogger('wacom_ff')
SIGNALS = {getattr(signal, a): a for a in dir(signal) if bool(re.match('SIG[^_]', a))}


def xdotool_get_cursor_position():
    """Get the position of the mouse."""
    r, output = getstatusoutput('xdotool getmouselocation')
    if r:
        raise ValueError(f'xdotool exited with code {r}', output)
    m = re.fullmatch(r'x:(?P<x>\d+) y:(?P<y>\d+) screen:(?P<screen>\d+)'
                     r' window:(?P<window_id>\d+)', output.strip())
    if not m:
        raise ValueError(f'xdotool returned invalid data: {output!r}')
    d = m.groupdict()
    return int(d['x']), int(d['y'])


class PseudoRange:
    """Implement pseudo ranges."""
    def __init__(self, start: int, stop: int, step: int = 1):
        self.start, self.stop, self.step = start, stop, step

    def __contains__(self, value: int):
        return (isinstance(value, int)
                and value >= self.start <= value < self.stop
                and (value - self.start) % self.step == 0)

    def __repr__(self):
        return f'range({self.start}, {self.stop}, {self.step})'


class MonitorDummy:
    """Implement a monitor dummy structure."""
    def __init__(self, id_num: int, name: str, name_1: str,
                 width_px: int, height_px: int,
                 x_offset: int = 0, y_offset: int = 0,
                 width_phys: float = None, height_phys: float = None):
        self.name, self.name_1, self.id_num = name, name_1, id_num
        self.width_px, self.height_px = width_px, height_px
        self.width_phys, self.height_phys = width_phys, height_phys
        self.x_offset, self.y_offset = x_offset, y_offset

    @property
    def x_range(self):
        "Return horizontal pixel range."
        return PseudoRange(self.x_offset, self.x_offset + self.width_px)

    @property
    def y_range(self):
        "Return vertical pixel range."
        return PseudoRange(self.y_offset, self.y_offset + self.height_px)

    def __contains__(self, location: tuple):
        x, y = location
        return x in self.x_range and y in self.y_range


class MonitorConfiguration:
    def __init__(self, *monitors):
        self.monitors = list(monitors)

    def __len__(self):
        return len(self.monitors)

    def get_monitor_from_position(self, position: tuple = None):
        """Return the monitor on which the mouse currently is."""
        if position is None:
            position = xdotool_get_cursor_position()
        x, y = position
        for m in self.monitors:
            if (x, y) in m:
                return m
        return None


def get_xrandr_monitor_data():
    line_re = (r'\s*(?P<id_num>\d+): (?:\+|.)(?P<name_1>.+) (?P<width_px>\d+)'
               r'/(?P<width_phys>\d+)x(?P<height_px>\d+)/(?P<height_phys>\d+)'
               r'\+(?P<x_offset>\d+)\+(?P<y_offset>\d+)\s+(?P<name>.+)')
    intify = {'id_num', 'width_px', 'height_px', 'x_offset', 'y_offset'}
    floatify = {'width_phys', 'height_phys'}
    r, output = getstatusoutput('xrandr --listactivemonitors')
    if r:
        raise ValueError(f'xrandr failed with code {r}', output)
    lines = list(map(str.strip, output.split('\n')))
    out = {}
    for l in lines:
        m = re.fullmatch(line_re, l)
        if not m:
            continue
        d = m.groupdict()
        for k in intify:
            d[k] = int(d[k])
        for k in floatify:
            d[k] = float(d[k])
        out[d['id_num']] = MonitorDummy(**d)
    return MonitorConfiguration(*out.values())


class WacomService:
    """Implement a focus following service."""

    def __init__(self, args: Namespace):
        try:
            self.monitor_config = get_xrandr_monitor_data()
        except Exception as e:
            logger.critical("Failed to get monitor config: %r", e)
            sys.exit(1)
        self.options = args
        self.every = args.every
        self.device = args.device
        self.always_poll = args.always_poll

    def start(self):
        """Start the service."""
        logger.info('Starting...')
        signal.signal(signal.SIGPOLL, self.poll)
        signal.signal(signal.SIGALRM, self.poll)
        signal.signal(signal.SIGUSR1, lambda *a: self.stop())
        if self.every > 0:
            signal.alarm(self.every)
        return self

    def stop(self):
        """Stop the service."""
        logger.info('Stopping...')
        signal.signal(signal.SIGPOLL, signal.SIG_DFL)
        signal.signal(signal.SIGALRM, signal.SIG_DFL)
        signal.signal(signal.SIGUSR1, lambda *a: self.start())
        if self.every > 0:
            signal.alarm(0)

    def poll(self, sig: int = None, _: FrameType = None):
        """Set the drawing area."""
        logger.debug('Caught signal %s', SIGNALS.get(sig, sig))
        if sig == signal.SIGPOLL or self.always_poll:
            logger.info('Reloading monitor config')
            try:
                self.monitor_config = get_xrandr_monitor_data()
            except Exception:
                logger.error('Failed to load monitor config!')
                return
        if len(self.monitor_config) < 2:
            logger.warning('Only one monitor found! Ignoring event!')
            return
        m = self.monitor_config.get_monitor_from_position()
        if m is None:
            logger.error('Could not determine the focussed monitor!')
            return
        cmd = 'xsetwacom set %r MapToOutput %r' % (self.device, m.name)
        logger.debug('Running %s', cmd)
        r, o = getstatusoutput(cmd)
        if r:
            logger.error('xsetwacom exited with code %r: %s', r, o)
        if self.every > 0:
            signal.alarm(self.every)


ap = ArgumentParser(prog='wacom_ff', conflict_handler='resolve')
ap.add_argument('--every', type=int, default=0, metavar='N',
                help='Automatically update ever N seconds')
ap.add_argument('--log-level', type=int, default=20,
                help='Set log level (high values mean quiet operation)')
ap.add_argument('--device', required=True, help='Which wacom device to handle')
ap.add_argument('--always-poll', action='store_true',
                help='Wether to always reload the monitor configuration (slower)')


if __name__ == '__main__':
    args = ap.parse_args()
    logger.setLevel(args.log_level)
    s = WacomService(args).start()

    def quit_service(sig: int, _: FrameType = None):
        """Stop the service and quit."""
        logger.info('Caught signal %s. Quitting now.', SIGNALS.get(sig, sig))
        s.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, quit_service)

    while True:
        time.sleep(60)
