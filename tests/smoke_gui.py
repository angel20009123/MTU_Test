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
    app.protocol_version.set('IPv6')
    app.protocol_changed()
    app.diagnostic_preset()
    app.values['sizes'].set('1600,1800,20000,65500')
    app.values['lower'].set('1280')
    app.start('packets')
    wait_done()
    assert len(app.probes) == 8, app.report
    assert all(p.status == 'ok' and p.ip_version == 6 for p in app.probes), app.probes
    assert app.probes[0].packet_size == 1648
    assert app.report['parameters']['ip_version'] == 6
    assert '65548' in app.status.get(), app.status.get()
    print('IPv6 packet test:', app.summary.get())
    app.values['upper'].set('2000')
    app.start('mtu')
    wait_done()
    if app.report['result']['state'] == 'error':
        assert '管理员权限' in app.status.get()
    else:
        assert app.report['result']['mtu'] == 2000, app.report
    print('IPv6 MTU:', app.status.get())
finally:
    app.close()
