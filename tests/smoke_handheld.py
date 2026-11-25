"""Headless smoke: python tests/smoke_handheld.py ABS_GB_GBC_OR_GBA_ROM ABS_CORE."""
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
# Exercise the no-output-device path, not an audio device that accepts samples.
os.environ['SDL_AUDIODRIVER'] = 'retro-pocket-no-device-test'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from handheld_player import Player, main, pg


def smoke(rom, core):
    # Drive the real main loop and native core. Inject SDL events between frames,
    # not button sets at the libretro boundary.
    tick = 0
    step = Player.step

    def post(event_type, **fields):
        pg.event.post(pg.event.Event(event_type, **fields))

    def scripted_step(player, buttons):
        nonlocal tick
        step(player, buttons)
        tick += 1
        if tick == 90:
            assert player.audio_status and player.channel is None
            # GB/GBC 160x144, Super Game Boy border 256x224, GBA 240x160; something drawn.
            w, h, frame = player.frame
            assert (w, h) in ((160, 144), (256, 224), (240, 160)) and len(set(frame)) > 1, (w, h)
            post(pg.KEYDOWN, key=pg.K_RETURN)
        elif tick == 96:
            assert buttons == {'start'}
            post(pg.KEYUP, key=pg.K_RETURN)
        elif tick == 130:
            player.window.size = (460, 580)
            player.draw(set())
            assert player.screen.get_size() == (460, 580)
            post(pg.MOUSEBUTTONDOWN, button=1, pos=player.pads['left'].center)
        elif tick == 136:
            assert buttons == {'left'}
            post(pg.MOUSEBUTTONUP, button=1, pos=player.pads['left'].center)
        elif tick == 165:
            player.window.size = (1000, 390)
            player.draw(set())
            assert player.screen.get_size() == (1000, 390)
            post(pg.MOUSEBUTTONDOWN, button=1, pos=player.pads['up'].center)
        elif tick == 171:
            assert buttons == {'up'}
            post(pg.MOUSEBUTTONUP, button=1, pos=player.pads['up'].center)
        elif tick == 200:
            assert buttons == set()
            post(pg.KEYDOWN, key=pg.K_ESCAPE)
        elif tick > 200:
            raise AssertionError('Escape did not exit the player')

    with TemporaryDirectory(prefix='retro-pocket-smoke-') as tmp:
        saves = Path(tmp) / 'saves'
        with patch.object(Player, 'step', scripted_step):
            status = main([rom, core, str(saves), Path(rom).stem])
        assert status == 0 and tick == 200 and not pg.display.get_init()
    print(f'{Path(rom).name} without an audio device: keyboard Start, mouse D-pad after two resizes, and clean Escape exit')


if __name__ == '__main__':
    smoke(*sys.argv[1:])
