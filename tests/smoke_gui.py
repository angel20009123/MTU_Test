"""Exercise the GUI event queue with real local ICMP probes."""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import App

app = App()
app.withdraw()


def wait_done():
    deadline = time.monotonic() + 15
    while app.running and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.running, "GUI worker did not complete"


try:
    app.preset(True)
    app.values['sizes'].set('32,20000,24000,32768,48000,60000,65500')
    app.values['count'].set('2')
    app.values['interval'].set('0')
    app.start('packets')
    wait_done()
    assert len(app.probes) == 14, app.report
    assert all(p.status == 'ok' for p in app.probes), app.probes
    assert app.report['result']['largest_successful_payload'] == 65500
    assert len(app.group_table.get_children()) == 7
    print('Packet test:', app.summary.get())
    app.values['upper'].set('1500')
    app.start('mtu')
    wait_done()
    assert app.report['result']['mtu'] == 1500, app.report
    assert app.report['result']['state'] == 'lower_bound'
    print('MTU test:', app.status.get())
finally:
    app.close()
